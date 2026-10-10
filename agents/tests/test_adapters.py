"""Foundry, Key Vault, agent registration, runtime wiring, hosted entrypoint and zip builder."""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import os
import sys
import types
import urllib.error
import zipfile
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import openai
import pytest
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from fakes import FakeFoundry

from sdlc_agents import create_agents, runtime, transport
from sdlc_agents.definitions import AGENTS, MCP_READ_ONLY_TOOLS
from sdlc_agents.foundry import (
    AgentOutputError,
    AgentRunError,
    FoundryClient,
    RetryPolicy,
    Section,
    build_input,
    call_with_retry,
    run_agent,
)
from sdlc_agents.keyvault import KeyVaultSecrets, SecretError
from sdlc_agents.transport import HttpRequest, HttpResponse

ENDPOINT = "https://res.services.ai.azure.com/api/projects/proj"
HOSTED = Path(__file__).resolve().parent.parent / "hosted" / "orchestrator"


class Token:
    def __init__(self) -> None:
        self.scopes: list[str] = []

    def get_token(self, *scopes: str, **_: Any) -> Any:
        self.scopes.extend(scopes)
        return types.SimpleNamespace(token="entra-token")


class Transport:
    def __init__(self, *responses: HttpResponse):
        self.responses = list(responses)
        self.requests: list[HttpRequest] = []

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        return self.responses.pop(0)


def response(status: str = "completed", text: str = '{"a": 1}', in_tok: int = 10, out_tok: int = 20) -> Any:
    return types.SimpleNamespace(
        id="resp-1", status=status, output_text=text,
        usage=types.SimpleNamespace(input_tokens=in_tok, output_tokens=out_tok),
        incomplete_details=types.SimpleNamespace(reason="max_output_tokens") if status != "completed" else None,
    )


def project_returning(result: Any) -> MagicMock:
    oc = MagicMock()
    if isinstance(result, Exception):
        oc.responses.create.side_effect = result
    else:
        oc.responses.create.return_value = result
    oc.__enter__ = lambda s: s
    oc.__exit__ = MagicMock(return_value=False)
    project = MagicMock()
    project.get_openai_client.return_value = oc
    return project


# ---------------------------------------------------------------------------
# FoundryClient
# ---------------------------------------------------------------------------

def test_prompt_agent_call_uses_an_agent_reference_by_name_and_returns_usage() -> None:
    project = project_returning(response())
    os.environ["AZURE_AI_PROJECTS_CONSOLE_LOGGING"] = "true"
    client = FoundryClient(ENDPOINT, Token(), project_factory=lambda e, c: project)
    result = client.call_prompt_agent("sdlc-triage", "input", max_output_tokens=99_999)
    assert (result.text, result.input_tokens, result.output_tokens) == ('{"a": 1}', 10, 20)
    assert "AZURE_AI_PROJECTS_CONSOLE_LOGGING" not in os.environ
    kwargs = project.get_openai_client.return_value.responses.create.call_args.kwargs
    assert kwargs["extra_body"] == {"agent_reference": {"type": "agent_reference", "name": "sdlc-triage"}}
    assert kwargs["max_output_tokens"] == 32_000 and kwargs["input"] == "input"
    project.get_openai_client.assert_called_with(max_retries=0, timeout=120.0)


@pytest.mark.parametrize("result, message", [
    (response(status="incomplete"), "not completed: max_output_tokens"),
    (response(text="  "), "empty text"),
])
def test_incomplete_or_empty_responses_raise(result: Any, message: str) -> None:
    client = FoundryClient(ENDPOINT, Token(), project_factory=lambda e, c: project_returning(result))
    with pytest.raises(AgentRunError, match=message):
        client.call_prompt_agent("sdlc-triage", "x")


def test_http_and_connection_errors_become_agent_run_errors() -> None:
    request = MagicMock()
    status_error = openai.APIStatusError("throttled", response=MagicMock(status_code=429, request=request), body=None)
    client = FoundryClient(ENDPOINT, Token(), project_factory=lambda e, c: project_returning(status_error))
    with pytest.raises(AgentRunError, match="HTTP 429"):
        client.call_prompt_agent("sdlc-triage", "x")
    conn = openai.APIConnectionError(request=request)
    client = FoundryClient(ENDPOINT, Token(), project_factory=lambda e, c: project_returning(conn))
    with pytest.raises(AgentRunError, match="request failed: APIConnectionError"):
        client.call_prompt_agent("sdlc-triage", "x")


def test_endpoint_must_be_a_foundry_project() -> None:
    with pytest.raises(ValueError, match="not a Foundry project endpoint"):
        FoundryClient("http://res/api/projects/p", Token())
    with pytest.raises(ValueError, match="not a Foundry project endpoint"):
        FoundryClient("https://res.example.com/other", Token())


def test_default_project_factory_builds_an_sdk_client() -> None:
    client = FoundryClient(ENDPOINT, Token())
    from azure.ai.projects import AIProjectClient

    assert isinstance(client._client(), AIProjectClient)


def test_invoke_hosted_posts_to_the_invocations_endpoint_and_returns_the_platform_session() -> None:
    token = Token()
    t = Transport(HttpResponse(200, {"x-agent-session-id": "sess-9"}, b'{"job_id":"j","status":"running"}'),
                  HttpResponse(200, {}, b'{"status":"running"}'))
    client = FoundryClient(ENDPOINT, token, transport=t)
    body, session = client.invoke_hosted("sdlc-coder", {"op": "start"})
    assert body == {"job_id": "j", "status": "running"} and session == "sess-9"
    first = t.requests[0]
    assert first.url == f"{ENDPOINT}/agents/sdlc-coder/endpoint/protocols/invocations?api-version=v1"
    assert first.headers["Authorization"] == "Bearer entra-token" and token.scopes == ["https://ai.azure.com/.default"]
    assert json.loads(first.body) == {"op": "start"}
    _, again = client.invoke_hosted("sdlc-coder", {"op": "status"}, session_id="sess-9", timeout_s=30)
    assert t.requests[1].url.endswith("api-version=v1&agent_session_id=sess-9") and again == "sess-9"
    assert t.requests[1].timeout_s == 30.0


def test_invoke_hosted_reads_an_event_stream_and_its_done_event_session() -> None:
    stream = (b'data: {"type": "token", "content": "x"}\n\n'
              b'data: {"type": "done", "status": "running", "session_id": "sess-sse"}\n\n')
    t = Transport(HttpResponse(200, {"content-type": "text/event-stream"}, stream),
                  HttpResponse(200, {"content-type": "text/event-stream", "x-agent-session-id": "hdr"}, stream))
    client = FoundryClient(ENDPOINT, Token(), transport=t)
    body, session = client.invoke_hosted("sdlc-coder", {"op": "status"})
    assert body["status"] == "running" and session == "sess-sse"
    assert client.invoke_hosted("sdlc-coder", {"op": "status"})[1] == "hdr"   # the header wins


@pytest.mark.parametrize("resp, message", [
    (HttpResponse(404, {}, b"no agent"), "HTTP 404"),
    (HttpResponse(200, {}, b"not json"), "not JSON"),
    (HttpResponse(200, {"content-type": "text/event-stream"}, b": keepalive\n\n"), "not JSON"),
    (HttpResponse(200, {}, b"[1]"), "expected an object"),
])
def test_invoke_hosted_errors(resp: HttpResponse, message: str) -> None:
    client = FoundryClient(ENDPOINT, Token(), transport=Transport(resp))
    with pytest.raises(AgentRunError, match=message):
        client.invoke_hosted("sdlc-coder", {})


# ---------------------------------------------------------------------------
# run_agent
# ---------------------------------------------------------------------------

def test_build_input_wraps_untrusted_sections_with_one_nonce_and_leaves_trusted_ones_plain() -> None:
    text = build_input([Section("mode", "bugfix", trusted=True), Section("issue", "body"),
                        Section("log", "L" * 70_000 + "END", keep_tail=True)], "abc")
    assert "## mode\nbugfix" in text and "<untrusted_input nonce=abc name=issue>\nbody\n" in text
    assert "LOG TRUNCATED nonce=abc" in text and "END\n</untrusted_input nonce=abc>" in text


def test_run_agent_validates_json_and_sanitises_markdown() -> None:
    foundry = FakeFoundry()
    foundry.script("sdlc-triage", {"severity": "s1", "owner": "web", "summary": "s", "suspected_area": "a",
                                   "rationale": "r"})
    out = run_agent(foundry, "sdlc-triage", [Section("issue", "x")])
    assert out.data["severity"] == "s1" and (out.input_tokens, out.output_tokens) == (1000, 400)
    foundry.script("sdlc-release-notes", "notes for @team <script>x</script>")
    notes = run_agent(foundry, "sdlc-release-notes", [Section("pr", "x")])
    assert notes.data is None and notes.text == "notes for `@team` x"
    assert foundry.calls[-1][1].count("nonce=") == 2


@pytest.mark.parametrize("text", ['{"severity": "s1", "severity": "s2"}', "not json", '{"severity": "s9"}'])
def test_run_agent_rejects_bad_json_after_one_repair_and_bills_both_answers(text: str) -> None:
    foundry = FakeFoundry()
    foundry.script("sdlc-triage", text, text)
    billed: list[tuple[str, int, int]] = []
    with pytest.raises(AgentOutputError, match="after a repair retry"):
        run_agent(foundry, "sdlc-triage", [Section("issue", "x")], bill=lambda *a: billed.append(a))
    assert billed == [("sdlc-triage", 1000, 400)] * 2
    assert "## repair\nYour previous answer was rejected" in foundry.calls[1][1]


# ---------------------------------------------------------------------------
# Key Vault
# ---------------------------------------------------------------------------

def test_key_vault_reads_and_caches_a_secret_without_exposing_it() -> None:
    token = Token()
    t = Transport(HttpResponse(200, {}, b'{"value": "s3cret"}'))
    vault = KeyVaultSecrets("https://kv-demo.vault.azure.net/", token, transport=t)
    assert vault.get_secret("github-pat") == "s3cret" and vault.get_secret("github-pat") == "s3cret"
    assert len(t.requests) == 1 and token.scopes == ["https://vault.azure.net/.default"]
    assert t.requests[0].url == "https://kv-demo.vault.azure.net/secrets/github-pat?api-version=7.4"
    assert "s3cret" not in repr(vault)


@pytest.mark.parametrize("url", ["http://kv.vault.azure.net", "https://evil.example.com", "kv.vault.azure.net"])
def test_key_vault_url_must_be_a_vault(url: str) -> None:
    with pytest.raises(ValueError, match="not a Key Vault URL"):
        KeyVaultSecrets(url, Token())


def test_key_vault_errors_name_the_secret_not_its_value() -> None:
    vault = KeyVaultSecrets("https://kv.vault.azure.net", Token(),
                            transport=Transport(HttpResponse(403, {}, b"{}"), HttpResponse(200, {}, b'{"value": ""}')))
    with pytest.raises(ValueError, match="invalid secret name"):
        vault.get_secret("../x")
    with pytest.raises(SecretError, match="403 for secret github-pat"):
        vault.get_secret("github-pat")
    with pytest.raises(SecretError, match="empty"):
        vault.get_secret("github-pat")


# ---------------------------------------------------------------------------
# urllib transport
# ---------------------------------------------------------------------------

def test_urllib_transport_refuses_plain_http() -> None:
    with pytest.raises(ValueError, match="non-https"):
        transport.urllib_transport(HttpRequest("GET", "http://example.com"))


def test_urllib_transport_returns_http_errors_and_redirects_as_responses() -> None:
    class Resp(io.BytesIO):
        status = 200
        headers: ClassVar[dict[str, str]] = {"X-A": "1"}

        def __enter__(self) -> Resp:
            return self

        def __exit__(self, *a: object) -> None:
            return None

    with patch.object(transport._OPENER, "open", return_value=Resp(b"ok")):
        ok = transport.urllib_transport(HttpRequest("GET", "https://example.com"))
    assert (ok.status, ok.headers, ok.text()) == (200, {"x-a": "1"}, "ok")
    redirect = urllib.error.HTTPError("https://example.com", 302, "Found", {"Location": "https://b"}, io.BytesIO(b""))
    with patch.object(transport._OPENER, "open", side_effect=redirect):
        resp = transport.urllib_transport(HttpRequest("GET", "https://example.com"))
    assert resp.status == 302 and resp.headers["location"] == "https://b"
    assert transport._NoRedirect().redirect_request(None, None, 302, "", {}, "https://b") is None


# ---------------------------------------------------------------------------
# create_agents
# ---------------------------------------------------------------------------

def test_definitions_attach_the_read_only_github_mcp_tool_only_where_needed() -> None:
    for agent in AGENTS:
        definition = create_agents.build_definition(agent).as_dict()
        tools = definition.get("tools") or []
        if agent.uses_mcp:
            assert tools == [{
                "type": "mcp", "server_label": "github", "server_url": "https://api.githubcopilot.com/mcp/",
                "project_connection_id": "github-mcp", "require_approval": "never",
                "allowed_tools": list(MCP_READ_ONLY_TOOLS),
            }]
        else:
            assert tools == []
        assert definition["model"] == "sdlc-default" and definition["reasoning"] == {"effort": "low"}
        assert ("text" in definition) == (agent.schema is not None)


def _registry(existing: dict[str, str | None]) -> MagicMock:
    client = MagicMock()

    def get(name: str) -> Any:
        if name not in existing:
            raise ResourceNotFoundError(message="nope")
        latest = types.SimpleNamespace(version="3", metadata={"definition_sha256": existing[name]})
        return types.SimpleNamespace(versions=types.SimpleNamespace(latest=latest))

    client.get.side_effect = get
    client.create_version.return_value = types.SimpleNamespace(version="4")
    return client


def test_registration_is_idempotent_by_definition_hash() -> None:
    agent = AGENTS[0]
    definition = create_agents.build_definition(agent)
    digest = create_agents.definition_hash(definition)
    project = types.SimpleNamespace(agents=_registry({agent.name: digest}))
    assert create_agents.ensure_version(project, agent.name, definition) == ("3", "unchanged")
    project = types.SimpleNamespace(agents=_registry({agent.name: "old"}))
    assert create_agents.ensure_version(project, agent.name, definition) == ("4", "created")
    assert project.agents.create_version.call_args.kwargs["metadata"] == {"definition_sha256": digest}
    project = types.SimpleNamespace(agents=_registry({}))
    assert create_agents.ensure_version(project, agent.name, definition) == ("4", "created")


def _run_main(agents_client: MagicMock, env: dict[str, str]) -> None:
    project = MagicMock()
    project.agents = agents_client
    project.__enter__ = lambda s: s
    project.__exit__ = MagicMock(return_value=False)
    with (patch.dict(os.environ, env, clear=False),
          patch("sdlc_agents.create_agents.AIProjectClient", return_value=project),
          patch("sdlc_agents.create_agents.DefaultAzureCredential")):
        create_agents.main()


def test_main_registers_every_agent_and_reports_azure_errors(capsys: pytest.CaptureFixture[str]) -> None:
    client = _registry({})
    _run_main(client, {"FOUNDRY_PROJECT_ENDPOINT": ENDPOINT})
    assert client.create_version.call_count == len(AGENTS)
    assert capsys.readouterr().out.count("created") == len(AGENTS)

    failing = _registry({})
    failing.create_version.side_effect = [HttpResponseError(message="boom"), *[types.SimpleNamespace(version="1")] * 7]
    with pytest.raises(SystemExit) as exc:
        _run_main(failing, {"FOUNDRY_PROJECT_ENDPOINT": ENDPOINT})
    assert exc.value.code == 1 and "ERROR registering sdlc-req-gate" in capsys.readouterr().err


def test_main_needs_the_endpoint(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        _run_main(_registry({}), {"FOUNDRY_PROJECT_ENDPOINT": ""})
    assert "FOUNDRY_PROJECT_ENDPOINT" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# runtime and hosted entrypoint
# ---------------------------------------------------------------------------

def test_run_once_needs_its_environment() -> None:
    with pytest.raises(runtime.ConfigError, match="FOUNDRY_PROJECT_ENDPOINT, KEY_VAULT_URI"):
        runtime.run_once({})
    with pytest.raises(runtime.ConfigError, match="integer"):
        runtime.run_once({"FOUNDRY_PROJECT_ENDPOINT": ENDPOINT, "KEY_VAULT_URI": "https://kv.vault.azure.net",
                          "TICK_BUDGET_S": "soon"})


def test_run_once_wires_key_vault_github_and_foundry_into_a_tick() -> None:
    seen: dict[str, Any] = {}

    def fake_tick(github: Any, foundry: Any, secrets: Any, clock: Any, budget_wall_s: int) -> Any:
        seen.update(github=github, foundry=foundry, budget=budget_wall_s)
        return types.SimpleNamespace(to_dict=lambda: {"lock": "acquired"})

    with (patch.object(runtime, "run_tick", fake_tick),
          patch.object(runtime.KeyVaultSecrets, "get_secret", return_value="ghp_x") as get_secret):
        report = runtime.run_once({"FOUNDRY_PROJECT_ENDPOINT": ENDPOINT, "KEY_VAULT_URI": "https://kv.vault.azure.net",
                                   "TICK_BUDGET_S": "120"}, credential_factory=Token)
    assert report == {"lock": "acquired"} and seen["budget"] == 120
    get_secret.assert_called_once_with("github-pat")
    assert repr(seen["github"]) == "GitHubClient(stevengonsalvez/foundry-autonomous-sdlc)"
    assert runtime._default_credential() is not None


def _load_main() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("orchestrator_main", HOSTED / "main.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Exporters probe the Azure metadata endpoint and write to the console; tests need neither.
    with patch("azure.ai.agentserver.core._tracing._configure_tracing"):
        spec.loader.exec_module(module)
    return module


def test_hosted_entrypoint_runs_one_tick_per_invocation_and_maps_errors() -> None:
    main = _load_main()
    request = types.SimpleNamespace(state=types.SimpleNamespace(session_id="s1"))
    with patch.object(main, "run_once", return_value={"lock": "acquired", "objects": []}):
        ok = asyncio.run(main.handle_invoke(request))
    assert ok.status_code == 200 and json.loads(ok.body) == {"lock": "acquired", "objects": []}
    with patch.object(main, "run_once", side_effect=runtime.ConfigError("missing environment: KEY_VAULT_URI")):
        bad = asyncio.run(main.handle_invoke(request))
    assert bad.status_code == 500 and json.loads(bad.body)["error"] == "config"
    with patch.object(main, "run_once", side_effect=PermissionError("token ghp_secret")):
        broken = asyncio.run(main.handle_invoke(request))
    assert broken.status_code == 502 and b"ghp_secret" not in broken.body
    assert main.app.__class__.__name__ == "InvocationAgentServerHost"
    assert os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] == "false"


def test_requirements_pin_every_dependency() -> None:
    lines = [ln for ln in (HOSTED / "requirements.txt").read_text().splitlines() if ln and not ln.startswith("#")]
    assert all("==" in ln for ln in lines)
    pins = dict(ln.split("==") for ln in lines)
    assert pins["azure-ai-agentserver-invocations"] == "1.1.0" and pins["azure-ai-agentserver-core"] == "2.1.0"


def test_zip_is_deterministic_and_vendors_the_package_at_the_root(tmp_path: Path) -> None:
    sys.path.insert(0, str(HOSTED))
    try:
        import build_zip
    finally:
        sys.path.remove(str(HOSTED))
    first, second = tmp_path / "a.zip", tmp_path / "b.zip"
    assert build_zip.build(first) == build_zip.build(second)
    names = zipfile.ZipFile(first).namelist()
    assert names[:2] == ["main.py", "requirements.txt"]
    assert "sdlc_agents/tick.py" in names and "sdlc_agents/ports.py" in names
    assert not [n for n in names if "__pycache__" in n or n.startswith("sdlc_agents/coder/")]
    assert build_zip.main(["--out", str(tmp_path / "c.zip")]) == 0


# ---------------------------------------------------------------------------
# Transient classification and retry
# ---------------------------------------------------------------------------

def _status_error(status: int, headers: dict[str, str] | None = None, body: Any = None) -> Exception:
    response = MagicMock(status_code=status, request=MagicMock(), headers=headers or {})
    return openai.APIStatusError("boom", response=response, body=body)


@pytest.mark.parametrize("error, transient, retry_after", [
    (_status_error(429, {"retry-after": "7"}), True, 7.0),
    (_status_error(408), True, None),
    (_status_error(503, {"retry-after": "soon"}), True, None),
    (_status_error(400, body={"code": "rate_limit_exceeded"}), True, None),
    (_status_error(400, body={"code": "invalid_prompt"}), False, None),
    (openai.APIConnectionError(request=MagicMock()), True, None),
])
def test_prompt_call_errors_are_classified(error: Exception, transient: bool, retry_after: float | None) -> None:
    client = FoundryClient(ENDPOINT, Token(), project_factory=lambda e, c: project_returning(error))
    with pytest.raises(AgentRunError) as exc:
        client.call_prompt_agent("sdlc-triage", "x")
    assert (exc.value.transient, exc.value.retry_after) == (transient, retry_after)


def test_failed_response_with_a_rate_limit_code_is_transient_and_a_refusal_is_not() -> None:
    failed = response(status="failed")
    failed.error = types.SimpleNamespace(code="rate_limit_exceeded")
    client = FoundryClient(ENDPOINT, Token(), project_factory=lambda e, c: project_returning(failed))
    with pytest.raises(AgentRunError) as exc:
        client.call_prompt_agent("sdlc-triage", "x")
    assert exc.value.transient
    refused = response(status="incomplete")
    refused.incomplete_details = types.SimpleNamespace(reason="content_filter")
    client = FoundryClient(ENDPOINT, Token(), project_factory=lambda e, c: project_returning(refused))
    with pytest.raises(AgentRunError, match="content_filter") as exc:
        client.call_prompt_agent("sdlc-triage", "x")
    assert not exc.value.transient and exc.value.output_tokens == 20


def test_invoke_hosted_marks_throttling_outages_and_dropped_connections_transient() -> None:
    client = FoundryClient(ENDPOINT, Token(), transport=Transport(HttpResponse(429, {"retry-after": "3"}, b"")))
    with pytest.raises(AgentRunError) as exc:
        client.invoke_hosted("sdlc-coder", {})
    assert exc.value.transient and exc.value.retry_after == 3.0

    def drop(_request: HttpRequest) -> HttpResponse:
        raise urllib.error.URLError("connection reset")

    with pytest.raises(AgentRunError) as exc:
        FoundryClient(ENDPOINT, Token(), transport=drop).invoke_hosted("sdlc-coder", {})
    assert exc.value.transient
    with pytest.raises(AgentRunError) as exc:
        FoundryClient(ENDPOINT, Token(), transport=Transport(HttpResponse(404, {}, b""))).invoke_hosted("x", {})
    assert not exc.value.transient


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.waits: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.now += seconds


def _policy(clock: _Clock, deadline: float = 1000.0, jitter: float = 0.0) -> RetryPolicy:
    return RetryPolicy(sleep=clock.sleep, monotonic=lambda: clock.now, deadline=deadline, jitter=lambda: jitter)


def test_call_with_retry_backs_off_exponentially_and_gives_up_after_max_attempts() -> None:
    clock = _Clock()
    calls: list[int] = []

    def always_throttled() -> None:
        calls.append(1)
        raise AgentRunError("429", transient=True)

    with pytest.raises(AgentRunError):
        call_with_retry(always_throttled, _policy(clock))
    assert len(calls) == 4 and clock.waits == [1.0, 2.0, 4.0]      # base 2 s x 2^n, jitter at its low end


def test_call_with_retry_stops_before_the_deadline_and_never_retries_real_failures() -> None:
    clock = _Clock()
    with pytest.raises(AgentRunError):
        call_with_retry(lambda: (_ for _ in ()).throw(AgentRunError("429", transient=True, retry_after=50)),
                        _policy(clock, deadline=40))
    assert clock.waits == []
    attempts: list[int] = []

    def refused() -> None:
        attempts.append(1)
        raise AgentRunError("content_filter")

    with pytest.raises(AgentRunError):
        call_with_retry(refused, _policy(clock))
    assert attempts == [1]
    assert call_with_retry(lambda: "ok", None) == "ok"
    assert RetryPolicy(sleep=clock.sleep, monotonic=lambda: 0, deadline=1, jitter=lambda: 1.0).delay(9, None) == 30.0
