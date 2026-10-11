"""
Crash and partial-failure behaviour: a step that fails half way must leave nothing half done.
Each test injects a failure between two side effects and asserts the pipeline still converges with
no duplicate comment, merge, release or coder job, and with every model call billed.
"""

from __future__ import annotations

import json

import pytest
from conftest import World
from test_scenarios import A_BODY, B_BODY, LOW_SCORE, open_stale_test_pr

from sdlc_agents import cost, gates, metrics, state
from sdlc_agents.foundry import AgentRunError
from sdlc_agents.gates import REQUIRED_CHECKS
from sdlc_agents.ports import Budget, CheckRun

NO_QUESTIONS = {**LOW_SCORE, "questions": []}   # fails validation: below 80 needs questions


def review_comments(world: World, pr: int) -> list[str]:
    return [b for b in world.gh.bodies(pr) if b.startswith(gates.REVIEW_MARKER_PREFIX)]


def test_failed_rescore_keeps_the_answers_and_escalates_without_re_asking(world: World) -> None:
    gh, foundry = world.gh, world.foundry
    foundry.script("sdlc-req-gate", LOW_SCORE, *[NO_QUESTIONS] * 6)
    n = gh.open_issue("Make the parcel tracker better", B_BODY)

    world.tick(8)

    assert len(foundry.agent_calls("sdlc-product-owner")) == 1
    assert len(foundry.agent_calls("sdlc-req-gate")) == 7      # 1 + 3 steps x (answer + repair)
    st = gh.state_of(n)
    assert st["escalation"]["label"] == state.ESC_AGENT_ERROR
    assert "rescore failed 3 times" in st["escalation"]["reasons"][0]
    assert st["quality"]["answers"] and st["quality"]["rounds"] == 1 and not st["quality"]["history"]
    assert len(st["cost"]["calls"]) == 8          # every call billed, including the six rejected ones
    assert max(len(b) for b in gh.bodies(n)) < 20_000


def test_merge_that_succeeds_while_saving_fails_still_releases_once(world: World) -> None:
    gh = world.gh
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: (gh.state_of(n).get("review") or {}).get("verdict") == "approve")
    gh.fail_once["update_comment"] = 2            # the step's save and the failure record both fail

    world.tick()
    assert len(gh.merges) == 1 and gh.issues[n]["state"] == "closed"   # auto-closed by "Closes #N"
    assert gh.state_of(n)["stages"][-1]["stage"] == state.IN_REVIEW

    world.drive(lambda: state.RELEASED in gh.labels(n))
    world.tick(2)
    assert len(gh.merges) == 1 and len(gh.releases) == 1
    assert [s["stage"] for s in gh.state_of(n)["stages"]][-2:] == [state.MERGED, state.RELEASED]


def test_lost_review_comment_means_no_recorded_verdict_and_a_clean_retry(world: World) -> None:
    gh, foundry = world.gh, world.foundry
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.IN_REVIEW in gh.labels(n))
    gh.fail_once["create_comment"] = 1

    report = world.tick()[0]
    st = gh.state_of(n)
    # a 502 on the comment is transient: the step is deferred, nothing is recorded or counted ...
    assert [o.result for o in report.objects if o.number == n] == ["deferred"]
    assert st["review"] is None and st["failures"] is None
    # ... except the spend: the review call is billed although its step was rolled back
    assert [c["agent"] for c in st["cost"]["calls"]][-1] == "sdlc-reviewer" and len(st["cost"]["calls"]) == 4

    world.drive(lambda: state.RELEASED in gh.labels(n))
    assert len(foundry.agent_calls("sdlc-reviewer")) == 2
    assert len(review_comments(world, st["pr"]["number"])) == 1 and len(gh.merges) == 1


def test_coder_start_whose_reply_is_lost_never_runs_a_second_job(world: World) -> None:
    gh, foundry, coder = world.gh, world.foundry, world.coder
    coder.lose_next_start_reply = True
    n = gh.open_issue("Show the estimated delivery date", A_BODY)

    world.drive(lambda: coder.lease_refusals == 1)     # the one resend is refused: the first job holds the lease
    coder.run_orphans()
    world.drive(lambda: state.RELEASED in gh.labels(n))

    starts = [body["job"]["job_id"] for _, body, _ in foundry.hosted if body["op"] == "start"]
    assert starts == [f"j-{n}-1", f"j-{n}-1"]
    assert len([r for r in coder.by_session.values() if r["job"]["job_id"] == f"j-{n}-1"]) == 1
    assert gh.state_of(n)["coder"]["attempts"] == 1


def test_a_fork_run_on_the_same_sha_cannot_turn_a_red_gate_green(world: World) -> None:
    gh = world.gh
    gh.ci = lambda _g, _n, _s: {**dict.fromkeys(REQUIRED_CHECKS, "success"), "tdd-order": "pending"}
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.IN_REVIEW in gh.labels(n))
    pr = gh.state_of(n)["pr"]["number"]
    head = gh.state_of(n)["pr"]["head"]
    gh.check_runs[head] = [r for r in gh.check_runs[head] if r.name != "tdd-order"] + [
        CheckRun("tdd-order", "completed", "failure", "2026-10-10T13:00:00Z", (pr,)),
        CheckRun("tdd-order", "completed", "success", "2026-10-10T14:00:00Z", ()),   # a fork PR's run
    ]
    world.drive(lambda: state.ESC_BUILD_FAILED in gh.labels(n))
    assert gh.merges == [] and "tdd-order" in gh.state_of(n)["escalation"]["reasons"][0]


def test_issue_closed_by_hand_while_building_cancels_the_coder(world: World) -> None:
    gh, foundry = world.gh, world.foundry
    world.coder.polls_to_finish = 10_000
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.BUILDING in gh.labels(n))
    gh.close_issue(n)
    world.tick()
    assert foundry.hosted[-1][1]["op"] == "cancel"
    assert gh.state_of(n)["escalation"]["label"] == state.ESC_BUILD_FAILED


def test_maintenance_pr_that_was_never_red_is_left_alone(world: World) -> None:
    gh = world.gh
    pr = gh.open_pr("Tidy", "copy", "chore/tidy", [("chore: tidy", ("app/web/src/a.tsx",))],
                    labels=("maintenance:test-repair",))
    reports = world.tick(2)
    assert world.foundry.calls == [] and gh.merges == []
    assert [o.action for r in reports for o in r.objects if o.number == pr] == ["noop", "noop"]


def test_incomplete_model_answers_are_billed(world: World) -> None:
    gh, foundry = world.gh, world.foundry
    foundry.errors["sdlc-req-gate"] = AgentRunError("not completed: max_output_tokens", 500, 4000)
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.tick()
    st = gh.state_of(n)
    assert st["cost"]["calls"] == [{"agent": "sdlc-req-gate", "in": 500, "out": 4000, "usd": 0.008125}]
    assert st["failures"]["count"] == 1


def test_merged_work_is_released_with_plain_notes_once_the_total_cap_is_hit(world: World) -> None:
    gh, foundry = world.gh, world.foundry
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.MERGED in gh.labels(n))
    world.tick(budget=Budget(usd_cap_total=0.001))
    assert state.RELEASED in gh.labels(n)
    assert not foundry.agent_calls("sdlc-release-notes")
    assert gh.releases[0]["body"].startswith("### Highlights\n- feat: Show the estimated delivery date")


def test_total_spend_never_shrinks_when_an_object_drops_out_of_view(world: World) -> None:
    gh = world.gh
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.RELEASED in gh.labels(n))
    world.tick()
    before = json.loads(gh.files[("metrics", "metrics.json")])["totals"]
    gh.issues[n]["labels"] = []                       # a human strips the pipeline labels
    report = world.tick()[0]
    after = json.loads(gh.files[("metrics", "metrics.json")])["totals"]
    assert before["usd"] > 0
    assert after["usd"] == pytest.approx(before["usd"] + report.orchestrator_usd, abs=1e-6)
    assert after["orchestrator_usd"] == pytest.approx(before["orchestrator_usd"] + report.orchestrator_usd, abs=1e-6)
    ledger = metrics.previous_totals(gh)
    assert ledger is not None and ledger.usd == after["usd"]


def test_previous_totals_are_empty_when_absent_and_unknown_when_corrupt(world: World) -> None:
    assert metrics.previous_totals(world.gh) == metrics.Ledger()
    world.gh.branches["metrics"] = world.gh.branches["main"]
    assert metrics.previous_totals(world.gh) == metrics.Ledger()          # branch but no file yet
    for corrupt in ("{not json", "[1]", '{"totals": {}}', '{"totals": {"usd": -1}}',
                    '{"totals": {"usd": 1}, "issues": [{"number": 1, "cost": {"usd": true}}]}'):
        world.gh.files[("metrics", "metrics.json")] = corrupt
        assert metrics.previous_totals(world.gh) is None, corrupt


def test_maintenance_repair_survives_a_lost_coder_reply(world: World) -> None:
    gh = world.gh
    world.coder.lose_next_start_reply = True
    pr = open_stale_test_pr(world)
    world.drive(lambda: world.coder.lease_refusals == 1)
    world.coder.run_orphans()
    world.drive(lambda: state.RELEASED in gh.labels(pr))
    assert len(gh.merges) == 1 and f"agent-lease/{pr}" not in gh.branches


def test_call_list_is_bounded_but_spend_and_counts_are_kept() -> None:
    st = state.State.new(1, "feature", None)
    for _ in range(45):
        cost.record_call(st, "sdlc-req-gate", 1000, 100)
    calls = st.data["cost"]["calls"]
    assert len(calls) == cost.MAX_CALL_ENTRIES and calls[0]["agent"] == cost.EARLIER
    assert cost.call_count(st) == 45
    assert st.usd == pytest.approx(45 * cost.token_usd(1000, 100))


def test_check_summary_falls_back_to_all_runs_when_none_are_tied_to_the_pr() -> None:
    runs = [CheckRun(n, "completed", "success", "2026-10-10T12:00:00Z") for n in REQUIRED_CHECKS]
    assert gates.all_green(gates.check_summary(runs, 5))


# ---------------------------------------------------------------------------
# Step error paths
# ---------------------------------------------------------------------------

def test_designed_test_that_would_overwrite_an_existing_file_is_rejected(world: World) -> None:
    gh = world.gh
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    gh.files[("main", f"app/web/tests/issue-{n}.test.tsx")] = "existing test"
    world.tick(3)
    st = gh.state_of(n)
    assert "already exists on main" in st["failures"]["error"] and not world.foundry.hosted
    assert "already exists on main" in world.foundry.agent_calls("sdlc-test-designer")[1]   # re-asked once


def test_coder_pr_is_found_by_branch_and_a_strangers_pr_is_never_picked(world: World) -> None:
    gh = world.gh
    world.coder.report_pr = False
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    decoy = gh.open_pr("Decoy", "x", "mallory-fork", [], author="mallory")
    gh.pulls[decoy]["head_ref"] = f"agent/issue-{n}"   # a fork PR whose branch has the agent's name
    world.drive(lambda: state.RELEASED in gh.labels(n))
    assert gh.state_of(n)["pr"]["number"] != decoy and len(gh.merges) == 1


def test_coder_pr_missing_after_success_is_a_recorded_failure(world: World) -> None:
    gh = world.gh
    world.coder.report_pr = False
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.BUILDING in gh.labels(n))
    world.coder.github = None  # type: ignore[assignment]  # the coder can no longer open a PR
    world.coder.status_override = {"job_id": "x", "status": "succeeded", "elapsed_s": 60}
    world.tick()
    assert "no open PR" in gh.state_of(n)["failures"]["error"]


def test_reviewer_answering_for_another_sha_is_rejected_then_retried(world: World) -> None:
    gh, foundry = world.gh, world.foundry
    foundry.script("sdlc-reviewer", {"verdict": "approve", "head": "abcdef1", "findings": [], "summary": "s"})
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.RELEASED in gh.labels(n))
    assert len(foundry.agent_calls("sdlc-reviewer")) == 2 and len(gh.merges) == 1


def test_merge_gate_failure_blocks_the_merge_and_escalates_after_retries(world: World) -> None:
    gh = world.gh
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: (gh.state_of(n).get("review") or {}).get("verdict") == "approve")
    pr = gh.state_of(n)["pr"]["number"]
    gh.comments[pr] = [c for c in gh.comments[pr] if not c.body.startswith(gates.REVIEW_MARKER_PREFIX)]
    world.drive(lambda: state.ESC_BUILD_FAILED in gh.labels(n))
    assert gh.merges == []
    assert "merge failed 3 times" in gh.state_of(n)["escalation"]["reasons"][0]
    assert "no review marker" in gh.state_of(n)["escalation"]["reasons"][0]


def test_released_issue_that_was_reopened_is_closed_again(world: World) -> None:
    gh = world.gh
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.RELEASED in gh.labels(n))
    gh.issues[n]["state"] = "open"
    report = world.tick()[0]
    assert gh.issues[n]["state"] == "closed"
    assert [o.action for o in report.objects if o.number == n] == ["close"]


def test_coder_that_refuses_to_start_or_reports_nonsense_is_bounded(world: World) -> None:
    gh = world.gh
    world.coder.start_status = "failed"
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.ESC_BUILD_FAILED in gh.labels(n))
    assert "start-coder failed 3 times" in gh.state_of(n)["escalation"]["reasons"][0]

    other = gh.open_issue("Second", A_BODY)
    world.coder.start_status = "running"
    world.coder.status_override = {"status": "confused"}
    world.drive(lambda: state.ESC_BUILD_FAILED in gh.labels(other))
    assert "poll-coder failed 6 times" in gh.state_of(other)["escalation"]["reasons"][0]


def test_cancel_failure_is_reported_and_the_escalation_still_lands(world: World) -> None:
    gh = world.gh
    world.coder.polls_to_finish = 10_000
    world.coder.cancel_error = AgentRunError("session gone")
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.BUILDING in gh.labels(n))
    world.clock.advance(7 * 3600)
    report = world.tick()[0]
    assert any("cancel failed" in e for e in report.errors)
    assert gh.state_of(n)["coder"]["status"] == "lost"       # a failed cancel does not block the loss


# ---------------------------------------------------------------------------
# Coder contract (w2b): interrupted jobs resume, model spend counts, files outside app/ never merge
# ---------------------------------------------------------------------------

def test_interrupted_coder_job_is_resumed_with_the_same_job_and_session(world: World) -> None:
    gh, foundry, coder = world.gh, world.foundry, world.coder
    coder.polls_to_finish = 10_000
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.BUILDING in gh.labels(n))
    coder.status_override = {"job_id": f"j-{n}-1", "status": "failed", "reason": "interrupted", "elapsed_s": 600}
    world.tick()
    assert gh.state_of(n)["coder"]["status"] == "starting"
    coder.status_override = None
    coder.polls_to_finish = 1
    world.drive(lambda: state.RELEASED in gh.labels(n))
    starts = [(body["job"]["job_id"], session) for _, body, session in foundry.hosted if body["op"] == "start"]
    assert starts == [(f"j-{n}-1", None), (f"j-{n}-1", "sess-1")]
    assert gh.state_of(n)["coder"]["resumes"] == 1 and coder.sessions == 1


def test_coder_interrupted_too_often_is_escalated(world: World) -> None:
    gh = world.gh
    world.coder.polls_to_finish = 10_000
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.BUILDING in gh.labels(n))
    world.coder.status_override = {"status": "failed", "reason": "interrupted", "elapsed_s": 60}
    world.drive(lambda: state.ESC_BUILD_FAILED in gh.labels(n), max_ticks=20)
    assert "interrupted 4 times" in gh.state_of(n)["escalation"]["reasons"][0]


def test_coder_failure_reason_and_model_spend_are_recorded(world: World) -> None:
    gh = world.gh
    world.coder.polls_to_finish = 10_000
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.BUILDING in gh.labels(n))
    world.coder.status_override = {"status": "failed", "reason": "tests-not-red", "phase": "tests",
                                   "detail": "all designed tests passed on main", "elapsed_s": 120,
                                   "cost": {"model_usd": 0.03, "input_tokens": 1, "output_tokens": 1}}
    world.tick()
    st = gh.state_of(n)
    assert st["escalation"]["reasons"][:2] == ["coder failed (tests-not-red) in phase tests",
                                               "all designed tests passed on main"]
    assert st["cost"]["coder_model_usd"] == 0.03
    assert st["cost"]["usd"] == pytest.approx(cost.model_usd(state.State(st)) + st["cost"]["coder_usd"] + 0.03)


def test_coder_job_budget_is_what_is_left_under_the_cap(world: World) -> None:
    gh, foundry = world.gh, world.foundry
    foundry.usage = (1_400_000, 1_250_000)      # 2.85 USD per call, 0.15 USD left under the 3 USD cap
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    gh.issues[n]["labels"] = ["type:feature"]
    st = state.State.new(n, "feature", "a")
    st.enter(state.TESTS_WRITTEN, "2026-10-10T11:00:00Z")
    cost.record_call(st, "sdlc-test-designer", 1_400_000, 1_250_000)
    gh.add_comment_as(n, "stevengonsalvez", state.render(st))
    tests = '{"tests":[{"path":"app/a.test.ts","content":"vitest"}]}'
    gh.add_comment_as(n, "stevengonsalvez", f"<!-- sdlc-tests:v1\n{tests}\n-->")
    world.tick()
    job = next(body["job"] for _, body, _ in foundry.hosted if body["op"] == "start")
    assert job["max_model_usd"] == pytest.approx(0.15)


def test_maintenance_pr_that_also_edits_ci_is_refused_at_the_merge_gate(world: World) -> None:
    gh = world.gh
    pr = open_stale_test_pr(world)
    gh.push("chore/update-home-heading", "ci: relax the gate", (".github/workflows/ci.yml",))
    gh.logs[(gh.branches["chore/update-home-heading"], "test")] = "FAIL app/web/src/pages/Home.test.tsx"
    world.drive(lambda: state.ESC_BUILD_FAILED in gh.labels(pr))
    assert gh.merges == []
    reason = gh.state_of(pr)["escalation"]["reasons"][0]
    assert reason == "merge refused: PR changes files outside app/: .github/workflows/ci.yml"


def test_app_only_pr_passes_the_file_scope_rule(world: World) -> None:
    pr = open_stale_test_pr(world)
    world.drive(lambda: state.RELEASED in world.gh.labels(pr))
    assert world.gh.list_pull_files(pr) == ["app/web/src/pages/Home.tsx", "app/web/tests/home-page.test.tsx"]
