"""
The foreman worker (D6: one activity at a time, so metrics.json and release tags are never written by
two steps at once), its graceful shutdown, and schedule_init's idempotent Schedule registration.

Schedules are not implemented by the time-skipping test server, so the schedule tests use the local
dev server (`WorkflowEnvironment.start_local`).
"""

from __future__ import annotations

import asyncio
import dataclasses
import threading
import time
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from conftest import World
from sdlc_agents import state
from temporalio.client import ScheduleOverlapPolicy
from temporalio.testing import WorkflowEnvironment
from test_scenarios import open_scenario

from sdlc_factory import schedule_init, worker
from sdlc_factory.activities import build_activities
from sdlc_factory.config import HumanGates
from sdlc_factory.workflows import TASK_QUEUE, PollInput, PollWorkflow, WorkInput, WorkItemWorkflow
from tests.test_activities import fake_deps, free_port, spaced


@pytest.fixture
async def env() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as e:
        yield e


# -- worker -------------------------------------------------------------------------------------------

def test_foreman_runs_one_activity_at_a_time() -> None:
    assert worker.FOREMAN_MAX_CONCURRENT_ACTIVITIES == 1


async def test_build_worker_foreman_config(env: WorkflowEnvironment, world: World) -> None:
    w = worker.build_worker(env.client, "foreman", build_activities(fake_deps(world)))
    config = w.config()

    assert config["task_queue"] == TASK_QUEUE == "foreman"
    assert config["max_concurrent_activities"] == 1
    assert {wf.__name__ for wf in config["workflows"]} >= {"WorkItemWorkflow", "PollWorkflow"}
    assert len(config["activities"]) == 3


async def test_build_worker_poller_runs_workflows_only(env: WorkflowEnvironment) -> None:
    config = worker.build_worker(env.client, "poller", []).config()

    assert config["task_queue"] == TASK_QUEUE and not config.get("activities")


def test_build_worker_refuses_an_unknown_role() -> None:
    with pytest.raises(ValueError, match="role"):
        worker.build_worker(None, "coder", [])  # type: ignore[arg-type]


async def test_two_work_items_never_overlap_inside_run_step(env: WorkflowEnvironment, world: World) -> None:
    active, peak, guard = 0, 0, threading.Lock()

    def counted(original, inp):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.02)        # widen the window a second step would have to overlap in
            return dataclasses.replace(original(inp), wait_hint_s=1)
        finally:
            with guard:
                active -= 1

    a, b = open_scenario(world, "a"), open_scenario(world, "d")
    activities = spaced(world, build_activities(fake_deps(world)), around=counted)
    # Real time, not skipped: the time-skipping server skips ahead while a run_step waits for the single
    # activity slot (it counts a queued activity as idle), timing the waiting workflow out. A real server
    # never skips; the 1 s wait hints keep this test fast.
    with env.auto_time_skipping_disabled():
        async with worker.build_worker(env.client, "foreman", activities):
            results = await asyncio.gather(*(
                env.client.execute_workflow(WorkItemWorkflow.run, WorkInput(number=n, gate_spec=False,
                                                                            gate_merge=False),
                                            id=f"issue-{n}", task_queue=TASK_QUEUE) for n in (a, b)))

    assert peak == 1
    assert [r["stage"] for r in results] == [state.RELEASED, state.RELEASED]
    assert len(set(world.gh.tags)) == 2       # two releases, two distinct tags


async def test_serve_returns_after_the_stop_event(env: WorkflowEnvironment) -> None:
    stop = asyncio.Event()
    serving = asyncio.create_task(worker.serve(worker.build_worker(env.client, "poller", []), stop))
    await asyncio.sleep(0.2)

    stop.set()

    await asyncio.wait_for(serving, timeout=15)


# -- schedule_init ------------------------------------------------------------------------------------

@pytest.fixture
async def dev_server() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local() as e:
        yield e


async def test_schedule_init_creates_then_updates_idempotently(dev_server: WorkflowEnvironment) -> None:
    client = dev_server.client

    first = await schedule_init.ensure_schedules(client, HumanGates(spec=False, merge=False), po_intake_enabled=False)
    second = await schedule_init.ensure_schedules(client, HumanGates(spec=True, merge=True), po_intake_enabled=False)

    assert first == {"github-poll": "created", "po-intake": "created"}
    assert second == {"github-poll": "updated", "po-intake": "updated"}
    poll = await client.get_schedule_handle("github-poll").describe()
    assert poll.schedule.spec.intervals[0].every == timedelta(seconds=60)
    assert poll.schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
    assert poll.schedule.action.workflow == PollWorkflow.__name__
    assert poll.schedule.action.task_queue == TASK_QUEUE
    args = await client.data_converter.decode(poll.schedule.action.args, [PollInput])
    assert args == [PollInput(gate_spec=True, gate_merge=True)]
    assert not poll.schedule.state.paused
    po = await client.get_schedule_handle("po-intake").describe()
    assert po.schedule.spec.intervals[0].every == timedelta(hours=4)
    assert po.schedule.state.paused

    await schedule_init.ensure_schedules(client, HumanGates(), po_intake_enabled=True)

    assert not (await client.get_schedule_handle("po-intake").describe()).schedule.state.paused
    await schedule_init.ensure_schedules(client, HumanGates(), po_intake_enabled=False)
    assert (await client.get_schedule_handle("po-intake").describe()).schedule.state.paused


async def test_connect_gives_up_after_its_deadline() -> None:
    started = time.monotonic()

    with pytest.raises(TimeoutError, match="Temporal"):
        await schedule_init.connect(f"127.0.0.1:{free_port()}", "default", deadline_s=1.5, interval_s=0.25)

    assert time.monotonic() - started < 15
