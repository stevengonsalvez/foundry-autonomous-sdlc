"""ledger-api over a real socket on an ephemeral port, with an in-memory store."""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time
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


def test_events_are_stored_even_when_the_sender_asks_to_reconcile(served: tuple[str, MemoryBranchStore]) -> None:
    # The foreman sends reconcile=true on its batches, but this server has no GitHub client (the PAT stays
    # with the foreman). Rejecting the batch left the live ledger empty and the control center blank.
    base, store = served
    status, _, body = call(f"{base}/ingest", {"events": [ticket_event()], "reconcile": True})
    assert status == 200, body
    assert json.loads(call(f"{base}/state.json")[2])["tickets"]
    assert store.commits != []


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


# -- hardening: ingest token, bounded handlers, startup refusals -----------------------------------------

LEDGER_TOKEN = "ledger-token-abc"


@pytest.fixture
def guarded() -> Iterator[tuple[str, MemoryBranchStore]]:
    store = MemoryBranchStore()
    server = make_server(store, "127.0.0.1", 0, token=LEDGER_TOKEN)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", store
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def post_ingest(base: str, body: Any, token: str | None) -> int:
    req = urllib.request.Request(f"{base}/ingest", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    if token is not None:
        req.add_header("x-factory-token", token)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_ingest_requires_the_ledger_token_when_configured(guarded: tuple[str, MemoryBranchStore]) -> None:
    base, store = guarded
    assert post_ingest(base, {"events": [ticket_event()]}, None) == 401
    assert post_ingest(base, {"events": [ticket_event()]}, "wrong") == 401
    assert store.commits == []
    assert post_ingest(base, {"events": [ticket_event()]}, LEDGER_TOKEN) == 200
    assert len(store.commits) == 1
    assert call(f"{base}/state.json")[0] == 200     # reads stay open: the control center has no token


def test_the_ledger_token_is_checked_before_the_body_is_read(guarded: tuple[str, MemoryBranchStore]) -> None:
    base, _ = guarded
    host, port = base.removeprefix("http://").split(":")
    sock = socket.create_connection((host, int(port)), timeout=5)
    sock.sendall(b"POST /ingest HTTP/1.1\r\nHost: x\r\nContent-Length: 5000\r\n\r\n")
    reply = sock.recv(4096).decode()
    sock.close()
    assert reply.startswith("HTTP/1.1 401"), reply


def test_handlers_time_out_idle_sockets() -> None:
    from sdlc_factory.ledger_api import _Handler

    assert _Handler.timeout == 30


def test_concurrent_handlers_are_bounded() -> None:
    store = MemoryBranchStore()
    server = make_server(store, "127.0.0.1", 0, max_concurrent=2, slot_wait_s=0.2)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    addr = server.server_address[:2]
    try:
        idle = [socket.create_connection(addr, timeout=5) for _ in range(2)]   # hold both slots, send nothing
        time.sleep(0.3)
        extra = socket.create_connection(addr, timeout=5)
        extra.sendall(b"GET /healthz HTTP/1.1\r\nHost: x\r\n\r\n")
        try:
            refused = extra.recv(4096)
        except ConnectionResetError:
            refused = b""
        assert refused == b""                                                # refused: no slot
        extra.close()
        for sock in idle:
            sock.close()
        time.sleep(0.3)
        assert call(f"http://{addr[0]}:{addr[1]}/healthz")[0] == 200         # slots come back
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize(("env", "missing"), [
    ({}, "LEDGER_TOKEN"),
    ({"LEDGER_TOKEN": "t", "DOLT_USER": "ledger"}, "DOLT_PASSWORD"),
    ({"LEDGER_TOKEN": "t", "DOLT_PASSWORD": "p"}, "DOLT_USER"),
    ({"LEDGER_TOKEN": " ", "DOLT_USER": "ledger", "DOLT_PASSWORD": "p"}, "LEDGER_TOKEN"),
])
def test_main_refuses_to_start_without_its_credentials(env: dict[str, str], missing: str) -> None:
    from sdlc_factory import ledger_api

    with pytest.raises(SystemExit, match=missing):
        ledger_api.main(env)


def test_the_dolt_connector_has_no_default_credentials() -> None:
    import inspect

    from sdlc_factory.ledger_store import pymysql_connector

    params = inspect.signature(pymysql_connector).parameters
    assert params["user"].default is inspect.Parameter.empty
    assert params["password"].default is inspect.Parameter.empty
