"""
Coder v11 failure reasons and what the orchestrator does with each (nothing was pushed in any of them):
- engine-unavailable (agy missing or without a token in that sandbox): a new job, new id and session,
  up to the attempt limit, then escalated:build-failed;
- internal-error (the coder crashed): one new job, then escalated:build-failed;
- invalid-allowed-paths (maintenance paths match nothing at the head): the ci-triage file validation
  runs again on the current head and one new job gets the corrected paths, else escalated:agent-error;
- interrupted, where the resumed start lands in a session that no longer knows the job (lease-held):
  a new attempt instead of a resume.
Every failed job still leaves its coder-log comment.
"""

from __future__ import annotations

from conftest import World
from test_scenarios import A_BODY, open_stale_test_pr

from sdlc_agents import cost, machine, state
from sdlc_agents.ports import Budget

BRANCH = "chore/update-home-heading"


def starts(world: World) -> list[tuple[str, str | None]]:
    return [(body["job"]["job_id"], session) for _, body, session in world.foundry.hosted if body["op"] == "start"]


def log_markers(world: World, n: int) -> list[str]:
    return [b.splitlines()[0] for b in world.gh.bodies(n) if b.startswith("<!-- sdlc-coder-log:v1 ")]


def test_engine_unavailable_starts_a_new_job_in_a_fresh_session(world: World) -> None:
    gh = world.gh
    world.coder.outcomes = ["failed:engine-unavailable"]
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.RELEASED in gh.labels(n))
    assert starts(world) == [(f"j-{n}-1", None), (f"j-{n}-2", None)]
    assert log_markers(world, n) == [f"<!-- sdlc-coder-log:v1 j-{n}-1 -->"]


def test_engine_unavailable_every_time_escalates_at_the_attempt_limit(world: World) -> None:
    gh = world.gh
    world.budget = Budget(usd_cap_issue=10.0, usd_cap_total=50.0)    # jobs now cost what Azure bills
    world.coder.outcomes = ["failed:engine-unavailable"] * (machine.MAX_CODER_ATTEMPTS + 2)
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.ESC_BUILD_FAILED in gh.labels(n), max_ticks=80)
    assert len(starts(world)) == machine.MAX_CODER_ATTEMPTS
    assert "engine-unavailable" in gh.state_of(n)["escalation"]["reasons"][0]
    assert len(log_markers(world, n)) == machine.MAX_CODER_ATTEMPTS


def test_internal_error_gets_one_new_attempt_then_escalates(world: World) -> None:
    gh = world.gh
    world.coder.outcomes = ["failed:internal-error", "failed:internal-error"]
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.ESC_BUILD_FAILED in gh.labels(n))
    assert [job for job, _ in starts(world)] == [f"j-{n}-1", f"j-{n}-2"]
    assert "internal-error" in gh.state_of(n)["escalation"]["reasons"][0]
    assert len(log_markers(world, n)) == 2


def test_invalid_allowed_paths_are_revalidated_on_the_current_head(world: World) -> None:
    gh, foundry = world.gh, world.foundry
    world.coder.polls_to_finish = 3
    world.coder.outcomes = ["failed:invalid-allowed-paths"]
    pr = open_stale_test_pr(world)
    world.drive(lambda: state.BUILDING in gh.labels(pr))
    # the owner moved the test while the job ran: the old path matches nothing at the head
    del gh.files[(BRANCH, "app/web/tests/home-page.test.tsx")]
    gh.files[(BRANCH, "app/web/test/home-page.test.tsx")] = "test"
    world.drive(lambda: state.RELEASED in gh.labels(pr))

    jobs = [body["job"] for _, body, _ in foundry.hosted if body["op"] == "start"]
    assert [j["allowed_paths"] for j in jobs] == [["app/web/tests/home-page.test.tsx"],
                                                  ["app/web/test/home-page.test.tsx"]]
    assert len(foundry.agent_calls("sdlc-ci-triage")) == 1
    assert log_markers(world, pr) == [f"<!-- sdlc-coder-log:v1 j-pr{pr}-1 -->"]


def test_invalid_allowed_paths_that_cannot_be_corrected_escalate_agent_error(world: World) -> None:
    gh = world.gh
    world.coder.outcomes = ["failed:invalid-allowed-paths"]
    pr = open_stale_test_pr(world)
    world.drive(lambda: state.ESC_AGENT_ERROR in gh.labels(pr))
    assert len(starts(world)) == 1
    assert "invalid-allowed-paths" in gh.state_of(pr)["escalation"]["reasons"][0]
    assert len(log_markers(world, pr)) == 1


def test_interrupted_job_whose_session_forgot_it_is_restarted_as_a_new_attempt(world: World) -> None:
    gh, coder = world.gh, world.coder
    coder.polls_to_finish = 10_000
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.BUILDING in gh.labels(n))
    coder.status_override = {"job_id": f"j-{n}-1", "status": "failed", "reason": "interrupted", "elapsed_s": 600}
    world.tick()
    coder.status_override = None
    coder.wipe_session("sess-1")              # the resume lands in a sandbox that never saw the job
    coder.polls_to_finish = 1
    world.drive(lambda: state.RELEASED in gh.labels(n))
    assert starts(world) == [(f"j-{n}-1", None), (f"j-{n}-1", "sess-1"), (f"j-{n}-2", None)]
    assert f"agent-lease/{n}" not in gh.branches


def test_a_finished_coder_job_is_charged_its_idle_tail(world: World) -> None:
    # Azure bills the session until it idles out; the 2.6x gap between the ledger and the invoice
    # (1.86 vs 4.80 USD on 2026-10-10) was these tails plus the second Container Apps meter.
    gh = world.gh
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.RELEASED in gh.labels(n))
    cost_block = gh.state_of(n)["cost"]
    assert cost_block["coder_seconds"] >= cost.CODER_IDLE_S
    assert cost_block["coder_usd"] >= cost.CODER_IDLE_S * cost.CODER_USD_PER_SECOND - 1e-6
