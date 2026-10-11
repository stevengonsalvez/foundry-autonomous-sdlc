"""State comment, state machine, gates, cost, release, lock and metrics as units."""

from __future__ import annotations

import json
from dataclasses import replace

import jsonschema
import pytest
from fakes import FakeClock, FakeGitHub

from sdlc_agents import cost, gates, lock, machine, metrics, release, state
from sdlc_agents.machine import Context, Kind
from sdlc_agents.ports import OWNER, Budget, CheckRun, Comment, GitHubError, Issue, PullRequest

NOW = "2026-10-10T12:00:00Z"
HEAD = "b" * 40
GREEN = dict.fromkeys(gates.REQUIRED_CHECKS, "success")


def make_state(*stages: str, type_: str = "feature") -> state.State:
    st = state.State.new(7, type_, None)
    for s in stages:
        st.enter(s, NOW)
    return st


def pull(**kw: object) -> PullRequest:
    base = PullRequest(number=8, title="t", body="b", author=OWNER, labels=("agent:pr",), state="open", merged=False,
                       head_ref="agent/issue-7", head_sha=HEAD, base_ref="main", created_at=NOW)
    return replace(base, **kw)


def ctx(st: state.State | None, **kw: object) -> Context:
    base = Context(kind="issue", number=7, author=OWNER, labels=frozenset(), is_open=True, object_type="feature",
                   state=st, now=NOW, budget=Budget())
    return replace(base, **kw)


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------

def test_state_round_trips_and_preserves_unknown_keys() -> None:
    st = make_state(state.READY)
    st.data["future_field"] = {"x": 1}
    body = state.render(st)
    assert body.startswith("<!-- sdlc-state:v1\n{") and "\n-->\n**SDLC state** for #7" in body
    parsed = state.parse(body)
    assert parsed is not None and parsed.data == st.data and parsed.stage == state.READY


def test_state_parse_rejects_newer_versions_and_corrupt_documents() -> None:
    assert state.parse("hello") is None
    with pytest.raises(state.StateVersionError):
        state.parse('<!-- sdlc-state:v2\n{}\n-->')
    with pytest.raises(ValueError, match="malformed"):
        state.parse("<!-- sdlc-state:v1 no newline -->")
    with pytest.raises(ValueError, match="not an object"):
        state.parse("<!-- sdlc-state:v1\n[1]\n-->")
    with pytest.raises(ValueError, match=r"state\.type"):
        state.parse('<!-- sdlc-state:v1\n{"version":1,"issue":1,"type":"epic","stages":[],'
                    '"cost":{"usd":0,"calls":[],"coder_seconds":0,"coder_usd":0}}\n-->')


def test_state_text_cannot_break_out_of_the_marker() -> None:
    st = make_state()
    st.data["quality"] = {"score": 5, "rounds": 1, "questions": ["--> <img src=x> | pipe"], "answers": []}
    body = state.render(st)
    marker_end = body.index("\n-->\n")
    assert "-->" not in body[: marker_end] and state.parse(body).data == st.data


def test_find_ignores_comments_not_written_by_the_owner() -> None:
    st = make_state(state.READY)
    comments = [Comment(1, "mallory", state.render(make_state(state.MERGED)), NOW),
                Comment(2, OWNER, state.render(st), NOW)]
    comment, found = state.find(comments)
    assert comment is not None and comment.id == 2 and found is not None and found.stage == state.READY
    assert state.find([]) == (None, None)


def test_summary_shows_every_section_sanitised() -> None:
    st = make_state(state.READY, state.FEASIBLE)
    st.data.update({
        "quality": {"score": 86, "rounds": 1, "questions": [], "answers": []},
        "triage": {"severity": "s2", "owner": "api"},
        "feasibility": {"suitable": False, "reasons": ["needs @ops <b>keys</b>"]},
        "coder": {"job_id": "j-7-1", "status": "running", "engine": "agy", "iterations": 2},
        "pr": {"number": 8, "head": HEAD}, "review": {"verdict": "approve", "head": HEAD, "rounds": 0},
        "gates": GREEN, "release": {"tag": "v0.2.0"},
    })
    st.escalate(state.ESC_NOT_SUITABLE, ["vendor | contract"], NOW)
    text = state.summary(st)
    for piece in ("86 / 100", "severity `s2`", "not suitable: needs `@ops` keys", "job `j-7-1`", "#8 at `bbbbbbb`",
                  "approve for `bbbbbbb`", "tdd-order: success", "`v0.2.0`", "vendor \\| contract", "Stages:"):
        assert piece in text
    assert st.escalation == state.ESC_NOT_SUITABLE and st.stage == state.FEASIBLE


def test_failure_counter_counts_per_action_and_resets_on_progress() -> None:
    st = make_state()
    assert st.record_failure("gate", "x") == 1
    assert st.record_failure("gate", "y") == 2
    assert st.record_failure("feasibility", "z") == 1
    st.enter(state.READY, NOW)
    assert st.data["failures"] is None


# ---------------------------------------------------------------------------
# machine
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stages, object_type, triaged, expected", [
    ((), "feature", False, Kind.GATE),
    ((), "bug", False, Kind.TRIAGE),
    ((), "bug", True, Kind.GATE),
    ((state.READY,), "feature", False, Kind.FEASIBILITY),
    ((state.READY,), "bug", False, Kind.TRIAGE),
    ((state.READY, state.FEASIBLE), "feature", False, Kind.DESIGN_TESTS),
    ((state.READY, state.FEASIBLE, state.TESTS_WRITTEN), "feature", False, Kind.START_CODER),
    ((state.MERGED,), "feature", False, Kind.RELEASE),
])
def test_issue_transitions(stages: tuple[str, ...], object_type: str, triaged: bool, expected: Kind) -> None:
    st = make_state(*stages, type_=object_type)
    if triaged:
        st.data["triage"] = {"severity": "s3", "owner": "api"}
    assert machine.next_action(ctx(st, object_type=object_type)).kind is expected


def test_start_coder_mode_follows_the_type() -> None:
    st = make_state(state.TESTS_WRITTEN, type_="bug")
    assert machine.next_action(ctx(st, object_type="bug")).mode == "bugfix"
    assert machine.next_action(ctx(make_state(state.TESTS_WRITTEN))).mode == "feature"


def test_refinement_alternates_answer_and_rescore() -> None:
    st = make_state(state.NEEDS_REFINEMENT)
    st.data["quality"] = {"score": 5, "rounds": 1, "questions": ["q"], "answers": []}
    assert machine.next_action(ctx(st)).kind is Kind.ANSWER
    st.data["quality"]["answers"] = ["a"]
    assert machine.next_action(ctx(st)).kind is Kind.RESCORE


def test_after_score_rounds() -> None:
    assert machine.after_score(80, 0).stage == state.READY
    assert machine.after_score(79, 0).stage == state.NEEDS_REFINEMENT
    assert machine.after_score(79, 1).stage == state.NEEDS_REFINEMENT
    assert machine.after_score(79, 2).escalate == state.ESC_REQUIREMENTS
    assert machine.after_feasibility(False).escalate == state.ESC_NOT_SUITABLE
    assert machine.after_coder("running") == machine.Outcome()
    assert machine.after_coder("timeout").escalate == state.ESC_BUILD_FAILED


def test_strangers_and_terminal_objects_get_no_action() -> None:
    assert machine.next_action(ctx(None, author="mallory")).kind is Kind.IGNORE
    assert machine.next_action(ctx(None, labels=frozenset({state.ESC_COST_CAP}))).kind is Kind.NOOP
    st = make_state(state.READY)
    st.escalate(state.ESC_REQUIREMENTS, ["x"], NOW)
    assert machine.next_action(ctx(st)).kind is Kind.NOOP
    assert machine.next_action(ctx(make_state(state.READY), is_open=False)).kind is Kind.NOOP
    assert machine.next_action(ctx(make_state(state.RELEASED), is_open=False)).kind is Kind.NOOP
    assert machine.next_action(ctx(make_state(state.RELEASED))).kind is Kind.CLOSE


def test_building_polls_until_the_deadline_and_needs_a_job() -> None:
    st = make_state(state.BUILDING)
    assert machine.next_action(ctx(st)).label == state.ESC_BUILD_FAILED
    st.data["coder"] = {"job_id": "j-7-1", "started_at": NOW, "attempts": 1}
    assert machine.next_action(ctx(st)).kind is Kind.POLL_CODER
    late = machine.next_action(ctx(st, now="2026-10-10T18:20:00Z"))
    assert late.kind is Kind.CODER_LOST                       # past deadline + 30 min: lost, restarted once
    st.data["coder"].update(status="lost", mode="feature")
    assert machine.next_action(ctx(st)).kind is Kind.START_CODER


def test_review_stage_decisions() -> None:
    st = make_state(state.IN_REVIEW)
    assert machine.next_action(ctx(st)).label == state.ESC_BUILD_FAILED                 # no PR
    assert machine.next_action(ctx(st, pr=pull(merged=True))).kind is Kind.MARK_MERGED
    assert machine.next_action(ctx(st, pr=pull(state="closed"))).kind is Kind.ESCALATE
    pending = {**GREEN, "e2e": "pending"}
    assert machine.next_action(ctx(st, pr=pull(), checks=pending)).kind is Kind.WAIT
    assert machine.next_action(ctx(st, pr=pull(), checks={**GREEN, "gitleaks": "failure"})).kind is Kind.ESCALATE
    assert machine.next_action(ctx(st, pr=pull(), checks=GREEN)).kind is Kind.REVIEW
    st.data["review"] = {"verdict": "approve", "head": "c" * 40, "rounds": 0}
    assert machine.next_action(ctx(st, pr=pull(), checks=GREEN)).kind is Kind.REVIEW    # old sha
    st.data["review"] = {"verdict": "approve", "head": HEAD, "rounds": 0}
    assert machine.next_action(ctx(st, pr=pull(), checks=GREEN)).kind is Kind.MERGE
    st.data["review"] = {"verdict": "request-changes", "head": HEAD, "rounds": 1}
    revise = machine.next_action(ctx(st, pr=pull(), checks=GREEN))
    assert revise.kind is Kind.START_CODER and revise.mode == "revise"
    st.data["coder"] = {"attempts": machine.MAX_CODER_ATTEMPTS}
    assert machine.next_action(ctx(st, pr=pull(), checks=GREEN)).reason.startswith("coder attempts exhausted")
    st.data["review"]["rounds"] = 2
    assert machine.next_action(ctx(st, pr=pull(), checks=GREEN)).label == state.ESC_REVIEW_FAILED


def test_maintenance_pr_decisions() -> None:
    maintenance_pr = pull(head_ref="chore/x", labels=("maintenance:test-repair",))
    m = {"kind": "pr", "object_type": "maintenance", "pr": maintenance_pr}
    red = {**GREEN, "test": "failure"}
    assert machine.next_action(ctx(None, **m, checks={**GREEN, "test": "pending"})).kind is Kind.WAIT
    assert machine.next_action(ctx(None, **m, checks=GREEN)).kind is Kind.NOOP      # never red: not ours
    triaged = make_state(type_="maintenance")
    triaged.data["ci_triage"] = {"cause": "stale-test", "head": "old"}
    assert machine.next_action(ctx(triaged, **m, checks=GREEN)).kind is Kind.REVIEW   # fixed by a push
    assert machine.next_action(ctx(None, **m, checks={**GREEN, "e2e": "failure"})).kind is Kind.ESCALATE
    assert machine.next_action(ctx(None, **m, checks=red, pr_touches_tests=True)).kind is Kind.ESCALATE
    assert machine.next_action(ctx(None, **m, checks=red, pr_touches_tests=False)).kind is Kind.CI_TRIAGE
    st = make_state(type_="maintenance")
    st.data["ci_triage"] = {"cause": "stale-test", "head": "old"}
    assert machine.next_action(ctx(st, **m, checks=red, pr_touches_tests=False)).kind is Kind.CI_TRIAGE
    st.data["ci_triage"]["head"] = HEAD
    action = machine.next_action(ctx(st, **m, checks=red, pr_touches_tests=False))
    assert action.kind is Kind.START_CODER and action.mode == "maintenance"
    st.data["ci_triage"]["cause"] = "real-bug"
    assert machine.next_action(ctx(st, **m, checks=red, pr_touches_tests=False)).label == state.ESC_BUILD_FAILED
    closed = {**m, "pr": pull(state="closed")}
    assert machine.next_action(ctx(None, **closed)).kind is Kind.NOOP
    for stage, kind in ((state.MERGED, Kind.RELEASE), (state.RELEASED, Kind.NOOP)):
        assert machine.next_action(ctx(make_state(stage, type_="maintenance"), **m)).kind is kind
    in_review = make_state(state.IN_REVIEW, type_="maintenance")
    in_review.data["review"] = {"verdict": "request-changes", "head": HEAD, "rounds": 1}
    assert machine.next_action(ctx(in_review, **m, checks=GREEN)).mode == "maintenance"
    building = make_state(state.BUILDING, type_="maintenance")
    building.data["coder"] = {"job_id": "j", "started_at": NOW}
    assert machine.next_action(ctx(building, **m)).kind is Kind.POLL_CODER


def test_caps_override_spending_steps() -> None:
    st = make_state()
    st.data["cost"]["usd"] = 3.0
    capped = machine.next_action(ctx(st))
    assert capped.kind is Kind.ESCALATE and capped.label == state.ESC_COST_CAP
    building = make_state(state.BUILDING)
    building.data["coder"] = {"job_id": "j", "started_at": NOW}
    building.data["cost"]["usd"] = 3.2
    assert machine.next_action(ctx(building)).cancel_coder
    halted = machine.next_action(ctx(make_state(), budget=Budget(usd_total=22.0)))
    assert halted.kind is Kind.HALT
    waiting = make_state(state.IN_REVIEW)
    assert machine.next_action(ctx(waiting, budget=Budget(usd_total=23), pr=pull(),
                                   checks={**GREEN, "e2e": "pending"})).kind is Kind.WAIT


def test_repeated_failures_escalate_with_the_phase_label() -> None:
    st = make_state()
    for _ in range(3):
        st.record_failure("gate", "bad json")
    action = machine.next_action(ctx(st))
    assert action.label == state.ESC_AGENT_ERROR and "failed 3 times" in action.reason
    building = make_state(state.BUILDING)
    building.data["coder"] = {"job_id": "j", "started_at": NOW}
    for _ in range(5):
        building.record_failure("poll-coder", "502")
    assert machine.next_action(ctx(building)).kind is Kind.POLL_CODER
    building.record_failure("poll-coder", "502")
    action = machine.next_action(ctx(building))
    assert action.label == state.ESC_BUILD_FAILED and action.cancel_coder


# ---------------------------------------------------------------------------
# gates
# ---------------------------------------------------------------------------

def runs(results: dict[str, str]) -> list[CheckRun]:
    return [CheckRun(n, "completed", r, NOW) if r != "pending" else CheckRun(n, "in_progress", None)
            for n, r in results.items()]


def review_comment(verdict: str, head: str, author: str = OWNER) -> Comment:
    return Comment(1, author, gates.render_review_marker(verdict, head) + "\nReview", NOW)


def verify(**kw: object) -> gates.GateResult:
    args = {"pr": pull(), "issue": Issue(7, "t", "b", OWNER, (), "open", NOW), "check_runs": runs(GREEN),
            "pr_comments": [review_comment("approve", HEAD)], "pr_files": ["app/web/src/a.tsx"],
            "object_usd": 0.1, "usd_cap": 1.0}
    return gates.verify_merge(**{**args, **kw})


def test_gate_passes_only_when_everything_holds() -> None:
    result = verify()
    assert result.passed and result.reasons == [] and result.checks == GREEN


@pytest.mark.parametrize("change, reason", [
    ({"check_runs": runs({**GREEN, "e2e": "failure"})}, "check e2e is failure"),
    ({"check_runs": runs({k: v for k, v in GREEN.items() if k != "gitleaks"})}, "check gitleaks is missing"),
    ({"check_runs": runs({**GREEN, "test": "pending"})}, "check test is pending"),
    ({"pr_comments": []}, "no review marker"),
    ({"pr_comments": [review_comment("approve", "c" * 40)]}, "review marker is for ccccccc"),
    ({"pr_comments": [review_comment("request-changes", HEAD)]}, "verdict is request-changes"),
    ({"pr_comments": [review_comment("approve", HEAD, author="mallory")]}, "no review marker"),
    ({"pr": pull(author="mallory")}, "PR author mallory"),
    ({"issue": Issue(7, "t", "b", "mallory", (), "open", NOW)}, "issue author mallory"),
    ({"object_usd": 1.0}, "cap"),
    ({"pr": pull(head_ref="feature/x")}, "not agent/*"),
    ({"pr": pull(base_ref="release")}, "base is release"),
    ({"pr": pull(state="closed")}, "not open"),
    ({"pr_files": ["app/web/a.ts", ".github/workflows/ci.yml"]}, "outside app/: .github/workflows/ci.yml"),
    ({"pr_files": ["app/../infra/main.tf"]}, "outside app/"),
    ({"pr_files": [f"scripts/{i}.py" for i in range(7)]}, "and 2 more"),
])
def test_gate_failures_name_their_reason(change: dict[str, object], reason: str) -> None:
    result = verify(**change)
    assert not result.passed and any(reason in r for r in result.reasons), result.reasons


def test_maintenance_label_allows_a_non_agent_branch_and_latest_review_wins() -> None:
    pr = pull(head_ref="chore/x", labels=("maintenance:test-repair",))
    comments = [review_comment("request-changes", HEAD), Comment(2, OWNER, "<!-- sdlc-review:v1 {bad -->", NOW),
                Comment(3, OWNER, '<!-- sdlc-review:v1 {"verdict":1} -->', NOW), review_comment("approve", HEAD)]
    assert verify(pr=pr, issue=None, pr_comments=comments).passed


def test_check_summary_uses_the_latest_completed_run_and_pending_wins() -> None:
    summary = gates.check_summary([
        CheckRun("test", "completed", "failure", "2026-10-10T12:00:00Z"),
        CheckRun("test", "completed", "success", "2026-10-10T12:05:00Z"),
        CheckRun("e2e", "in_progress", None), CheckRun("e2e", "completed", "success", NOW),
        CheckRun("lint", "completed", "failure", NOW),
    ])
    assert summary["test"] == "success" and summary["e2e"] == "pending" and summary["coverage"] == "missing"
    assert "lint" not in summary


# ---------------------------------------------------------------------------
# cost and release
# ---------------------------------------------------------------------------

def test_cost_prices_and_accounting() -> None:
    assert cost.token_usd(1_000_000, 0) == pytest.approx(0.25)
    assert cost.token_usd(0, 1_000_000) == pytest.approx(2.00)
    # Foundry hosted meter plus the Container Apps meter Azure bills for the same session (see cost.py)
    assert pytest.approx(0.10934 + 0.1224) == cost.HOSTED_VCPU_USD_PER_HOUR
    assert pytest.approx(0.01298 + 0.0144) == cost.HOSTED_GIB_USD_PER_HOUR
    assert pytest.approx(2 * 0.23174 + 4 * 0.02738, abs=1e-5) == cost.CODER_USD_PER_SECOND * 3600
    st = make_state()
    assert cost.record_call(st, "sdlc-req-gate", 900, 400) == pytest.approx(0.001025)
    added = cost.set_coder_spend(st, 3600, model_usd=0.05)
    assert added == pytest.approx(0.5730 + 0.05, abs=1e-4)
    assert st.usd == pytest.approx(0.001025 + 0.5730 + 0.05, abs=1e-4)
    assert cost.model_usd(st) == pytest.approx(0.001025)
    cost.set_coder_spend(st, -5, -1)
    assert st.data["cost"]["coder_seconds"] == 0 and st.data["cost"]["coder_model_usd"] == 0
    # the orchestrator: 1 vCPU and 2 GiB, each tick billed with the 2 minute idle tail
    assert cost.orchestrator_tick_usd(60) == pytest.approx(180 / 3600 * (0.23174 + 2 * 0.02738), abs=1e-5)
    assert cost.orchestrator_tick_usd(-1) == pytest.approx(120 / 3600 * 0.28650, abs=1e-5)


@pytest.mark.parametrize("tags, bump, expected", [
    ([], "minor", "v0.1.0"), ([], "patch", "v0.1.0"), (["v0.1.0"], "minor", "v0.2.0"),
    (["v0.1.0", "v0.2.0", "junk", "v0.10.0"], "patch", "v0.10.1"), (["v1.2.3"], "minor", "v1.3.0"),
])
def test_next_version(tags: list[str], bump: str, expected: str) -> None:
    assert release.next_version(tags, bump) == expected


def test_release_bump_kinds_and_idempotent_publish() -> None:
    assert release.bump_for("feature") == "minor" and release.bump_for("bug") == "patch"
    assert release.bump_for("maintenance") == "patch"
    with pytest.raises(ValueError, match="unknown bump"):
        release.next_version(["v0.1.0"], "major")
    gh = FakeGitHub(FakeClock())
    url = release.publish(gh, tag="v0.1.0", target_sha="m", name="n", notes="b")
    assert release.publish(gh, tag="v0.1.0", target_sha="m", name="n", notes="b") == url
    assert len(gh.releases) == 1


# ---------------------------------------------------------------------------
# lock
# ---------------------------------------------------------------------------

def test_lock_acquire_release_held_and_stale() -> None:
    clock = FakeClock()
    gh = FakeGitHub(clock)
    held = lock.acquire(gh, clock, "a")
    assert gh.branches[lock.LOCK_BRANCH] == held.sha and not held.took_over_stale
    with pytest.raises(lock.LockHeld):
        lock.acquire(gh, clock, "b")
    clock.advance(lock.STALE_AFTER_S + 1)
    taken = lock.acquire(gh, clock, "b")
    assert taken.took_over_stale
    assert lock.release(gh, held) is False          # no longer ours
    assert lock.release(gh, taken) is True and lock.LOCK_BRANCH not in gh.branches


def test_lock_errors_other_than_conflict_propagate() -> None:
    clock = FakeClock()
    gh = FakeGitHub(clock)
    gh.fail_on["create_branch"] = GitHubError(500, "boom")
    with pytest.raises(GitHubError):
        lock.acquire(gh, clock, "a")
    gh2 = FakeGitHub(clock)
    del gh2.branches["main"]
    with pytest.raises(GitHubError, match="main"):
        lock.acquire(gh2, clock, "a")


def test_lock_race_during_stale_takeover_reports_held() -> None:
    clock = FakeClock()
    gh = FakeGitHub(clock)
    gh.plant_lock(age_s=3600)
    original = gh.delete_branch

    def delete_and_lose_race(branch: str) -> None:
        original(branch)
        gh.branches[branch] = gh.branches["main"]   # another tick wins the re-create

    gh.delete_branch = delete_and_lose_race  # type: ignore[method-assign]
    with pytest.raises(lock.LockHeld):
        lock.acquire(gh, clock, "a")


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

def test_metrics_document_validates_against_the_schema_and_counts_gates() -> None:
    issue = Issue(7, "Filter", "b", OWNER, (), "closed", "2026-10-10T11:00:00Z", "2026-10-10T13:00:00Z")
    st = make_state(type_="bug")
    st.data["stages"] = [{"stage": state.READY, "at": "2026-10-10T11:05:00Z"},
                         {"stage": state.RELEASED, "at": "2026-10-10T12:00:00Z"}]
    st.data["triage"] = {"severity": "s2", "owner": "web"}
    st.data["gate_history"] = [{"head": "a", "results": {**GREEN, "e2e": "failure"}}, {"head": "b", "results": GREEN},
                               {"head": "c", "results": "corrupt"}]
    open_issue = Issue(9, "Open", "b", OWNER, (), "open", NOW)
    open_state = make_state(state.READY)
    doc = metrics.build([(open_issue, open_state), (issue, st)], NOW)
    jsonschema.Draft202012Validator(metrics.METRICS_SCHEMA).validate(doc)
    first = doc["issues"][0]
    assert first["number"] == 7 and first["resolution_seconds"] == 3600 and first["scenario"] == "d"
    assert first["stages"][0]["seconds"] == 3300 and first["stages"][1] == {
        "stage": state.RELEASED, "entered_at": "2026-10-10T12:00:00Z", "seconds": 0}
    assert doc["issues"][1]["stages"][0]["in_progress"] is True and doc["issues"][1]["outcome"] == "open"
    assert doc["gate_pass_rates"]["e2e"] == {"pass": 1, "fail": 1, "first_pass": 0, "first_fail": 1}
    assert doc["totals"] == {"usd": 0.0, "issues": 2, "released": 1, "escalated": 0, "orchestrator_usd": 0.0,
                             "ledger_usd": 0.0, "deferred": 0}
    assert first["gate_attempts"]["e2e"] == ["failure", "success"] and first["kind"] == "issue"
    with_orchestrator = metrics.build([(issue, st)], NOW, orchestrator_usd=0.2, floor_usd=0.1)
    assert with_orchestrator["totals"]["usd"] == 0.2
    assert metrics.build([(issue, st)], NOW, orchestrator_usd=0.2, floor_usd=0.5)["totals"]["usd"] == 0.5


def test_scenario_inference() -> None:
    assert metrics.infer_scenario(make_state()) == "a"
    refined = make_state()
    refined.data["quality"] = {"rounds": 1}
    assert metrics.infer_scenario(refined) == "b"
    unsuitable = make_state()
    unsuitable.escalate(state.ESC_NOT_SUITABLE, ["x"], NOW)
    assert metrics.infer_scenario(unsuitable) == "c"
    assert metrics.infer_scenario(make_state(type_="bug")) == "d"
    assert metrics.infer_scenario(make_state(type_="maintenance")) == "d-maintenance"


def test_metrics_publish_creates_the_branch_and_skips_unchanged_documents() -> None:
    clock = FakeClock()
    gh = FakeGitHub(clock)
    doc = metrics.build([], NOW)
    assert metrics.publish(gh, doc) == metrics.CHANGED and "metrics" in gh.branches
    assert metrics.publish(gh, {**doc, "generated_at": "2026-10-10T12:30:00Z"}) == metrics.UNCHANGED
    assert metrics.publish(gh, {**doc, "totals": {**doc["totals"], "usd": 0.01}}) == metrics.TOTALS
    gh.files[("metrics", "metrics.json")] = "not json"
    assert metrics.publish(gh, doc) == metrics.CHANGED
    assert json.loads(gh.files[("metrics", "metrics.json")])["version"] == 1
    empty = FakeGitHub(clock)
    del empty.branches["main"]
    with pytest.raises(RuntimeError, match="main"):
        metrics.publish(empty, doc)


def test_review_marker_matches_the_documented_shape_and_refuses_bad_values() -> None:
    expected = f'<!-- sdlc-review:v1 {{"verdict":"approve","head":"{HEAD}"}} -->'
    assert gates.render_review_marker("approve", HEAD) == expected
    for verdict, head in (("merge", HEAD), ("approve", "abc"), ("approve", HEAD + "-->")):
        with pytest.raises(ValueError, match="bad review marker"):
            gates.render_review_marker(verdict, head)
