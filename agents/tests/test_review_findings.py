"""
Independent review findings H2, M3, M4, M5 and the low items, each as observable behaviour.
"""

from __future__ import annotations

import json

import pytest
from conftest import World
from test_github import client, ok
from test_scenarios import A_BODY, open_stale_test_pr

from sdlc_agents import gates, state
from sdlc_agents.foundry import AgentRunError
from sdlc_agents.gates import REQUIRED_CHECKS
from sdlc_agents.ports import Budget, GitHubError


def starts(world: World) -> list[tuple[str, str | None]]:
    return [(body["job"]["job_id"], session) for _, body, session in world.foundry.hosted if body["op"] == "start"]


def to_building(world: World) -> int:
    world.coder.polls_to_finish = 10_000
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.BUILDING in world.gh.labels(n))
    return n


# ---------------------------------------------------------------------------
# H2: a lost start reply never spawns a second job
# ---------------------------------------------------------------------------

def test_ambiguous_start_is_not_resent_in_the_same_tick_or_the_next(world: World) -> None:
    world.coder.lose_next_start_reply = True
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: (world.gh.state_of(n).get("coder") or {}).get("status") == "start-unconfirmed")
    assert len(starts(world)) == 1
    world.tick()
    assert len(starts(world)) == 1                 # one tick later: still waiting


def test_lost_start_reply_is_resent_once_then_the_orphan_is_adopted_through_the_lease(world: World) -> None:
    gh, coder = world.gh, world.coder
    coder.lose_next_start_reply = True
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: coder.lease_refusals == 1)
    assert [job for job, _ in starts(world)] == [f"j-{n}-1", f"j-{n}-1"]      # the one counted resend
    assert gh.state_of(n)["coder"]["status"] == "lease-held"
    coder.run_orphans()                            # the first job, never polled, finishes on its own
    world.drive(lambda: state.RELEASED in gh.labels(n))
    assert len(starts(world)) == 2 and coder.sessions == 2 and len(gh.merges) == 1
    assert f"agent-lease/{n}" not in gh.branches


def test_unconfirmed_start_with_a_known_session_is_checked_by_status_not_resent(world: World) -> None:
    gh, coder = world.gh, world.coder
    n = to_building(world)
    coder.status_override = {"status": "failed", "reason": "interrupted", "elapsed_s": 60}
    world.tick()                                   # interrupted: the resume start is due
    coder.status_override = None
    # every attempt of the resume start times out: did it reach the coder? Unknown.
    world.foundry.hosted_fail_next = [AgentRunError("read timed out", transient=True, ambiguous=True)] * 4
    world.tick()
    assert gh.state_of(n)["coder"]["status"] == "start-unconfirmed"
    before = len(starts(world))
    world.tick()
    assert len(starts(world)) == before            # status first, not another start
    assert world.foundry.hosted[-1][1]["op"] == "status"


def test_start_refused_because_the_request_never_left_is_retried_in_the_tick(world: World) -> None:
    world.foundry.hosted_fail_next = [AgentRunError("connection refused", transient=True, ambiguous=False)]
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.BUILDING in world.gh.labels(n))
    assert world.gh.state_of(n)["coder"]["status"] == "running"


def test_orphan_that_outlives_the_deadline_is_swept_and_escalated(world: World) -> None:
    gh, coder = world.gh, world.coder
    world.budget = Budget(usd_cap_issue=10.0, usd_cap_total=50.0)    # jobs now cost what Azure bills
    coder.lose_next_start_reply = True
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: coder.lease_refusals == 1)
    world.clock.advance(3 * 3600)
    world.tick()
    assert state.ESC_BUILD_FAILED in gh.labels(n) and f"agent-lease/{n}" not in gh.branches
    assert "orphaned coder job" in gh.state_of(n)["escalation"]["reasons"][0]


def test_lease_is_released_on_every_terminal_coder_outcome(world: World) -> None:
    world.coder.outcomes = ["failed:max-iterations"]
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.ESC_BUILD_FAILED in world.gh.labels(n))
    assert f"agent-lease/{n}" not in world.gh.branches


# ---------------------------------------------------------------------------
# M3: no silent truncation
# ---------------------------------------------------------------------------

def test_pagination_raises_instead_of_truncating() -> None:
    full = [{"name": f"v{i}"} for i in range(100)]
    routes = {f"GET /tags?per_page=100&page={p}": ok(full, headers={"link": 'rel="next"'}) for p in range(1, 21)}
    gh, _, _ = client(routes)
    with pytest.raises(GitHubError, match="more than 2000"):
        gh.list_tags()


def test_truncated_tree_raises() -> None:
    gh, _, _ = client({"GET /git/trees/main?recursive=1": ok({"tree": [], "truncated": True})})
    with pytest.raises(GitHubError, match="truncated"):
        gh.list_tree("main")


def test_merge_is_refused_when_the_pr_file_list_may_be_incomplete(world: World) -> None:
    pr = open_stale_test_pr(world)
    world.gh.push("chore/update-home-heading", "chore: bulk", tuple(f"app/web/src/gen/{i}.ts" for i in range(3000)))
    world.gh.logs[(world.gh.branches["chore/update-home-heading"], "test")] = "FAIL app/web/src/pages/Home.test.tsx"
    world.drive(lambda: state.ESC_BUILD_FAILED in world.gh.labels(pr))
    assert world.gh.merges == []
    assert "3000 or more files" in world.gh.state_of(pr)["escalation"]["reasons"][0]


# ---------------------------------------------------------------------------
# M4: required checks that never arrive
# ---------------------------------------------------------------------------

def test_missing_required_check_escalates_after_three_hours_in_review(world: World) -> None:
    world.gh.ci = lambda _g, _n, _s: {k: "success" for k in REQUIRED_CHECKS if k != "e2e"}
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.IN_REVIEW in world.gh.labels(n))
    world.tick(5)
    assert state.ESC_BUILD_FAILED not in world.gh.labels(n)
    world.clock.advance(3 * 3600)
    world.tick()
    reason = world.gh.state_of(n)["escalation"]["reasons"][0]
    assert "e2e" in reason and "3 h" in reason


def test_maintenance_pr_waiting_on_checks_escalates_after_three_hours(world: World) -> None:
    world.gh.ci = lambda _g, _n, _s: dict.fromkeys(REQUIRED_CHECKS, "pending")
    pr = open_stale_test_pr(world)
    world.gh.ci = lambda _g, _n, _s: dict.fromkeys(REQUIRED_CHECKS, "pending")
    world.gh.run_ci(pr)
    world.tick()
    assert state.ESC_BUILD_FAILED not in world.gh.labels(pr)
    world.clock.advance(3 * 3600)
    world.tick()
    assert state.ESC_BUILD_FAILED in world.gh.labels(pr)


# ---------------------------------------------------------------------------
# M5: transient failures have an upper bound
# ---------------------------------------------------------------------------

def test_endless_transient_coder_errors_escalate_agent_error_after_24_ticks(world: World) -> None:
    n = to_building(world)
    world.budget = Budget(usd_cap_issue=10.0, usd_cap_total=50.0)    # jobs now cost what Azure bills
    world.foundry.hosted_fail_next = [AgentRunError("HTTP 503", transient=True)] * 100_000
    reports = world.tick(23)
    assert {o.result for r in reports for o in r.objects if o.number == n} == {"deferred"}
    world.tick()
    assert state.ESC_AGENT_ERROR in world.gh.labels(n)
    assert "24 consecutive ticks" in world.gh.state_of(n)["escalation"]["reasons"][0]


def test_transient_streak_resets_after_a_good_tick_and_needs_no_state_comment(world: World) -> None:
    rate_limited = AgentRunError("HTTP 429", transient=True)
    world.foundry.errors["sdlc-req-gate"] = rate_limited
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    world.tick(10)
    assert world.gh.comments[n] == []
    assert json.loads(world.gh.files[("metrics", "metrics.json")])["deferrals"] == {str(n): 10}
    del world.foundry.errors["sdlc-req-gate"]
    world.tick()
    assert json.loads(world.gh.files[("metrics", "metrics.json")])["deferrals"] == {}


# ---------------------------------------------------------------------------
# Low items
# ---------------------------------------------------------------------------

def test_a_re_review_of_the_same_sha_updates_the_one_marker_comment(world: World) -> None:
    gh, foundry = world.gh, world.foundry
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: (gh.state_of(n).get("review") or {}).get("verdict") == "approve")
    pr = gh.state_of(n)["pr"]["number"]
    head = gh.state_of(n)["pr"]["head"]
    # a stale request-changes marker for the same sha, as left by an earlier review of it
    gh.comments[pr] = [c for c in gh.comments[pr] if not c.body.startswith(gates.REVIEW_MARKER_PREFIX)]
    gh.add_comment_as(pr, "stevengonsalvez", gates.render_review_marker("request-changes", head) + "\nold")
    st = gh.state_of(n)
    st_comment = next(c for c in gh.comments[n] if c.body.startswith("<!-- sdlc-state:v1"))
    st["review"] = None
    from sdlc_agents.state import State, render
    gh.update_comment(st_comment.id, render(State(st)))
    world.tick()
    markers = [b for b in gh.bodies(pr) if b.startswith(gates.REVIEW_MARKER_PREFIX)]
    assert len(markers) == 1 and '"verdict":"approve"' in markers[0]
    assert len(foundry.agent_calls("sdlc-reviewer")) == 2


def test_a_cancelled_check_waits_one_tick_before_it_counts_as_a_failure(world: World) -> None:
    world.gh.ci = lambda _g, _n, _s: {**dict.fromkeys(REQUIRED_CHECKS, "success"), "e2e": "cancelled"}
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.IN_REVIEW in world.gh.labels(n))
    report = world.tick()[0]
    assert [o.action for o in report.objects if o.number == n] == ["wait"]
    world.tick()
    assert state.ESC_BUILD_FAILED in world.gh.labels(n)


def test_a_cancelled_check_that_is_rerun_green_merges(world: World) -> None:
    runs = {"count": 0}

    def ci(_g, _n, _s):  # type: ignore[no-untyped-def]
        runs["count"] += 1
        return {**dict.fromkeys(REQUIRED_CHECKS, "success"), "e2e": "cancelled" if runs["count"] == 1 else "success"}

    world.gh.ci = ci
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.IN_REVIEW in world.gh.labels(n))
    world.tick()
    world.gh.run_ci(world.gh.state_of(n)["pr"]["number"])      # the rerun lands green
    world.drive(lambda: state.RELEASED in world.gh.labels(n))


def test_no_coder_start_with_less_than_a_cent_left_under_the_cap(world: World) -> None:
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.TESTS_WRITTEN in world.gh.labels(n))
    spent = world.gh.state_of(n)["cost"]["usd"]
    world.tick(budget=Budget(usd_cap_issue=spent + 0.005))
    assert state.ESC_COST_CAP in world.gh.labels(n) and not world.foundry.hosted


def test_fork_pr_on_the_agent_branch_name_is_never_adopted_or_merged(world: World) -> None:
    gh = world.gh
    world.coder.report_pr = False
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    fork = gh.open_pr("Fork", "x", f"agent/issue-{n}", [], author="stevengonsalvez", head_repo="mallory/fork")
    world.drive(lambda: state.RELEASED in gh.labels(n))
    assert gh.state_of(n)["pr"]["number"] != fork and all(m[0] != fork for m in gh.merges)


def test_gate_refuses_a_pr_from_another_repository() -> None:
    from test_core import pull, verify

    result = verify(pr=pull(head_repo="mallory/fork"))
    assert not result.passed and any("head repository" in r for r in result.reasons)


def test_fake_pull_files_are_capped_like_github(world: World) -> None:
    pr = world.gh.open_pr("Big", "x", "chore/big", [("chore: big", tuple(f"app/{i}.ts" for i in range(3500)))])
    assert len(world.gh.list_pull_files(pr)) == 3000


def test_coder_contract_words_from_w2b_are_kept_not_replaced(world: World) -> None:
    n = to_building(world)
    world.coder.status_override = {"status": "failed", "reason": "sandbox-unavailable", "engine": "agy-unrestricted",
                                   "phase": "setup", "elapsed_s": 30}
    world.tick()
    st = world.gh.state_of(n)
    assert st["coder"]["engine"] == "agy-unrestricted"
    assert st["escalation"]["reasons"][0] == "coder failed (sandbox-unavailable) in phase setup"


def test_lease_error_on_start_counts_as_a_start_failure(world: World) -> None:
    world.coder.start_status = "failed"
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.ESC_BUILD_FAILED in world.gh.labels(n))
    assert "start-coder failed 3 times" in world.gh.state_of(n)["escalation"]["reasons"][0]
