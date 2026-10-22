"""
WorkItemWorkflow and PollWorkflow on the time-skipping test server, with the activities bound to the
agents test world (FakeGitHub, FakeFoundry, FakeCoder, FakeClock). Durable timers are skipped, so a
run that would take hours of tick spacing finishes in seconds.
"""

from __future__ import annotations

import concurrent.futures
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from conftest import World
from sdlc_agents import state
from temporalio import activity
from temporalio.client import Client, WorkflowHandle
from temporalio.service import RPCError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from test_scenarios import A_BODY, UNSUITABLE, open_scenario, open_stale_test_pr

from sdlc_factory.activities import StepInput, StepOutput, build_activities
from sdlc_factory.cli_foundry import AuthError, QuotaError
from sdlc_factory.workflows import (
    TASK_QUEUE,
    PollInput,
    PollWorkflow,
    WorkInput,
    WorkItemWorkflow,
)
from tests.test_activities import MeteredFoundry, fake_deps, spaced

Around = Callable[[Callable[[StepInput], StepOutput], StepInput], StepOutput]


@pytest.fixture
async def env() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as e:
        yield e


def worker(client: Client, activities: list, *, slots: int = 1) -> Worker:
    """slots > 1 only where several workflows run at once: the time-skipping server skips ahead while an
    activity waits for a free slot, which would time the waiting workflow out (a real server does not)."""
    return Worker(client, task_queue=TASK_QUEUE, workflows=[WorkItemWorkflow, PollWorkflow], activities=activities,
                  activity_executor=concurrent.futures.ThreadPoolExecutor(max(slots, 2)),
                  max_concurrent_activities=slots)


def world_activities(world: World, *, around: Around | None = None) -> list:
    return spaced(world, build_activities(fake_deps(world)), around=around)


def work(number: int, **kw: Any) -> WorkInput:
    return WorkInput(number=number, gate_spec=kw.pop("gate_spec", False), gate_merge=kw.pop("gate_merge", False), **kw)


async def status_when(env: WorkflowEnvironment, handle: WorkflowHandle, done: Callable[[dict], bool],
                      *, max_polls: int = 200) -> dict:
    """Skip workflow time until the status query satisfies `done`."""
    for _ in range(max_polls):
        status = await handle.query(WorkItemWorkflow.status)
        if done(status):
            return status
        await env.sleep(30)
    raise AssertionError(f"status never matched; last: {status}")


# -- WorkItemWorkflow -------------------------------------------------------------------------------

async def test_a_feature_issue_is_driven_to_released_and_returns_terminal(env: WorkflowEnvironment,
                                                                          world: World) -> None:
    n = open_scenario(world, "a")
    deps = fake_deps(world)
    deps.foundry = metered = MeteredFoundry(world.foundry, deps.config)
    async with worker(env.client, spaced(world, build_activities(deps))):
        summary = await env.client.execute_workflow(WorkItemWorkflow.run, work(n), id=f"issue-{n}",
                                                    task_queue=TASK_QUEUE)

    assert summary["terminal"] and summary["stage"] == state.RELEASED and summary["number"] == n
    assert summary["holds"] == 0 and summary["reason"] == "settled"
    assert world.gh.issues[n]["state"] == "closed" and world.gh.tags == ["v0.1.0"]
    # D7: every prompt call this issue made is carried as surrogate spend
    assert summary["calls"] == metered.calls > 0
    assert summary["surrogate_usd"] == pytest.approx(metered.surrogate_usd(metered.calls, metered.minutes))


async def test_gate_merge_holds_the_unmerged_pr_until_human_approved(env: WorkflowEnvironment, world: World) -> None:
    gh = world.gh
    n = open_scenario(world, "a")
    async with worker(env.client, world_activities(world)):
        handle = await env.client.start_workflow(WorkItemWorkflow.run, work(n, gate_merge=True), id=f"issue-{n}",
                                                 task_queue=TASK_QUEUE)
        held = await status_when(env, handle, lambda s: s["waiting_for"] == "merge")
        steps = held["steps"]
        await env.sleep(3 * 24 * 3600)        # days pass: still held, and no further step was run
        still = await handle.query(WorkItemWorkflow.status)
        pr = gh.state_of(n)["pr"]["number"]

        assert still["waiting_for"] == "merge" and still["steps"] == steps
        assert not gh.pulls[pr]["merged"] and not gh.merges and state.IN_REVIEW in gh.labels(n)

        await handle.signal(WorkItemWorkflow.human_approved, "merge")
        summary = await handle.result()

    assert summary["terminal"] and summary["stage"] == state.RELEASED and summary["holds"] >= 1
    assert gh.pulls[pr]["merged"] and len(gh.merges) == 1


async def test_without_gates_the_workflow_never_waits_for_a_human(env: WorkflowEnvironment, world: World) -> None:
    n = open_scenario(world, "a")
    async with worker(env.client, world_activities(world)):
        summary = await env.client.execute_workflow(WorkItemWorkflow.run, work(n, gate_spec=False, gate_merge=False),
                                                    id=f"issue-{n}", task_queue=TASK_QUEUE)

    assert summary["holds"] == 0 and summary["stage"] == state.RELEASED


async def test_gate_spec_holds_before_the_test_designer(env: WorkflowEnvironment, world: World) -> None:
    n = open_scenario(world, "a")
    async with worker(env.client, world_activities(world)):
        handle = await env.client.start_workflow(WorkItemWorkflow.run, work(n, gate_spec=True), id=f"issue-{n}",
                                                 task_queue=TASK_QUEUE)
        await status_when(env, handle, lambda s: s["waiting_for"] == "design-tests")

        assert not world.foundry.agent_calls("sdlc-test-designer")
        assert state.FEASIBLE in world.gh.labels(n)

        await handle.signal(WorkItemWorkflow.human_approved, "spec")     # the humanGates key works too
        summary = await handle.result()

    assert summary["stage"] == state.RELEASED and world.foundry.agent_calls("sdlc-test-designer")


async def test_an_approval_for_another_gate_does_not_release_the_hold(env: WorkflowEnvironment,
                                                                      world: World) -> None:
    n = open_scenario(world, "a")
    async with worker(env.client, world_activities(world)):
        handle = await env.client.start_workflow(WorkItemWorkflow.run, work(n, gate_spec=True), id=f"issue-{n}",
                                                 task_queue=TASK_QUEUE)
        await status_when(env, handle, lambda s: s["waiting_for"] == "design-tests")
        await handle.signal(WorkItemWorkflow.human_approved, "merge")
        await handle.signal(WorkItemWorkflow.human_approved, "deploy-to-prod")   # unknown: ignored
        await env.sleep(3600)
        status = await handle.query(WorkItemWorkflow.status)

        assert status["waiting_for"] == "design-tests" and status["approved"] == ["merge"]
        assert not world.foundry.agent_calls("sdlc-test-designer")
        await handle.terminate()


async def test_a_maintenance_pr_is_driven_through_merge_to_release(env: WorkflowEnvironment, world: World) -> None:
    pr = open_stale_test_pr(world)
    async with worker(env.client, world_activities(world)):
        summary = await env.client.execute_workflow(WorkItemWorkflow.run, work(pr), id=f"pr-{pr}",
                                                    task_queue=TASK_QUEUE)

    assert summary["stage"] == state.RELEASED and world.gh.pulls[pr]["merged"]


async def test_continue_as_new_keeps_driving_the_issue_to_release(env: WorkflowEnvironment, world: World) -> None:
    n = open_scenario(world, "a")
    async with worker(env.client, world_activities(world)):
        summary = await env.client.execute_workflow(WorkItemWorkflow.run, work(n, max_iterations=3),
                                                    id=f"issue-{n}", task_queue=TASK_QUEUE)

    assert summary["stage"] == state.RELEASED and summary["runs"] > 1
    assert summary["steps"] > 3       # counted across runs


async def test_an_escalated_issue_ends_the_workflow(env: WorkflowEnvironment, world: World) -> None:
    world.foundry.script("sdlc-feasibility", UNSUITABLE)
    n = open_scenario(world, "c")
    async with worker(env.client, world_activities(world)):
        summary = await env.client.execute_workflow(WorkItemWorkflow.run, work(n), id=f"issue-{n}",
                                                    task_queue=TASK_QUEUE)

    assert summary["terminal"] and state.ESC_NOT_SUITABLE in world.gh.labels(n)


async def test_a_poke_wakes_the_workflow_before_its_timer(env: WorkflowEnvironment, world: World) -> None:
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))
    async with worker(env.client, world_activities(world)):
        handle = await env.client.start_workflow(WorkItemWorkflow.run, work(n), id=f"issue-{n}",
                                                 task_queue=TASK_QUEUE)
        first = await status_when(env, handle, lambda s: s["steps"] >= 1)
        await handle.signal(WorkItemWorkflow.poke)
        poked = await status_when(env, handle, lambda s: s["steps"] > first["steps"], max_polls=1_000)

        assert poked["steps"] > first["steps"]
        await handle.terminate()


# -- engine quota and auth --------------------------------------------------------------------------

def quota() -> QuotaError:
    return QuotaError("sdlc-req-gate: agy quota exhausted (agent-quota)", transient=True, retry_after=21600,
                      ambiguous=False)


async def test_an_engine_quota_waits_a_durable_timer_then_gives_up_flagged(env: WorkflowEnvironment,
                                                                           world: World) -> None:
    world.foundry.errors["sdlc-req-gate"] = quota()
    steps: list[StepOutput] = []

    def count(original, inp):
        steps.append(original(inp))
        return steps[-1]

    n = world.gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))
    async with worker(env.client, world_activities(world, around=count)):
        started = await env.get_current_time()
        summary = await env.client.execute_workflow(WorkItemWorkflow.run, work(n), id=f"issue-{n}",
                                                    task_queue=TASK_QUEUE)
        elapsed = (await env.get_current_time()) - started

    assert summary["terminal"] and summary["escalate_quota"] and summary["reason"] == "agent-quota"
    assert [s.result for s in steps] == ["quota"] * 6
    assert elapsed.total_seconds() >= 5 * 3600         # an hour between attempts, on durable timers


async def test_a_quota_that_clears_lets_the_issue_continue(env: WorkflowEnvironment, world: World) -> None:
    world.foundry.errors["sdlc-req-gate"] = quota()
    results: list[str] = []

    def clear_after_two(original, inp):
        out = original(inp)
        results.append(out.result)
        if results.count("quota") == 2:
            world.foundry.errors.pop("sdlc-req-gate", None)
        return out

    n = open_scenario(world, "a")
    async with worker(env.client, world_activities(world, around=clear_after_two)):
        summary = await env.client.execute_workflow(WorkItemWorkflow.run, work(n), id=f"issue-{n}",
                                                    task_queue=TASK_QUEUE)

    assert results[:2] == ["quota", "quota"] and summary["stage"] == state.RELEASED
    assert not summary["escalate_quota"]


async def test_an_engine_auth_failure_stops_stepping_at_once(env: WorkflowEnvironment, world: World) -> None:
    world.foundry.errors["sdlc-req-gate"] = AuthError("sdlc-req-gate: agy authentication required", ambiguous=False)
    steps: list[StepOutput] = []

    def count(original, inp):
        steps.append(original(inp))
        return steps[-1]

    n = world.gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))
    async with worker(env.client, world_activities(world, around=count)):
        summary = await env.client.execute_workflow(WorkItemWorkflow.run, work(n), id=f"issue-{n}",
                                                    task_queue=TASK_QUEUE)

    assert summary["terminal"] and summary["reason"] == "agent-auth" and len(steps) == 1


# -- PollWorkflow -------------------------------------------------------------------------------------

def parked_activities(world: World) -> list:
    """Real list_work; a run_step that never finishes the object, so started workflows stay running."""

    @activity.defn(name="run_step")
    def run_step(inp: StepInput) -> StepOutput:
        return StepOutput(action="wait", result="ok", detail="parked", stage=None, terminal=False, wait_hint_s=3600)

    return [run_step if activity._Definition.must_from_callable(a).name == "run_step" else a
            for a in build_activities(fake_deps(world))]


async def test_poll_starts_workflows_only_for_owner_issues_and_maintenance_prs_idempotently(
        env: WorkflowEnvironment, world: World) -> None:
    gh = world.gh
    feature = gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))
    stranger = gh.open_issue("Please add dark mode", A_BODY, author="someone-else")
    maintenance = open_stale_test_pr(world)
    agent_pr = gh.open_pr("feat: agent work", "Closes #1", "agent/issue-1", [("feat: x", ("app/x.ts",))])
    poll = PollInput(gate_spec=False, gate_merge=True)
    async with worker(env.client, parked_activities(world), slots=4):
        first = await env.client.execute_workflow(PollWorkflow.run, poll, id="poll-1", task_queue=TASK_QUEUE)
        second = await env.client.execute_workflow(PollWorkflow.run, poll, id="poll-2", task_queue=TASK_QUEUE)

        for wf_id in (f"issue-{feature}", f"pr-{maintenance}"):
            assert (await env.client.get_workflow_handle(wf_id).describe()).status.name == "RUNNING"
        child = await env.client.get_workflow_handle(f"issue-{feature}").query(WorkItemWorkflow.status)
        for wf_id in (f"issue-{stranger}", f"issue-{agent_pr}", f"pr-{agent_pr}"):
            with pytest.raises(RPCError):
                await env.client.get_workflow_handle(wf_id).describe()

    assert first == {"listed": 2, "started": 2, "running": 0}
    assert second == {"listed": 2, "started": 0, "running": 2}
    assert child["gates"] == ["merge"]
