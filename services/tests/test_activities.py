"""
The Temporal activities over the existing tick: `run_step` steps ONE object through `run_tick(only=N,
use_lock=False)`, `list_work` names the objects a workflow should drive, `po_intake` is off by default.
Also the deps they are bound to (`deps.build_from_env`) and the ledger HTTP emitter.

`fake_deps` and `spaced` are the harness the workflow and worker tests reuse.
"""

from __future__ import annotations

import dataclasses
import http.server
import json
import socket
import threading
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from conftest import World
from sdlc_agents import state
from sdlc_agents.gates import MAINTENANCE_LABEL
from sdlc_agents.github import GitHubClient
from sdlc_agents.ports import Budget, GitHubError
from temporalio import activity
from temporalio.exceptions import ApplicationError
from test_scenarios import A_BODY, open_stale_test_pr

from sdlc_factory.activities import StepInput, StepOutput, WorkRef, build_activities
from sdlc_factory.cli_foundry import AuthError, QuotaError
from sdlc_factory.config import load_factory
from sdlc_factory.deps import FactoryDeps, build_from_env
from sdlc_factory.http_emitter import HttpEmitter

FACTORY_YAML = Path(__file__).resolve().parents[2] / "factory" / "factory.yaml"
TICK_SPACING_S = 300


# -- harness reused by test_workflows / test_worker ----------------------------------------------

def fake_deps(world: World) -> FactoryDeps:
    """Deps bound to the agents test world: FakeGitHub, FakeFoundry (with FakeCoder), FakeClock."""
    config = load_factory(FACTORY_YAML)
    return FactoryDeps(
        github=world.gh, foundry=world.foundry, clock=world.clock,
        budget=Budget(usd_cap_issue=config.budget.issue_cap_usd(), usd_cap_total=config.budget.total_cap_usd()),
        emitter=world.emitter, config=config, sleep=world.sleep,
    )


def spaced(world: World, activities: list[Callable], *,
           around: Callable[[Callable[[StepInput], StepOutput], StepInput], StepOutput] | None = None) -> list:
    """The activities with `run_step` advancing the fake clock one tick spacing after every step (the cron
    gap the old tick loop had), optionally wrapped by `around(original, input)`."""
    original = next(a for a in activities if activity._Definition.must_from_callable(a).name == "run_step")

    @activity.defn(name="run_step")
    def run_step(inp: StepInput) -> StepOutput:
        try:
            return around(original, inp) if around else original(inp)
        finally:
            world.clock.advance(TICK_SPACING_S)

    return [run_step if a is original else a for a in activities]


def by_name(activities: list[Callable]) -> dict[str, Callable]:
    return {activity._Definition.must_from_callable(a).name: a for a in activities}


# -- names ------------------------------------------------------------------------------------------

def test_build_activities_names_are_exactly_run_step_list_work_po_intake(world: World) -> None:
    names = [activity._Definition.must_from_callable(a).name for a in build_activities(fake_deps(world))]

    assert sorted(names) == ["list_work", "po_intake", "run_step"]


# -- run_step -------------------------------------------------------------------------------------

def test_run_step_advances_only_the_named_issue_and_reads_the_outcome_back(world: World) -> None:
    run_step = by_name(build_activities(fake_deps(world)))["run_step"]
    a = world.gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))
    b = world.gh.open_issue("Filter parcels by status", A_BODY, labels=("type:feature",))

    out = run_step(StepInput(number=a, hold=[]))

    assert (out.action, out.result, out.stage, out.terminal, out.wait_hint_s) == ("gate", "ok", state.READY,
                                                                                  False, 60)
    assert state.READY in world.gh.labels(a)
    assert world.gh.labels(b) == {"type:feature"} and not world.gh.comments[b]
    assert world.gh.state_of(a)       # the state comment was written
    json.dumps(dataclasses.asdict(out))     # JSON-safe for the Temporal data converter


def test_run_step_marks_the_issue_as_run_by_this_factory_once(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    deps = fake_deps(world)
    label = deps.config.ticket_label
    sent: list[tuple[int, tuple[str, ...]]] = []
    real = world.gh.add_labels
    monkeypatch.setattr(world.gh, "add_labels", lambda n, labels: (sent.append((n, labels)), real(n, labels))[1])
    run_step = by_name(build_activities(deps))["run_step"]
    a = world.gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))
    b = world.gh.open_issue("Filter parcels by status", A_BODY, labels=("type:feature",))

    run_step(StepInput(number=a, hold=[]))
    world.clock.advance(TICK_SPACING_S)
    run_step(StepInput(number=a, hold=[]))

    assert label in world.gh.labels(a)
    assert label not in world.gh.labels(b)                       # an issue this factory never ran stays unmarked
    assert [n for n, labels in sent if label in labels] == [a]   # added once, not on every step


def test_a_failed_marking_never_fails_the_step(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    deps = fake_deps(world)
    real = world.gh.add_labels

    def flaky(n, labels):
        if deps.config.ticket_label in labels:
            raise GitHubError(502, "boom")
        real(n, labels)

    monkeypatch.setattr(world.gh, "add_labels", flaky)
    a = world.gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))
    out = by_name(build_activities(deps))["run_step"](StepInput(number=a, hold=[]))
    assert out.result == "ok" and state.READY in world.gh.labels(a)


def test_run_step_reports_a_held_step_and_does_nothing(world: World) -> None:
    run_step = by_name(build_activities(fake_deps(world)))["run_step"]
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))

    outs = []
    for _ in range(10):
        outs.append(run_step(StepInput(number=n, hold=["design-tests"])))
        world.clock.advance(TICK_SPACING_S)
        if outs[-1].result == "held":
            break

    assert outs[-1].action == "design-tests" and outs[-1].result == "held" and not outs[-1].terminal
    assert not world.foundry.agent_calls("sdlc-test-designer")


def test_run_step_starts_each_step_with_a_fresh_budget(world: World) -> None:
    """A step that fails closed (unreadable metrics.json) must not halt every later step: Budget is
    per tick in run_tick, so the activity cannot share one across steps."""
    deps = fake_deps(world)
    run_step = by_name(build_activities(deps))["run_step"]
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))
    world.gh.create_branch("metrics", from_sha=world.gh.branches["main"])
    world.gh.files[("metrics", "metrics.json")] = "not json"

    halted = run_step(StepInput(number=n, hold=[]))
    world.clock.advance(TICK_SPACING_S)
    resumed = run_step(StepInput(number=n, hold=[]))

    assert halted.action == "halt" and "spend cannot be determined" in halted.detail and halted.stage is None
    assert resumed.result == "ok" and resumed.stage == state.READY
    assert deps.budget.known and deps.budget.usd_total == 0.0


class MeteredFoundry:
    """FakeFoundry with CliFoundry's usage meter: each prompt call counts one call and one minute."""

    def __init__(self, inner, config) -> None:
        self._inner, self._config, self.calls, self.minutes = inner, config, 0, 0.0

    def call_prompt_agent(self, agent: str, input_text: str, **kw):
        self.calls += 1
        self.minutes += 1.0
        return self._inner.call_prompt_agent(agent, input_text, **kw)

    def invoke_hosted(self, *args, **kw):
        return self._inner.invoke_hosted(*args, **kw)

    def surrogate_usd(self, calls: int, minutes: float) -> float:
        return round(calls * self._config.budget.call_usd + minutes * self._config.budget.minute_usd, 6)

    def usage_summary(self) -> dict:
        return {"calls": self.calls, "minutes": self.minutes,
                "usd": self.surrogate_usd(self.calls, self.minutes), "quota_hit": False}


def test_run_step_carries_the_surrogate_spend_of_its_own_calls(world: World) -> None:
    deps = fake_deps(world)
    deps.foundry = MeteredFoundry(world.foundry, deps.config)
    deps.foundry.calls, deps.foundry.minutes = 7, 3.0      # earlier steps, other issues: not this step's
    run_step = by_name(build_activities(deps))["run_step"]
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))

    out = run_step(StepInput(number=n, hold=[]))

    calls = deps.foundry.calls - 7
    assert calls >= 1 and out.calls == calls and out.minutes == float(calls)
    assert out.surrogate_usd == deps.foundry.surrogate_usd(calls, float(calls))


def metered(world: World, call_usd: float) -> FactoryDeps:
    """fake_deps whose foundry meters calls like CliFoundry, at `call_usd` per call plus the minute rate."""
    deps = fake_deps(world)
    config = dataclasses.replace(deps.config, budget=dataclasses.replace(deps.config.budget, call_usd=call_usd))
    deps.foundry = MeteredFoundry(world.foundry, config)
    return deps


def drive(run_step: Callable[[StepInput], StepOutput], world: World, n: int, until: Callable[[], bool],
          max_steps: int = 40) -> list[StepOutput]:
    outs = []
    for _ in range(max_steps):
        outs.append(run_step(StepInput(number=n, hold=[])))
        world.clock.advance(TICK_SPACING_S)
        if until():
            break
    return outs


def test_run_step_bills_the_surrogate_spend_to_the_issue_instead_of_tokens(world: World) -> None:
    deps = metered(world, 0.05)
    deps.foundry.calls, deps.foundry.minutes = 7, 3.0      # earlier steps, other issues: not this issue's
    run_step = by_name(build_activities(deps))["run_step"]
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))

    out = run_step(StepInput(number=n, hold=[]))

    assert out.calls >= 1
    assert world.gh.state_of(n)["cost"]["usd"] == pytest.approx(out.surrogate_usd)   # not tokens + surrogate


def test_run_step_escalates_cost_cap_when_the_surrogate_spend_reaches_the_issue_cap(world: World) -> None:
    deps = metered(world, 1.5)            # 1.52 USD a call with the minute: the 3.00 cap after two calls
    run_step = by_name(build_activities(deps))["run_step"]
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))

    outs = drive(run_step, world, n, lambda: state.ESC_COST_CAP in world.gh.labels(n))

    assert state.ESC_COST_CAP in world.gh.labels(n)
    assert outs[-1].action == "escalate" and outs[-1].terminal
    assert deps.foundry.calls == 2
    assert world.gh.state_of(n)["cost"]["usd"] >= deps.budget.usd_cap_issue


def test_run_step_under_the_cap_does_not_escalate(world: World) -> None:
    deps = metered(world, 0.05)
    run_step = by_name(build_activities(deps))["run_step"]
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))

    outs = drive(run_step, world, n, lambda: False, max_steps=3)

    assert not any(label.startswith("escalated:") for label in world.gh.labels(n))
    assert world.gh.state_of(n)["cost"]["usd"] == pytest.approx(sum(o.surrogate_usd for o in outs))


def test_run_step_without_a_usage_meter_reports_no_surrogate_spend(world: World) -> None:
    run_step = by_name(build_activities(fake_deps(world)))["run_step"]
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))

    out = run_step(StepInput(number=n, hold=[]))

    assert (out.calls, out.minutes, out.surrogate_usd) == (0, 0.0, 0.0)


def test_run_step_reports_an_engine_quota_hit_as_quota(world: World) -> None:
    world.foundry.errors["sdlc-req-gate"] = QuotaError("sdlc-req-gate: agy quota exhausted (agent-quota)",
                                                       transient=True, retry_after=21600, ambiguous=False)
    run_step = by_name(build_activities(fake_deps(world)))["run_step"]
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))

    out = run_step(StepInput(number=n, hold=[]))

    assert out.result == "quota" and out.action == "gate" and not out.terminal
    assert "QuotaError" in out.detail


def test_run_step_reports_an_engine_auth_failure_as_auth(world: World) -> None:
    world.foundry.errors["sdlc-req-gate"] = AuthError("sdlc-req-gate: agy authentication required",
                                                      ambiguous=False)
    run_step = by_name(build_activities(fake_deps(world)))["run_step"]
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))

    out = run_step(StepInput(number=n, hold=[]))

    assert out.result == "auth" and out.action == "gate" and "AuthError" in out.detail


def test_run_step_rejects_a_non_positive_number_as_non_retryable(world: World) -> None:
    run_step = by_name(build_activities(fake_deps(world)))["run_step"]

    with pytest.raises(ApplicationError) as err:
        run_step(StepInput(number=0, hold=[]))

    assert err.value.type == "NonRetryable" and err.value.non_retryable


# -- list_work ------------------------------------------------------------------------------------

def test_list_work_names_owner_issues_and_maintenance_prs_only(world: World) -> None:
    gh = world.gh
    feature = gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))
    gh.open_issue("Please add dark mode", A_BODY, author="someone-else")
    closed = gh.open_issue("Old idea", A_BODY)
    gh.close_issue(closed)
    escalated = gh.open_issue("Needs prod access", A_BODY, labels=("escalated:not-suitable",))
    maintenance = open_stale_test_pr(world)
    gh.open_pr("feat: agent work", "Closes #1", "agent/issue-1", [("feat: x", ("app/x.ts",))])
    gh.open_pr("chore: stranger maintenance", "x", "chore/x", [("chore: x", ("app/y.ts",))],
               author="someone-else", labels=(MAINTENANCE_LABEL,))

    refs = by_name(build_activities(fake_deps(world)))["list_work"]()

    assert refs == [WorkRef(number=feature, kind="issue"), WorkRef(number=maintenance, kind="pr")]
    assert escalated not in {r.number for r in refs}


# -- po_intake ------------------------------------------------------------------------------------

def test_po_intake_is_disabled_by_default(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PO_INTAKE_ENABLED", raising=False)

    assert by_name(build_activities(fake_deps(world)))["po_intake"]() == "disabled"


def test_po_intake_enabled_fails_loudly_until_implemented(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PO_INTAKE_ENABLED", "true")

    with pytest.raises(ApplicationError) as err:
        by_name(build_activities(fake_deps(world)))["po_intake"]()

    assert err.value.non_retryable and "not implemented" in str(err.value)


# -- deps.build_from_env ----------------------------------------------------------------------------

def test_build_from_env_builds_the_real_adapters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pat, agy = tmp_path / "pat", tmp_path / "agy.json"
    pat.write_text("ghp_test\n")
    agy.write_text("{}")
    monkeypatch.setenv("GITHUB_PAT_FILE", str(pat))
    monkeypatch.setenv("AGY_TOKEN_FILE", str(agy))
    monkeypatch.setenv("FACTORY_CONFIG", str(FACTORY_YAML))
    monkeypatch.setenv("LEDGER_URL", "http://ledger-api:8080")

    deps = build_from_env()

    assert isinstance(deps.github, GitHubClient)
    assert type(deps.foundry).__name__ == "CliFoundry"
    assert isinstance(deps.emitter, HttpEmitter)
    assert (deps.budget.usd_cap_issue, deps.budget.usd_cap_total) == (3.0, 100.0)
    assert deps.config.name


def test_build_from_env_without_ledger_url_has_no_emitter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pat").write_text("ghp_test")
    (tmp_path / "agy").write_text("{}")
    monkeypatch.setenv("GITHUB_PAT_FILE", str(tmp_path / "pat"))
    monkeypatch.setenv("AGY_TOKEN_FILE", str(tmp_path / "agy"))
    monkeypatch.setenv("FACTORY_CONFIG", str(FACTORY_YAML))
    monkeypatch.delenv("LEDGER_URL", raising=False)

    assert build_from_env().emitter is None


@pytest.mark.parametrize("content", [None, "", "  \n"])
def test_build_from_env_refuses_a_missing_or_empty_github_token(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str | None) -> None:
    pat = tmp_path / "pat"
    if content is not None:
        pat.write_text(content)
    monkeypatch.setenv("GITHUB_PAT_FILE", str(pat))
    monkeypatch.setenv("FACTORY_CONFIG", str(FACTORY_YAML))

    with pytest.raises(ValueError, match="GITHUB_PAT_FILE"):
        build_from_env()


def test_build_from_env_requires_github_pat_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_PAT_FILE", raising=False)

    with pytest.raises(ValueError, match="GITHUB_PAT_FILE is not set"):
        build_from_env()


# -- http_emitter -----------------------------------------------------------------------------------

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def ledger() -> Iterator[tuple[str, list[dict], list[tuple[int, bytes]]]]:
    """A stand-in ledger-api: records POST /ingest bodies, answers with the queued (status, body) replies."""
    received: list[dict] = []
    replies: list[tuple[int, bytes]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            received.append({"path": self.path,
                             "body": json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
            status, body = replies.pop(0) if replies else (200, b'{"ok": true, "applied": 1}')
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", received, replies
    finally:
        server.shutdown()
        server.server_close()


def test_http_emitter_posts_the_batch_to_ingest(ledger) -> None:
    url, received, _ = ledger

    result = HttpEmitter(url + "/").emit([{"type": "ticket.updated"}], reconcile=True)

    assert result.error is None and result.usd == 0.0 and result.reply == {"ok": True, "applied": 1}
    assert received == [{"path": "/ingest", "body": {"events": [{"type": "ticket.updated"}], "reconcile": True}}]


def test_http_emitter_never_raises_on_connection_refused() -> None:
    result = HttpEmitter(f"http://127.0.0.1:{free_port()}", timeout_s=2).emit([{"type": "x"}])

    assert result.error is not None and result.error.startswith("ledger: ")
    assert result.usd == 0.0


@pytest.mark.parametrize(("status", "body"), [(500, b'{"ok": false, "error": "ingest failed"}'),
                                              (409, b'{"ok": false}'), (200, b"not json"),
                                              (200, b'{"ok": false, "error": "bad"}')])
def test_http_emitter_reports_a_refusal_as_an_error(ledger, status: int, body: bytes) -> None:
    url, _, replies = ledger
    replies.append((status, body))

    result = HttpEmitter(url).emit([])

    assert result.error is not None and result.error.startswith("ledger: ")


def test_http_emitter_rejects_a_non_http_url() -> None:
    with pytest.raises(ValueError, match="http"):
        HttpEmitter("file:///etc/passwd")
