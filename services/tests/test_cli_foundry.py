from __future__ import annotations

import json
import threading
import urllib.parse
from pathlib import Path
from typing import Any

import pytest
from sdlc_agents.coder.toolchain import AGY_AUTH_FILE
from sdlc_agents.foundry import AgentRunError, RetryPolicy, Section, call_with_retry, run_agent
from sdlc_agents.ports import AgentResult
from sdlc_agents.transport import HttpRequest, HttpResponse

from sdlc_factory.cli_foundry import NO_TOOLS_NOTICE, CliFoundry, QuotaError
from sdlc_factory.config import load_factory
from sdlc_factory.engines import ABORTED_RC, TIMEOUT_RC, AgyEngine, ProcessOutput

REPO = Path(__file__).resolve().parents[2]
FACTORY = load_factory(REPO / "factory" / "factory.yaml")
TOKEN = "agy-token-value"
FEASIBLE = {"suitable": True, "reasons": ["web only"], "risk": "low", "affected_paths": ["app/web/src"]}
TRIAGE = {"severity": "s2", "owner": "api", "summary": "label lookup 500s",
          "suspected_area": "app/api", "rationale": "stack trace points at the api"}
AUTH_STDERR = "Authentication required. Open https://accounts.example/device to sign in.\n"
QUOTA_STDERR = ('AGY_ERROR: {"short_error":"RESOURCE_EXHAUSTED (code 429): quota exceeded",'
                '"status":"RESOURCE_EXHAUSTED","error_code":429}\n')
TIMEOUT_STDERR = "[agy] print timeout after 5m0s with turn in progress; returning partial output\n"


def agy_stdout(response: str, *, tokens: int = 10, status: str = "SUCCESS") -> str:
    usage = {"input_tokens": tokens, "output_tokens": tokens, "thinking_tokens": 2 * tokens,
             "total_tokens": 4 * tokens}
    return json.dumps({"event": "result", "result": {
        "status": status, "response": response, "duration_seconds": 1.0, "usage": usage,
        "denied_actions": []}}) + "\n"


class ScriptedRunner:
    """Plays scripted agy process outputs in order and records what each call saw."""

    def __init__(self, *outputs: ProcessOutput, clock: FakeClock | None = None, seconds: float = 0.0):
        self.outputs = list(outputs)
        self.calls: list[dict[str, Any]] = []
        self.clock, self.seconds = clock, seconds

    def __call__(self, argv, *, cwd, env, timeout_s, abort_on) -> ProcessOutput:
        home = Path(env["HOME"])
        token = home / AGY_AUTH_FILE
        self.calls.append({
            "argv": argv, "cwd": Path(cwd), "home": home, "timeout_s": timeout_s,
            "cwd_entries": sorted(p.name for p in Path(cwd).iterdir()),
            "token": token.read_text() if token.is_file() else None,
            "token_mode": token.stat().st_mode & 0o777 if token.is_file() else None,
            "schema": _schema_arg(argv),
        })
        if self.clock is not None:
            self.clock.now += self.seconds
        return self.outputs.pop(0)

    @property
    def prompts(self) -> list[str]:
        return [c["argv"][c["argv"].index("-p") + 1] for c in self.calls]


def _schema_arg(argv: list[str]) -> Any:
    if "--json-schema" not in argv:
        return None
    return json.loads(Path(argv[argv.index("--json-schema") + 1]).read_text())


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def ok(response: str, tokens: int = 10) -> ProcessOutput:
    return ProcessOutput(0, agy_stdout(response, tokens=tokens), "")


@pytest.fixture
def token_file(tmp_path: Path) -> Path:
    path = tmp_path / "secrets" / "agy-token"
    path.parent.mkdir()
    path.write_text(TOKEN + "\n")
    return path


def make(token_file: Path, runner: ScriptedRunner, **kw: Any) -> CliFoundry:
    return CliFoundry(FACTORY, token_path=token_file, runner=runner,
                      engine_factory=lambda _agent: AgyEngine(binary=Path("/opt/agy/bin/agy")), **kw)


# --------------------------------------------------------------------------------- prompt agents

def test_schema_agent_returns_compact_json_and_tokens(token_file):
    runner = ScriptedRunner(ok(json.dumps(TRIAGE, indent=2), tokens=7))
    result = make(token_file, runner).call_prompt_agent("sdlc-triage", "INPUT-TEXT")

    assert isinstance(result, AgentResult)
    assert result.text == json.dumps(TRIAGE, separators=(",", ":"))
    assert (result.input_tokens, result.output_tokens) == (7, 7 + 14)   # thinking counts as output
    call = runner.calls[0]
    agent = FACTORY.agent("sdlc-triage")
    assert runner.prompts[0] == f"{agent.instructions}\n\n{NO_TOOLS_NOTICE}\n\nINPUT-TEXT"
    assert call["argv"][call["argv"].index("--mode") + 1] == "plan"
    assert call["schema"] == agent.schema
    assert call["timeout_s"] > agent.timeout_s


def test_each_call_gets_an_empty_cwd_and_a_private_home_copy_that_are_removed(token_file):
    runner = ScriptedRunner(ok(json.dumps(TRIAGE)), ok(json.dumps(TRIAGE)))
    foundry = make(token_file, runner)
    foundry.call_prompt_agent("sdlc-triage", "a")
    foundry.call_prompt_agent("sdlc-triage", "b")

    first, second = runner.calls
    assert first["cwd_entries"] == [] and second["cwd_entries"] == []
    assert first["token"] == TOKEN and first["token_mode"] == 0o600
    assert first["home"] != second["home"] and first["cwd"] != second["cwd"]
    assert first["cwd"] != first["home"]
    for call in (first, second):
        assert not call["home"].exists() and not call["cwd"].exists()


def test_fenced_json_is_extracted(token_file):
    runner = ScriptedRunner(ok(f"Here you go:\n```json\n{json.dumps(TRIAGE)}\n```\n"))
    result = make(token_file, runner).call_prompt_agent("sdlc-triage", "x")
    assert json.loads(result.text) == TRIAGE
    assert len(runner.calls) == 1


def test_invalid_answer_is_repaired_once_internally(token_file):
    runner = ScriptedRunner(ok("I think it is an api bug."), ok(json.dumps(TRIAGE)))
    foundry = make(token_file, runner)
    result = foundry.call_prompt_agent("sdlc-triage", "x")

    assert json.loads(result.text) == TRIAGE
    assert (result.input_tokens, result.output_tokens) == (20, 60)       # both calls summed
    assert "rejected" in runner.prompts[1] and runner.prompts[1].startswith(runner.prompts[0])
    assert foundry.usage_summary()["calls"] == 2


def test_still_invalid_after_internal_repair_returns_text_for_run_agent_to_judge(token_file):
    bad = dict(TRIAGE, severity="catastrophic")
    runner = ScriptedRunner(ok(json.dumps(bad)), ok(f"```json\n{json.dumps(bad)}\n```"))
    result = make(token_file, runner).call_prompt_agent("sdlc-triage", "x")
    assert result.text == json.dumps(bad, separators=(",", ":"))
    assert len(runner.calls) == 2


def test_markdown_agent_passes_text_through(token_file):
    notes = "## Release notes\n\n- Fixed label lookup.\n"
    runner = ScriptedRunner(ok(notes))
    result = make(token_file, runner).call_prompt_agent("sdlc-release-notes", "x")
    assert result.text == notes
    assert runner.calls[0]["schema"] is None


def test_agents_that_mention_github_tools_are_told_no_tools_exist(token_file):
    # agy has no get_file_contents: a call attempt is denied and the run ends empty (live scenario a).
    runner = ScriptedRunner(ProcessOutput(0, agy_stdout(json.dumps(FEASIBLE)), ""))
    make(token_file, runner).call_prompt_agent("sdlc-feasibility", "INPUT-TEXT")
    prompt = runner.prompts[0]
    assert "get_file_contents" in prompt                          # the shared instructions are untouched
    notice = prompt.split("INPUT-TEXT")[0].rsplit("\n\n", 2)[-2]
    assert "NO TOOLS" in notice and "Never call a tool" in notice


def test_every_prompt_agent_is_told_no_tools_exist(token_file):
    # Plan mode auto-denies any tool call and the run then ends empty. The req-gate asked for a command on
    # a feature issue that never mentioned a tool (live #123: "auto-denied ... allow-rule under permissions").
    for agent, payload in (("sdlc-triage", TRIAGE), ("sdlc-feasibility", FEASIBLE)):
        runner = ScriptedRunner(ProcessOutput(0, agy_stdout(json.dumps(payload)), ""))
        make(token_file, runner).call_prompt_agent(agent, "INPUT-TEXT")
        assert NO_TOOLS_NOTICE in runner.prompts[0], agent
    assert "Never call a tool" in NO_TOOLS_NOTICE and "command" in NO_TOOLS_NOTICE


def test_image_urls_are_listed_in_the_prompt(token_file):
    runner = ScriptedRunner(ok("## ok\n"))
    make(token_file, runner).call_prompt_agent("sdlc-release-notes", "x", image_urls=["https://img/a.png"])
    assert "https://img/a.png" in runner.prompts[0]


def test_unknown_agent_is_a_clear_non_transient_error(token_file):
    with pytest.raises(AgentRunError, match="unknown agent") as info:
        make(token_file, ScriptedRunner()).call_prompt_agent("sdlc-nope", "x")
    assert not info.value.transient


def test_oversized_prompt_fails_before_spending_a_call(token_file):
    runner = ScriptedRunner()
    with pytest.raises(AgentRunError, match="chars") as info:
        make(token_file, runner).call_prompt_agent("sdlc-triage", "x" * 200_000)
    assert not info.value.transient and runner.calls == []


def test_missing_token_file_is_a_non_transient_auth_error(tmp_path):
    runner = ScriptedRunner()
    with pytest.raises(AgentRunError, match="token") as info:
        make(tmp_path / "absent", runner).call_prompt_agent("sdlc-triage", "x")
    assert not info.value.transient and runner.calls == []


# ------------------------------------------------------------------------------- error mapping

@pytest.mark.parametrize(("output", "match"), [
    (ProcessOutput(0, agy_stdout(""), TIMEOUT_STDERR), "timeout"),
    (ProcessOutput(0, agy_stdout(""), ""), "empty"),
    (ProcessOutput(1, "", "segfault"), "failed"),
    (ProcessOutput(TIMEOUT_RC, "", ""), "timeout"),
])
def test_timeout_empty_failed_are_transient_and_carry_usage(token_file, output, match):
    with pytest.raises(AgentRunError, match=match) as info:
        make(token_file, ScriptedRunner(output)).call_prompt_agent("sdlc-triage", "x")
    assert info.value.transient
    assert not isinstance(info.value, QuotaError)


def test_a_denied_or_empty_failure_names_what_agy_said_without_urls(token_file):
    # "ended denied (rc 0)" alone cannot tell a denied tool from a model that answered nothing (live #119).
    stderr = "no output produced; see https://example.test/trace?id=1 for details\n"
    with pytest.raises(AgentRunError) as info:
        make(token_file, ScriptedRunner(ProcessOutput(0, agy_stdout(""), stderr))).call_prompt_agent(
            "sdlc-triage", "x")
    assert "no output produced" in str(info.value)
    assert "example.test" not in str(info.value)
    assert "\n" not in str(info.value)


def test_failed_engine_usage_is_carried_for_billing(token_file):
    runner = ScriptedRunner(ProcessOutput(0, agy_stdout("", tokens=5), TIMEOUT_STDERR))
    with pytest.raises(AgentRunError) as info:
        make(token_file, runner).call_prompt_agent("sdlc-triage", "x")
    assert (info.value.input_tokens, info.value.output_tokens) == (5, 15)


def test_auth_is_non_transient_with_a_clear_message_and_no_login_url(token_file):
    with pytest.raises(AgentRunError, match="authentication") as info:
        make(token_file, ScriptedRunner(ProcessOutput(ABORTED_RC, "", AUTH_STDERR))).call_prompt_agent(
            "sdlc-triage", "x")
    assert not info.value.transient
    assert "accounts.example" not in str(info.value)


def test_quota_raises_quota_error_that_defers_and_sets_the_flag(token_file):
    foundry = make(token_file, ScriptedRunner(ProcessOutput(3, "", QUOTA_STDERR)))
    assert not foundry.quota_hit
    with pytest.raises(QuotaError) as info:
        foundry.call_prompt_agent("sdlc-triage", "x")
    assert isinstance(info.value, AgentRunError) and info.value.transient
    assert foundry.quota_hit
    # The retry hint outlasts any tick, so call_with_retry gives up at once instead of burning calls.
    attempts: list[int] = []

    def fn() -> None:
        attempts.append(1)
        raise info.value

    policy = RetryPolicy(sleep=lambda _s: None, monotonic=lambda: 0.0, deadline=900.0)
    with pytest.raises(QuotaError):
        call_with_retry(fn, policy)
    assert len(attempts) == 1


# ------------------------------------------------------------------------------------- budget

def test_counters_track_calls_minutes_and_surrogate_usd(token_file):
    clock = FakeClock()
    runner = ScriptedRunner(ok("nope"), ok(json.dumps(TRIAGE)), ProcessOutput(0, agy_stdout(""), TIMEOUT_STDERR),
                            clock=clock, seconds=90.0)
    foundry = make(token_file, runner, monotonic=clock)
    foundry.call_prompt_agent("sdlc-triage", "x")
    with pytest.raises(AgentRunError):
        foundry.call_prompt_agent("sdlc-triage", "y")

    summary = foundry.usage_summary()
    assert summary["calls"] == 3
    assert summary["minutes"] == pytest.approx(4.5)
    budget = FACTORY.budget
    assert summary["usd"] == pytest.approx(3 * budget.call_usd + 4.5 * budget.minute_usd)
    assert foundry.surrogate_usd(60, 0) == pytest.approx(budget.issue_cap_usd())
    assert foundry.surrogate_usd(0, budget.per_issue_max_minutes) == pytest.approx(3.00)


def test_counters_are_thread_safe(token_file):
    n = 40
    runner = ScriptedRunner(*[ok(json.dumps(TRIAGE)) for _ in range(n)])
    lock = threading.Lock()

    def locked(*a: Any, **kw: Any) -> ProcessOutput:
        with lock:
            return ScriptedRunner.__call__(runner, *a, **kw)

    foundry = CliFoundry(FACTORY, token_path=token_file, runner=locked,
                         engine_factory=lambda _a: AgyEngine(binary=Path("/opt/agy/bin/agy")))
    threads = [threading.Thread(target=foundry.call_prompt_agent, args=("sdlc-triage", "x")) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert foundry.usage_summary()["calls"] == n


# ------------------------------------------------------------------------------- hosted coder

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


def reply(status: int, body: dict[str, Any] | str, headers: dict[str, str] | None = None) -> HttpResponse:
    raw = body if isinstance(body, str) else json.dumps(body)
    return HttpResponse(status, {"content-type": "application/json", **(headers or {})}, raw.encode())


def coder(token_file: Path, transport: FakeTransport, **kw: Any) -> CliFoundry:
    return CliFoundry(FACTORY, token_path=token_file, coder_url="http://coder:8080/", transport=transport, **kw)


def test_coder_start_then_status_round_trips_the_session_id(token_file):
    transport = FakeTransport(
        reply(200, {"job_id": "j-12-1", "status": "running"}, {"x-agent-session-id": "s-abc"}),
        reply(200, {"job_id": "j-12-1", "status": "succeeded"}),
    )
    foundry = coder(token_file, transport)
    body, session = foundry.invoke_hosted("sdlc-coder", {"op": "start", "job": {"job_id": "j-12-1"}})
    assert (body["status"], session) == ("running", "s-abc")
    body, session2 = foundry.invoke_hosted("sdlc-coder", {"op": "status", "job_id": "j-12-1"},
                                           session_id=session, timeout_s=30)
    assert (body["status"], session2) == ("succeeded", "s-abc")

    start, status = transport.requests
    assert start.method == "POST" and start.url == "http://coder:8080/invoke"
    assert json.loads(start.body) == {"op": "start", "job": {"job_id": "j-12-1"}}
    assert start.headers["Content-Type"] == "application/json"
    parsed = urllib.parse.urlparse(status.url)
    assert parsed.path == "/invoke" and urllib.parse.parse_qs(parsed.query) == {"agent_session_id": ["s-abc"]}
    assert status.timeout_s == 30


def test_coder_session_falls_back_to_body_then_to_the_given_id(token_file):
    transport = FakeTransport(reply(200, {"status": "running", "session_id": "s-body"}),
                              reply(200, {"status": "running"}))
    foundry = coder(token_file, transport)
    assert foundry.invoke_hosted("sdlc-coder", {"op": "status"})[1] == "s-body"
    assert foundry.invoke_hosted("sdlc-coder", {"op": "status"}, session_id="s-old")[1] == "s-old"


def test_coder_session_gone_maps_to_what_tick_detects(token_file):
    from sdlc_agents.tick import _session_gone

    transport = FakeTransport(reply(404, {"error": {"code": "session_not_accessible"}}))
    with pytest.raises(AgentRunError) as info:
        coder(token_file, transport).invoke_hosted("sdlc-coder", {"op": "status"}, session_id="s-x")
    assert info.value.http_status == 404 and not info.value.transient
    assert _session_gone(info.value)


@pytest.mark.parametrize(("item", "transient", "ambiguous", "status"), [
    (reply(503, "busy"), True, True, 503),
    (reply(429, "slow down", {"retry-after": "7"}), True, False, 429),
    (reply(400, "bad job"), False, True, 400),
    (TimeoutError("timed out"), True, True, None),
    (ConnectionRefusedError("refused"), True, False, None),
])
def test_coder_failures_are_classified_like_foundry(token_file, item, transient, ambiguous, status):
    with pytest.raises(AgentRunError) as info:
        coder(token_file, FakeTransport(item)).invoke_hosted("sdlc-coder", {"op": "start"})
    assert (info.value.transient, info.value.ambiguous, info.value.http_status) == (transient, ambiguous, status)


def test_coder_retry_after_is_honoured(token_file):
    with pytest.raises(AgentRunError) as info:
        coder(token_file, FakeTransport(reply(429, "x", {"retry-after": "7"}))).invoke_hosted("sdlc-coder", {})
    assert info.value.retry_after == 7.0


def test_coder_non_json_reply_is_a_non_transient_error(token_file):
    with pytest.raises(AgentRunError, match="not JSON") as info:
        coder(token_file, FakeTransport(reply(200, "<html>"))).invoke_hosted("sdlc-coder", {})
    assert not info.value.transient


def test_coder_without_url_is_a_clear_error(token_file):
    foundry = CliFoundry(FACTORY, token_path=token_file)
    with pytest.raises(AgentRunError, match="CODER_URL"):
        foundry.invoke_hosted("sdlc-coder", {})


def test_coder_url_must_be_http(token_file):
    with pytest.raises(ValueError, match="coder_url"):
        CliFoundry(FACTORY, token_path=token_file, coder_url="file:///etc/passwd")


def test_other_hosted_agents_go_to_the_ledger_handler(token_file):
    seen: list[tuple[str, dict[str, Any], str | None]] = []

    def handler(agent: str, body: dict[str, Any], session_id: str | None) -> tuple[dict[str, Any], str]:
        seen.append((agent, body, session_id))
        return {"ok": True}, "ledger-session"

    foundry = CliFoundry(FACTORY, token_path=token_file, ledger_handler=handler)
    assert foundry.invoke_hosted("sdlc-ledger", {"events": []}, session_id="s1") == ({"ok": True}, "ledger-session")
    assert seen == [("sdlc-ledger", {"events": []}, "s1")]


def test_other_hosted_agents_without_a_handler_raise(token_file):
    with pytest.raises(AgentRunError, match="sdlc-ledger") as info:
        CliFoundry(FACTORY, token_path=token_file).invoke_hosted("sdlc-ledger", {})
    assert not info.value.transient


# --------------------------------------------------------------------------------- from_env

def test_from_env_reads_config_token_and_coder_url(monkeypatch, token_file):
    monkeypatch.setenv("FACTORY_CONFIG", str(REPO / "factory" / "factory.yaml"))
    monkeypatch.setenv("AGY_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("CODER_URL", "http://coder:8080")
    transport = FakeTransport(reply(200, {"status": "running"}, {"x-agent-session-id": "s"}))
    foundry = CliFoundry.from_env(transport=transport)
    assert foundry.invoke_hosted("sdlc-coder", {})[1] == "s"
    assert transport.requests[0].url == "http://coder:8080/invoke"


def test_from_env_requires_the_token_file(monkeypatch):
    monkeypatch.setenv("FACTORY_CONFIG", str(REPO / "factory" / "factory.yaml"))
    monkeypatch.delenv("AGY_TOKEN_FILE", raising=False)
    with pytest.raises(ValueError, match="AGY_TOKEN_FILE"):
        CliFoundry.from_env()


# ---------------------------------------------------------- integration with tick's run_agent

def test_run_agent_over_cli_foundry_validates_and_bills_triage(token_file):
    runner = ScriptedRunner(ok(f"```json\n{json.dumps(TRIAGE)}\n```", tokens=4))
    billed: list[tuple[str, int, int]] = []
    out = run_agent(make(token_file, runner), "sdlc-triage", [Section("issue", "#12 label lookup 500s")],
                    bill=lambda *a: billed.append(a))
    assert out.data == TRIAGE
    assert billed == [("sdlc-triage", 4, 12)]
    assert "<untrusted_input nonce=" in runner.prompts[0]


def test_run_agent_repairs_what_cli_foundry_passes_through(token_file):
    bad = dict(TRIAGE, owner="nobody")
    runner = ScriptedRunner(ok(json.dumps(bad)), ok(json.dumps(bad)), ok(json.dumps(TRIAGE)))
    out = run_agent(make(token_file, runner), "sdlc-triage", [Section("issue", "#12")])
    assert out.data == TRIAGE
    assert len(runner.calls) == 3      # CliFoundry's own repair, then run_agent's repair


def test_run_agent_markdown_agent_over_cli_foundry(token_file):
    runner = ScriptedRunner(ok("## Notes\n\n- Fixed it.\n"))
    out = run_agent(make(token_file, runner), "sdlc-release-notes", [Section("pr", "#13")])
    assert out.data is None and "Fixed it." in out.text


# ------------------------------------------------------------------------------ review follow-ups

def test_factory_schemas_match_the_schemas_run_agent_validates_against():
    from sdlc_agents.definitions import AGENT_BY_NAME

    for name, agent in FACTORY.agents.items():
        if name in AGENT_BY_NAME:
            assert agent.output_kind == AGENT_BY_NAME[name].output_kind, name
            assert agent.schema == AGENT_BY_NAME[name].schema, name


def test_prompt_mode_other_than_plan_is_refused(token_file):
    from dataclasses import replace

    from sdlc_factory.config import ConfigError

    widened = replace(FACTORY, engines={"agy": {**FACTORY.engines["agy"], "promptMode": "accept-edits"}})
    with pytest.raises(ConfigError, match="promptMode"):
        CliFoundry(widened, token_path=token_file)


def test_binary_that_cannot_run_is_not_transient(token_file):
    from sdlc_factory.engines import NOT_FOUND_RC

    runner = ScriptedRunner(ProcessOutput(NOT_FOUND_RC, "", "cannot run /opt/agy/bin/agy: FileNotFoundError"))
    with pytest.raises(AgentRunError, match="cannot be run") as info:
        make(token_file, runner).call_prompt_agent("sdlc-triage", "x")
    assert not info.value.transient


def test_auth_error_is_its_own_type(token_file):
    from sdlc_factory.cli_foundry import AuthError

    with pytest.raises(AuthError):
        make(token_file, ScriptedRunner(ProcessOutput(ABORTED_RC, "", AUTH_STDERR))).call_prompt_agent(
            "sdlc-triage", "x")


def test_after_a_quota_hit_calls_fail_fast_until_the_hold_ends(token_file):
    from sdlc_factory.cli_foundry import QUOTA_HOLD_S

    clock = FakeClock()
    runner = ScriptedRunner(ProcessOutput(3, "", QUOTA_STDERR), ok(json.dumps(TRIAGE)))
    foundry = make(token_file, runner, monotonic=clock)
    with pytest.raises(QuotaError):
        foundry.call_prompt_agent("sdlc-triage", "x")
    with pytest.raises(QuotaError, match="agent-quota"):
        foundry.call_prompt_agent("sdlc-triage", "y")
    assert len(runner.calls) == 1
    clock.now += QUOTA_HOLD_S + 1
    assert json.loads(foundry.call_prompt_agent("sdlc-triage", "z").text) == TRIAGE
    assert foundry.quota_hit


def test_quota_during_the_internal_repair_carries_both_calls_usage(token_file):
    runner = ScriptedRunner(ok("no json here", tokens=5), ProcessOutput(3, "", QUOTA_STDERR))
    with pytest.raises(QuotaError) as info:
        make(token_file, runner).call_prompt_agent("sdlc-triage", "x")
    assert (info.value.input_tokens, info.value.output_tokens) == (5, 15)


def test_engine_that_refuses_the_call_is_counted_and_cleans_up(token_file, tmp_path, monkeypatch):
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "t"))
    (tmp_path / "t").mkdir()

    class Refusing(AgyEngine):
        def argv(self, *a: Any, **kw: Any) -> list[str]:
            raise ValueError("bad timeout")

    foundry = CliFoundry(FACTORY, token_path=token_file, runner=ScriptedRunner(),
                         engine_factory=lambda _a: Refusing(binary=Path("/opt/agy/bin/agy")))
    with pytest.raises(AgentRunError, match="not started") as info:
        foundry.call_prompt_agent("sdlc-triage", "x")
    assert not info.value.transient
    assert foundry.usage_summary()["calls"] == 1
    assert not any(p.name.startswith("cli-agent-") for p in (tmp_path / "t").iterdir())


def test_engine_factory_failure_is_an_agent_run_error(token_file):
    from sdlc_factory.config import ConfigError

    def broken(_agent: Any) -> Any:
        raise ConfigError("no engine")

    foundry = CliFoundry(FACTORY, token_path=token_file, runner=ScriptedRunner(), engine_factory=broken)
    with pytest.raises(AgentRunError, match="no engine") as info:
        foundry.call_prompt_agent("sdlc-triage", "x")
    assert not info.value.transient


def test_coder_urlerror_refused_is_unambiguous_and_cut_reply_is_transient(token_file):
    import http.client
    import urllib.error

    refused = urllib.error.URLError(ConnectionRefusedError("refused"))
    cut = http.client.IncompleteRead(b"{", 10)
    transport = FakeTransport(refused, cut)
    foundry = coder(token_file, transport)
    with pytest.raises(AgentRunError) as info:
        foundry.invoke_hosted("sdlc-coder", {})
    assert info.value.transient and not info.value.ambiguous
    with pytest.raises(AgentRunError) as info:
        foundry.invoke_hosted("sdlc-coder", {})
    assert info.value.transient and info.value.ambiguous


def test_coder_requests_carry_the_shared_token_when_configured(token_file):
    transport = FakeTransport(reply(200, {"status": "running"}, {"x-agent-session-id": "s"}))
    coder(token_file, transport, coder_token="s3cret").invoke_hosted("sdlc-coder", {"op": "status"})
    assert transport.requests[0].headers["x-factory-token"] == "s3cret"


def test_coder_requests_have_no_token_header_by_default(token_file):
    transport = FakeTransport(reply(200, {"status": "running"}, {"x-agent-session-id": "s"}))
    coder(token_file, transport).invoke_hosted("sdlc-coder", {"op": "status"})
    assert "x-factory-token" not in transport.requests[0].headers


def test_from_env_reads_the_coder_service_token(token_file, monkeypatch):
    monkeypatch.setenv("AGY_TOKEN_FILE", str(token_file))
    monkeypatch.setenv("CODER_SERVICE_TOKEN", "tok")
    monkeypatch.setenv("CODER_URL", "http://coder:8090")
    monkeypatch.setenv("FACTORY_CONFIG", str(Path(__file__).resolve().parents[2] / "factory" / "factory.yaml"))
    foundry = CliFoundry.from_env()
    assert foundry._coder_token == "tok"
