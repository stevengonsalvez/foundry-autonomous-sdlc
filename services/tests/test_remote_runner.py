"""
CliFoundry in remote mode: prompt-agent calls go to the coder service's POST /agent-run and the reply is
classified locally, exactly like a local agy process. The foreman never holds the agy token and never
spawns agy when a sandbox URL is configured.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from sdlc_agents.foundry import AgentRunError
from sdlc_agents.transport import HttpRequest, HttpResponse

from sdlc_factory.cli_foundry import AuthError, CliFoundry, QuotaError, RemoteRunner
from sdlc_factory.coder_service import FakeAgentRunner, FakeCoder, serve
from sdlc_factory.config import load_factory
from sdlc_factory.engines import ProcessOutput

REPO = Path(__file__).resolve().parents[2]
FACTORY_YAML = REPO / "factory" / "factory.yaml"
FACTORY = load_factory(FACTORY_YAML)
TOKEN = "svc-token"
TRIAGE = {"severity": "s2", "owner": "api", "summary": "label lookup 500s",
          "suspected_area": "app/api", "rationale": "stack trace points at the api"}


def result_stdout(response: str, *, tokens: int = 5) -> str:
    usage = {"input_tokens": tokens, "output_tokens": tokens, "thinking_tokens": 0, "total_tokens": 2 * tokens}
    return json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": response,
                                                     "usage": usage, "denied_actions": []}}) + "\n"


class FakeTransport:
    def __init__(self, *responses: HttpResponse | Exception):
        self.responses = list(responses)
        self.requests: list[HttpRequest] = []

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def run_reply(stdout: str, *, returncode: int = 0, stderr: str = "", status: int = 200) -> HttpResponse:
    body = {"returncode": returncode, "stdout": stdout, "stderr": stderr, "timed_out": returncode == 124,
            "duration_s": 0.5}
    return HttpResponse(status, {"content-type": "application/json"}, json.dumps(body).encode())


def error_reply(status: int, error: str, headers: dict[str, str] | None = None) -> HttpResponse:
    return HttpResponse(status, {"content-type": "application/json", **(headers or {})},
                        json.dumps({"error": error}).encode())


def no_local_agy(*_a: Any, **_kw: Any) -> ProcessOutput:
    raise AssertionError("a local agy was spawned in remote mode")


def remote(transport: FakeTransport, **kw: Any) -> CliFoundry:
    return CliFoundry(FACTORY, remote=RemoteRunner("http://coder:8090/", token=TOKEN, transport=transport),
                      runner=no_local_agy, **kw)


# -- the wire ---------------------------------------------------------------------------------------------


def test_remote_runner_posts_only_prompt_schema_and_timeout_with_the_token() -> None:
    transport = FakeTransport(run_reply("out", stderr="err"))
    out = RemoteRunner("http://coder:8090/", token=TOKEN, transport=transport)("PROMPT", schema={"type": "object"},
                                                                               timeout_s=299.2)
    assert out == ProcessOutput(0, "out", "err")
    (request,) = transport.requests
    assert (request.method, request.url) == ("POST", "http://coder:8090/agent-run")
    assert request.headers["x-factory-token"] == TOKEN
    assert json.loads(request.body) == {"prompt": "PROMPT", "schema": {"type": "object"}, "timeout_s": 300}
    assert request.timeout_s > 300 + 30     # past the server's own hard kill


def test_remote_runner_refuses_a_non_http_url() -> None:
    with pytest.raises(ValueError, match="http"):
        RemoteRunner("file:///run/secrets", token=TOKEN)


@pytest.mark.parametrize(("response", "transient"), [
    (error_reply(429, "busy", {"retry-after": "30"}), True),
    (HttpResponse(429, {}, b'{"error": "busy", "retry_after_s": 30}'), True),
    (error_reply(502, "bad_gateway"), True),
    (error_reply(500, "internal_error"), True),
    (error_reply(500, "sandbox_unavailable"), False),
    (error_reply(500, "token_unavailable"), False),
    (error_reply(401, "unauthorized"), False),
    (error_reply(400, "invalid_request"), False),
    (HttpResponse(200, {}, b"not json"), False),
    (HttpResponse(200, {}, b'{"returncode": "0", "stdout": "", "stderr": ""}'), False),
    (ConnectionResetError("reset"), True),
], ids=["busy", "busy-body", "502", "500", "no-sandbox", "no-token", "401", "400", "not-json", "bad-shape", "reset"])
def test_remote_failures_are_agent_run_errors_classified_for_tick(response: Any, transient: bool) -> None:
    foundry = remote(FakeTransport(response))
    with pytest.raises(AgentRunError) as info:
        foundry.call_prompt_agent("sdlc-release-notes", "x")
    assert info.value.transient is transient
    assert foundry.usage_summary()["calls"] == 1
    if isinstance(response, HttpResponse) and response.status == 429:   # from the header or the body
        assert info.value.retry_after == 30.0


# -- classification stays local ---------------------------------------------------------------------------


def test_a_schema_agent_round_trips_and_is_classified_locally() -> None:
    transport = FakeTransport(run_reply(result_stdout(json.dumps(TRIAGE), tokens=7)))
    result = remote(transport).call_prompt_agent("sdlc-triage", "INPUT")
    assert json.loads(result.text) == TRIAGE
    assert (result.input_tokens, result.output_tokens) == (7, 7)
    body = json.loads(transport.requests[0].body)
    agent = FACTORY.agent("sdlc-triage")
    assert body["prompt"] == f"{agent.instructions}\n\nINPUT"
    assert body["schema"] == agent.schema
    assert body["timeout_s"] == agent.timeout_s


def test_the_internal_repair_also_goes_remote() -> None:
    transport = FakeTransport(run_reply(result_stdout("no json here")), run_reply(result_stdout(json.dumps(TRIAGE))))
    foundry = remote(transport)
    assert json.loads(foundry.call_prompt_agent("sdlc-triage", "x").text) == TRIAGE
    assert len(transport.requests) == 2
    assert "rejected" in json.loads(transport.requests[1].body)["prompt"]
    assert foundry.usage_summary()["calls"] == 2


def test_quota_and_auth_from_the_remote_process_map_like_local_ones() -> None:
    quota = ('AGY_ERROR: {"short_error":"RESOURCE_EXHAUSTED (code 429)","status":"RESOURCE_EXHAUSTED",'
             '"error_code":429}\n')
    foundry = remote(FakeTransport(run_reply("", returncode=3, stderr=quota)))
    with pytest.raises(QuotaError):
        foundry.call_prompt_agent("sdlc-release-notes", "x")
    assert foundry.quota_hit
    with pytest.raises(AuthError):
        remote(FakeTransport(run_reply("", returncode=125, stderr="Authentication required. Visit https://x\n"))
               ).call_prompt_agent("sdlc-release-notes", "x")


def test_a_remote_timeout_is_transient() -> None:
    with pytest.raises(AgentRunError) as info:
        remote(FakeTransport(run_reply("", returncode=124, stderr="[agy] print timeout after 5s\n"))
               ).call_prompt_agent("sdlc-release-notes", "x")
    assert info.value.transient


def test_without_a_token_path_or_a_remote_the_foundry_refuses_to_build() -> None:
    with pytest.raises(ValueError, match="token"):
        CliFoundry(FACTORY)


# -- against the real coder service ------------------------------------------------------------------------


@contextmanager
def coder_with_fake_agents() -> Iterator[str]:
    server = serve(FakeCoder(), host="127.0.0.1", port=0, token=TOKEN, agent_runner=FakeAgentRunner())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_round_trip_through_the_coder_service_in_fake_mode() -> None:
    with coder_with_fake_agents() as url:
        foundry = CliFoundry(FACTORY, remote=RemoteRunner(url, token=TOKEN), runner=no_local_agy)
        assert foundry.call_prompt_agent("sdlc-release-notes", "x").text == FakeAgentRunner.TEXT
        bad = CliFoundry(FACTORY, remote=RemoteRunner(url, token="wrong"), runner=no_local_agy)
        with pytest.raises(AgentRunError) as info:
            bad.call_prompt_agent("sdlc-release-notes", "x")
    assert info.value.http_status == 401 and not info.value.transient


# -- from_env ------------------------------------------------------------------------------------------------


def clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AGENT_SANDBOX_URL", "CODER_URL", "CODER_SERVICE_TOKEN", "AGY_TOKEN_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FACTORY_CONFIG", str(FACTORY_YAML))


@pytest.mark.parametrize("var", ["AGENT_SANDBOX_URL", "CODER_URL"])
def test_from_env_with_a_sandbox_url_never_reads_the_token_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                                 var: str) -> None:
    clear_env(monkeypatch)
    monkeypatch.setenv(var, "http://coder:8090")
    monkeypatch.setenv("CODER_SERVICE_TOKEN", TOKEN)
    monkeypatch.setenv("AGY_TOKEN_FILE", str(tmp_path / "does-not-exist"))   # reading it would fail the call
    transport = FakeTransport(run_reply(result_stdout("notes")))
    foundry = CliFoundry.from_env(transport=transport, runner=no_local_agy)
    assert foundry.call_prompt_agent("sdlc-release-notes", "x").text == "notes"
    assert transport.requests[0].url == "http://coder:8090/agent-run"
    assert transport.requests[0].headers["x-factory-token"] == TOKEN


def test_from_env_prefers_the_sandbox_url_and_keeps_the_coder_url_for_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_env(monkeypatch)
    monkeypatch.setenv("AGENT_SANDBOX_URL", "http://sandbox:9000")
    monkeypatch.setenv("CODER_URL", "http://coder:8090")
    monkeypatch.setenv("CODER_SERVICE_TOKEN", TOKEN)
    transport = FakeTransport(run_reply(result_stdout("notes")),
                              HttpResponse(200, {"x-agent-session-id": "s"}, b'{"status": "running"}'))
    foundry = CliFoundry.from_env(transport=transport, runner=no_local_agy)
    foundry.call_prompt_agent("sdlc-release-notes", "x")
    foundry.invoke_hosted("sdlc-coder", {"op": "status"})
    assert [r.url for r in transport.requests] == ["http://sandbox:9000/agent-run", "http://coder:8090/invoke"]


def test_from_env_without_a_url_is_local_mode_and_needs_the_token_file(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_env(monkeypatch)
    with pytest.raises(ValueError, match="AGY_TOKEN_FILE"):
        CliFoundry.from_env()
