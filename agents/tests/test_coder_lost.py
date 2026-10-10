"""
A coder job whose sandbox session is gone (status answers HTTP 400/404 session_not_accessible twice
in a row), or that is still not finished 30 minutes past its deadline whatever its polls say, is
lost: the lease is released, `coder-session-lost` is recorded in the state and metrics, and the job
restarts once under a new job id on the same branch (counting an attempt). A second loss escalates
build-failed with reason coder-session-lost.
"""

from __future__ import annotations

from conftest import World
from test_scenarios import A_BODY, metrics_doc, open_stale_test_pr

from sdlc_agents import machine, state
from sdlc_agents.ports import Budget


def start_jobs(world: World) -> list[dict]:
    return [body["job"] for _, body, _ in world.foundry.hosted if body["op"] == "start"]


def test_a_lost_maintenance_session_restarts_once_on_the_same_pr_branch(world: World) -> None:
    gh, coder = world.gh, world.coder
    pr = open_stale_test_pr(world)
    coder.lost_jobs = {f"j-pr{pr}-1"}
    world.drive(lambda: state.RELEASED in gh.labels(pr))

    jobs = start_jobs(world)
    assert [j["job_id"] for j in jobs] == [f"j-pr{pr}-1", f"j-pr{pr}-2"]
    assert {j["branch"] for j in jobs} == {"chore/update-home-heading"} and jobs[1]["mode"] == "maintenance"
    st = gh.state_of(pr)
    assert st["coder_sessions_lost"] == 1 and st["coder"]["attempts"] == 2
    assert f"agent-lease/{pr}" not in gh.branches
    assert metrics_doc(world)["issues"][0]["coder_sessions_lost"] == 1


def test_a_second_lost_session_escalates_build_failed(world: World) -> None:
    gh = world.gh
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.coder.lost_jobs = {f"j-{n}-1", f"j-{n}-2"}
    world.drive(lambda: state.ESC_BUILD_FAILED in gh.labels(n))

    jobs = start_jobs(world)
    assert [j["job_id"] for j in jobs] == [f"j-{n}-1", f"j-{n}-2"]
    assert jobs[0]["branch"] == jobs[1]["branch"] == f"agent/issue-{n}"
    st = gh.state_of(n)
    assert "coder-session-lost" in st["escalation"]["reasons"][0] and st["coder_sessions_lost"] == 2
    assert f"agent-lease/{n}" not in gh.branches


def test_one_unreachable_poll_is_not_a_loss(world: World) -> None:
    gh, coder = world.gh, world.coder
    coder.polls_to_finish = 3
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.BUILDING in gh.labels(n))
    coder.lost_jobs = {f"j-{n}-1"}
    world.tick()
    coder.lost_jobs = set()
    world.drive(lambda: state.RELEASED in gh.labels(n))
    assert len(start_jobs(world)) == 1 and "coder_sessions_lost" not in gh.state_of(n)


def test_a_job_still_running_past_deadline_plus_30_minutes_is_lost_and_restarted(world: World) -> None:
    gh, coder = world.gh, world.coder
    world.budget = Budget(usd_cap_issue=10.0, usd_cap_total=50.0)    # jobs now cost what Azure bills
    coder.polls_to_finish = 10**6
    coder.extra_status = {"elapsed_s": 42}           # the live symptom: a progress report that never moves
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: len(start_jobs(world)) == 2, max_ticks=60)

    assert machine.CODER_GRACE_S == 1800
    first = coder.jobs[f"j-{n}-1"]
    assert first["status"] == "cancelled"                        # best-effort cancel of the stuck job
    assert gh.state_of(n)["coder_sessions_lost"] == 1 and gh.state_of(n)["coder"]["job_id"] == f"j-{n}-2"
    coder.polls_to_finish = 1
    world.drive(lambda: state.RELEASED in gh.labels(n))


def test_unreachable_polls_must_be_consecutive(world: World) -> None:
    gh, coder = world.gh, world.coder
    coder.polls_to_finish = 4
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.BUILDING in gh.labels(n))
    for gone in (True, False, True):
        coder.lost_jobs = {f"j-{n}-1"} if gone else set()
        world.tick()
    coder.lost_jobs = set()
    world.drive(lambda: state.RELEASED in gh.labels(n))
    assert len(start_jobs(world)) == 1 and "coder_sessions_lost" not in gh.state_of(n)


def test_a_lost_job_that_already_pushed_is_adopted_not_restarted(world: World) -> None:
    gh, coder = world.gh, world.coder
    coder.polls_to_finish = 10
    pr = open_stale_test_pr(world)
    world.drive(lambda: state.BUILDING in gh.labels(pr))
    coder.lost_jobs = {f"j-pr{pr}-1"}
    coder.run_orphans()                       # the job pushed its repair, then its session went away
    world.drive(lambda: state.RELEASED in gh.labels(pr))
    assert len(start_jobs(world)) == 1 and gh.state_of(pr)["coder_sessions_lost"] == 1
