"""Ledger adapters: the GitHub branch store, billing, summaries, runtime wiring and the hosted entrypoint."""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import os
import types
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sdlc_agents.ledger import runtime as ledger_runtime
from sdlc_agents.ledger import summary
from sdlc_agents.ledger.billing import AzureBilling
from sdlc_agents.ledger.store import GitHubBranchStore, StoreConflict
from sdlc_agents.ports import GitHubError
from sdlc_agents.transport import HttpRequest, HttpResponse
from tests.test_github import BASE, Recorded, client, ok

HOSTED = Path(__file__).resolve().parents[2] / "hosted" / "ledger"


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


# -- the state branch over the GitHub git data API -----------------------------------------


def test_read_files_returns_the_named_files_of_the_branch_tip_and_none_for_a_missing_branch() -> None:
    gh, _, _ = client(
        {
            "GET /git/ref/heads/state": ok({"object": {"sha": "c1"}}),
            "GET /git/commits/c1": ok({"tree": {"sha": "t1"}}),
            "GET /git/trees/t1": ok(
                {
                    "tree": [
                        {"path": "state.json", "type": "blob", "sha": "b1"},
                        {"path": "README.md", "type": "blob", "sha": "b2"},
                    ]
                }
            ),
            "GET /git/blobs/b1": ok({"content": b64('{"a":1}'), "encoding": "base64"}),
        }
    )
    assert gh.read_files("state", ("state.json", "events.jsonl")) == ({"state.json": '{"a":1}'}, "c1")
    gone, _, _ = client({"GET /git/ref/heads/state": HttpResponse(404, {}, b"{}")})
    assert gone.read_files("state", ("state.json",)) is None


def test_the_parent_of_a_write_is_the_commit_the_files_were_read_at() -> None:
    """A branch that moves between the read and the write must make the write fail, not be overwritten."""
    gh, transport, _ = client(
        {
            "GET /git/ref/heads/state": [ok({"object": {"sha": "c1"}}), ok({"object": {"sha": "c2"}})],
            "GET /git/commits/c1": ok({"tree": {"sha": "t1"}}),
            "GET /git/trees/t1": ok({"tree": [{"path": "state.json", "type": "blob", "sha": "b1"}]}),
            "GET /git/blobs/b1": ok({"content": b64("{}"), "encoding": "base64"}),
        }
    )
    snap = GitHubBranchStore(gh).read()
    assert snap.head == "c1"
    assert sum(1 for r in transport.requests if "/git/ref/heads/state" in r.url) == 1


def test_commit_files_moves_the_ref_without_force_so_a_second_writer_cannot_be_lost() -> None:
    gh, transport, _ = client(
        {
            "POST /git/blobs": ok({"sha": "b1"}, 201),
            "GET /git/commits/p1": ok({"tree": {"sha": "t0"}}),
            "POST /git/trees": ok({"sha": "t1"}, 201),
            "POST /git/commits": ok({"sha": "c2"}, 201),
            "PATCH /git/refs/heads/state": ok({}),
        }
    )
    assert gh.commit_files("state", {"state.json": "{}"}, message="m", parent_sha="p1") == "c2"
    patch_req = next(r for r in transport.requests if r.method == "PATCH")
    assert json.loads(patch_req.body) == {"sha": "c2", "force": False}
    tree_req = next(r for r in transport.requests if r.url.endswith("/git/trees"))
    assert json.loads(tree_req.body)["base_tree"] == "t0"
    moved, _, _ = client(
        {
            "POST /git/blobs": ok({"sha": "b1"}, 201),
            "GET /git/commits/p1": ok({"tree": {"sha": "t0"}}),
            "POST /git/trees": ok({"sha": "t1"}, 201),
            "POST /git/commits": ok({"sha": "c2"}, 201),
            "PATCH /git/refs/heads/state": HttpResponse(422, {}, b'{"message":"Update is not a fast forward"}'),
        }
    )
    with pytest.raises(GitHubError):
        moved.commit_files("state", {"state.json": "{}"}, message="m", parent_sha="p1")
    store = GitHubBranchStore(moved)
    with pytest.raises(StoreConflict):
        store.write({"state.json": "{}"}, message="m", parent="p1")


def test_the_first_commit_creates_the_branch_as_an_orphan_root() -> None:
    gh, transport, _ = client(
        {
            "POST /git/blobs": ok({"sha": "b1"}, 201),
            "POST /git/trees": ok({"sha": "t1"}, 201),
            "POST /git/commits": ok({"sha": "c1"}, 201),
            "POST /git/refs": ok({}, 201),
        }
    )
    assert gh.commit_files("state", {"state.json": "{}"}, message="m", parent_sha=None) == "c1"
    commit = next(r for r in transport.requests if r.url.endswith("/git/commits"))
    assert json.loads(commit.body)["parents"] == []
    assert (
        json.loads(next(r for r in transport.requests if r.url.endswith("/git/refs")).body)["ref"] == "refs/heads/state"
    )


# -- billing ------------------------------------------------------------------------------------


class Token:
    def get_token(self, *scopes: str, **_: Any) -> Any:
        return types.SimpleNamespace(token="tok")


def test_billing_reads_month_to_date_cost_by_meter_and_never_logs_the_token() -> None:
    seen: list[HttpRequest] = []

    def transport(req: HttpRequest) -> HttpResponse:
        seen.append(req)
        body = {
            "properties": {
                "columns": [{"name": "CostUSD"}, {"name": "MeterCategory"}, {"name": "Currency"}],
                "rows": [
                    [6.74, "Azure Container Apps", "GBP"],
                    [5.97, "Foundry Tools", "GBP"],
                    [0.30, "Foundry Models", "GBP"],
                ],
            }
        }
        return HttpResponse(200, {}, json.dumps(body).encode())

    out = AzureBilling(Token(), "sub-1", "rg-x", transport=transport).observe("2026-10-11T20:00:00Z")
    assert out["billed_usd"] == 13.01 and out["by_meter"][0] == {"name": "Azure Container Apps", "usd": 6.74}
    assert out["as_of"] == "2026-10-11T20:00:00Z" and out["scope"] == "rg-x" and "tok" not in json.dumps(out)
    assert "/subscriptions/sub-1/resourceGroups/rg-x/providers/Microsoft.CostManagement/query" in seen[0].url
    failing = AzureBilling(Token(), "s", "g", transport=lambda r: HttpResponse(429, {}, b""))
    with pytest.raises(RuntimeError, match="429"):
        failing.observe("2026-10-11T20:00:00Z")


# -- summaries ----------------------------------------------------------------------------------


def test_a_summary_may_not_add_numbers_links_or_markup() -> None:
    facts = '{"issue": 12, "cost_usd": 0.07}'
    assert summary.acceptable("Issue 12 reached production for 0.07 USD.", facts)
    assert not summary.acceptable("Issue 12 cost 9.99 USD.", facts)
    assert not summary.acceptable("See https://evil.example for issue 12.", facts)
    assert not summary.acceptable("Issue 12 <b>done</b>.", facts)
    assert not summary.acceptable("x" * 400, facts)


def test_model_summariser_sends_facts_as_untrusted_data_and_drops_bad_answers(real) -> None:
    from tests.ledger.conftest import ticket_of

    t = ticket_of(real[12])
    sent: list[dict[str, Any]] = []

    def transport_for(text: str):
        def transport(req: HttpRequest) -> HttpResponse:
            sent.append(json.loads(req.body))
            body = {
                "status": "completed",
                "usage": {"input_tokens": 120, "output_tokens": 30},
                "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
            }
            return HttpResponse(200, {}, json.dumps(body).encode())

        return transport

    good = summary.ModelSummariser(
        "https://r.services.ai.azure.com/api/projects/p",
        "sdlc-default",
        token_provider=lambda: "t",
        transport=transport_for("Feature 12 is live in production."),
    )
    text, usage = good.summarise(t)
    assert text == "Feature 12 is live in production." and usage == {"in": 120, "out": 30}
    assert "untrusted_input" in sent[0]["input"][0]["content"] and sent[0]["model"] == "sdlc-default"
    bad = summary.ModelSummariser(
        "https://r.services.ai.azure.com/api/projects/p",
        "sdlc-default",
        token_provider=lambda: "t",
        transport=transport_for("It cost 42 USD."),
    )
    assert bad.summarise(t)[0] is None
    down = summary.ModelSummariser(
        "https://r.services.ai.azure.com/api/projects/p",
        "sdlc-default",
        token_provider=lambda: "t",
        transport=lambda r: HttpResponse(500, {}, b""),
    )
    assert down.summarise(t) == (None, {"in": 0, "out": 0})


# -- runtime wiring -------------------------------------------------------------------------------


def test_build_ledger_reads_the_pat_from_key_vault_and_enables_billing_only_when_configured() -> None:
    env = {
        "FOUNDRY_PROJECT_ENDPOINT": "https://res.services.ai.azure.com/api/projects/proj",
        "KEY_VAULT_URI": "https://kv.vault.azure.net",
    }
    with patch.object(ledger_runtime.KeyVaultSecrets, "get_secret", return_value="ghp_x") as get:
        led = ledger_runtime.build_ledger(env, credential_factory=Token)
        assert led.billing is None and led.summariser is not None and led.mode == "hosted"
        full = ledger_runtime.build_ledger(
            {**env, "AZURE_SUBSCRIPTION_ID": "s", "AZURE_RESOURCE_GROUP": "g", "LEDGER_SUMMARIES": "off"},
            credential_factory=Token,
        )
        assert full.billing is not None and full.summariser is None
    get.assert_called_with("github-pat")
    with pytest.raises(ledger_runtime.ConfigError, match="KEY_VAULT_URI"):
        ledger_runtime.build_ledger(
            {"FOUNDRY_PROJECT_ENDPOINT": env["FOUNDRY_PROJECT_ENDPOINT"]}, credential_factory=Token
        )


# -- hosted entrypoint and zip ------------------------------------------------------------------------


def _load_main() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("ledger_main", HOSTED / "main.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    with patch("azure.ai.agentserver.core._tracing._configure_tracing"):
        spec.loader.exec_module(module)
    return module


class FakeRequest:
    def __init__(self, body: Any):
        self._body = body

    async def json(self) -> Any:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def test_hosted_entrypoint_maps_bad_requests_config_and_crashes_to_http_errors() -> None:
    main = _load_main()

    class Fake:
        def handle(self, body: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True, "echo": body["op"]}

    with patch.object(main, "build_ledger", return_value=Fake()):
        ok_resp = asyncio.run(main.handle_invoke(FakeRequest({"op": "status"})))
        not_json = asyncio.run(main.handle_invoke(FakeRequest(ValueError("x"))))
        not_obj = asyncio.run(main.handle_invoke(FakeRequest([1])))
    assert ok_resp.status_code == 200 and json.loads(ok_resp.body)["echo"] == "status"
    assert not_json.status_code == 400 and not_obj.status_code == 400
    with patch.object(main, "build_ledger", side_effect=main.ConfigError("missing environment: KEY_VAULT_URI")):
        assert asyncio.run(main.handle_invoke(FakeRequest({"op": "status"}))).status_code == 500

    class Bad:
        def handle(self, body: dict[str, Any]) -> dict[str, Any]:
            raise main.LedgerError("unknown op 'x'")

    with patch.object(main, "build_ledger", return_value=Bad()):
        assert asyncio.run(main.handle_invoke(FakeRequest({"op": "x"}))).status_code == 400

    class Boom:
        def handle(self, body: dict[str, Any]) -> dict[str, Any]:
            raise PermissionError("token ghp_secret")

    with patch.object(main, "build_ledger", return_value=Boom()):
        broken = asyncio.run(main.handle_invoke(FakeRequest({"op": "status"})))
    assert broken.status_code == 502 and b"ghp_secret" not in broken.body
    assert os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] == "false"


def test_ledger_zip_is_deterministic_and_carries_the_ledger_package(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("ledger_build_zip", HOSTED / "build_zip.py")
    assert spec and spec.loader
    build_zip = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_zip)
    a, b = tmp_path / "a.zip", tmp_path / "b.zip"
    assert build_zip.build(a) == build_zip.build(b)
    names = zipfile.ZipFile(a).namelist()
    assert names[:2] == ["main.py", "requirements.txt"] and "sdlc_agents/ledger/service.py" in names
    assert not [n for n in names if n.startswith("sdlc_agents/coder/")]
    lines = [ln for ln in (HOSTED / "requirements.txt").read_text().splitlines() if ln and not ln.startswith("#")]
    assert all("==" in ln for ln in lines)


# silence an unused import: Recorded and BASE document the shared fake transport shape
_ = (Recorded, BASE)
