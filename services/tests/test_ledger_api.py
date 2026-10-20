"""ledger-api over a real socket on an ephemeral port, with an in-memory store."""

from __future__ import annotations

import http.client
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest
from sdlc_agents.ledger import events, fold, model
from sdlc_agents.ledger.store import STATE_FILE, MemoryBranchStore

from sdlc_factory.ledger_api import ISSUES_FILE, make_server

NOW = "2026-10-20T10:00:00Z"


def ticket_event(number: int = 7, title: str = "Show delivery date") -> dict[str, Any]:
    t = model.ticket(
        number=number,
        kind="issue",
        title=title,
        author="po",
        opened_at=NOW,
        closed_at=None,
        labels=("type:feature", "stage:refining"),
        state_data=None,
    )
    return events.make("ticket.updated", NOW, {"ticket": t}, issue=number)


@pytest.fixture
def served() -> Iterator[tuple[str, MemoryBranchStore]]:
    store = MemoryBranchStore()
    server = make_server(store, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", store
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def call(url: str, body: Any = None, *, raw: bytes | None = None) -> tuple[int, dict[str, str], bytes]:
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    req = urllib.request.Request(url, data=data, method="GET" if data is None else "POST")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def test_healthz(served: tuple[str, MemoryBranchStore]) -> None:
    base, _ = served
    status, _, body = call(f"{base}/healthz")
    assert status == 200 and json.loads(body) == {"ok": True}


def test_state_json_is_404_before_the_first_ingest(served: tuple[str, MemoryBranchStore]) -> None:
    base, _ = served
    status, _, body = call(f"{base}/state.json")
    assert status == 404 and json.loads(body)["ok"] is False


def test_ingesting_a_ticket_updated_event_serves_a_valid_v1_state(served: tuple[str, MemoryBranchStore]) -> None:
    base, store = served
    status, _, body = call(f"{base}/ingest", {"events": [ticket_event()]})
    reply = json.loads(body)
    assert status == 200 and reply["ok"] is True and reply["tickets"] == 1 and reply["head"] == store.head

    status, headers, body = call(f"{base}/state.json")
    doc = json.loads(body)
    assert status == 200
    assert headers["Content-Type"].startswith("application/json")
    assert headers["Cache-Control"] == "no-store"
    assert doc["version"] == fold.VERSION == 1
    assert [t["issue"] for t in doc["tickets"]] == [7]
    assert body.decode() == store.files[STATE_FILE]  # served as stored, not re-encoded
    assert {"tickets", "agents", "cost", "environments", "ledger"} <= doc.keys()


def test_ingesting_the_same_event_twice_adds_no_duplicate_ticket(served: tuple[str, MemoryBranchStore]) -> None:
    base, _ = served
    event = ticket_event()
    call(f"{base}/ingest", {"events": [event]})
    call(f"{base}/ingest", {"events": [event]})
    doc = json.loads(call(f"{base}/state.json")[2])
    assert len(doc["tickets"]) == 1


def test_issues_json_is_an_empty_list_until_a_file_exists(served: tuple[str, MemoryBranchStore]) -> None:
    base, store = served
    status, headers, body = call(f"{base}/issues.json")
    assert status == 200 and json.loads(body) == [] and headers["Cache-Control"] == "no-store"
    store.files[ISSUES_FILE] = '[{"number":3}]'
    assert json.loads(call(f"{base}/issues.json")[2]) == [{"number": 3}]


@pytest.mark.parametrize("path", ["/nope", "/state.json/extra", "/ingest"])
def test_unknown_paths_and_wrong_methods_are_404_or_405(served: tuple[str, MemoryBranchStore], path: str) -> None:
    base, _ = served
    status, _, body = call(f"{base}{path}")
    assert status in (404, 405) and json.loads(body)["ok"] is False


def test_post_to_an_unknown_path_is_404(served: tuple[str, MemoryBranchStore]) -> None:
    base, _ = served
    assert call(f"{base}/nope", {"events": []})[0] == 404


@pytest.mark.parametrize(
    "raw",
    [b"not json", b"[]", b'{"events": "x"}', b'{"events": [{"bad": 1}]}'],
    ids=["not-json", "not-object", "events-not-list", "invalid-event"],
)
def test_a_bad_ingest_body_is_400_and_writes_nothing(served: tuple[str, MemoryBranchStore], raw: bytes) -> None:
    base, store = served
    status, _, body = call(f"{base}/ingest", raw=raw)
    assert status == 400 and json.loads(body)["ok"] is False
    assert store.commits == []


def test_reconcile_without_github_is_a_400_not_a_crash(served: tuple[str, MemoryBranchStore]) -> None:
    base, store = served
    status, _, body = call(f"{base}/ingest", {"events": [], "reconcile": True})
    assert status == 400 and "GitHub" in json.loads(body)["error"]
    assert store.commits == []


def test_an_oversized_body_is_rejected_from_the_header_alone(served: tuple[str, MemoryBranchStore]) -> None:
    base, store = served
    conn = http.client.HTTPConnection(base.removeprefix("http://"), timeout=10)
    conn.putrequest("POST", "/ingest")
    conn.putheader("Content-Length", str(9 * 1024 * 1024))
    conn.endheaders()  # the body is never sent: the server must not wait for it
    resp = conn.getresponse()
    assert resp.status == 413 and json.loads(resp.read())["ok"] is False
    conn.close()
    assert store.commits == []
