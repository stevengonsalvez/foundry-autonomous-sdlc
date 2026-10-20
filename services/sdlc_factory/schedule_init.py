"""
schedule-init: register the factory's Temporal Schedules, idempotently (create, or update in place).

    github-poll  every 60 s   PollWorkflow(humanGates from factory.yaml), overlap SKIP
    po-intake    every 4 h    PoIntakeWorkflow, paused unless PO_INTAKE_ENABLED

`python -m sdlc_factory.schedule_init` waits up to 120 s for Temporal to answer, registers both and
exits 0 (1 when Temporal never answered or registration failed).
Env: TEMPORAL_ADDRESS (localhost:7233), TEMPORAL_NAMESPACE (default), FACTORY_CONFIG, PO_INTAKE_ENABLED.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import timedelta

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
    ScheduleUpdate,
)

from sdlc_factory.activities import PO_INTAKE_FLAG, flag_enabled
from sdlc_factory.config import HumanGates, load_factory
from sdlc_factory.deps import DEFAULT_FACTORY_CONFIG
from sdlc_factory.workflows import TASK_QUEUE, PoIntakeWorkflow, PollInput, PollWorkflow

POLL_SCHEDULE, PO_SCHEDULE = "github-poll", "po-intake"
POLL_EVERY = timedelta(seconds=60)
PO_EVERY = timedelta(hours=4)
CONNECT_DEADLINE_S = 120.0

log = logging.getLogger("sdlc_factory.schedule_init")


def _schedule(action: ScheduleActionStartWorkflow, every: timedelta, *, paused: bool, note: str) -> Schedule:
    return Schedule(
        action=action,
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=every)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
        state=ScheduleState(paused=paused, note=note),
    )


def desired(gates: HumanGates, *, po_intake_enabled: bool) -> dict[str, Schedule]:
    poll = ScheduleActionStartWorkflow(PollWorkflow.run, PollInput(gate_spec=gates.spec, gate_merge=gates.merge),
                                       id=f"{POLL_SCHEDULE}-run", task_queue=TASK_QUEUE)
    po = ScheduleActionStartWorkflow(PoIntakeWorkflow.run, id=f"{PO_SCHEDULE}-run", task_queue=TASK_QUEUE)
    return {
        POLL_SCHEDULE: _schedule(poll, POLL_EVERY, paused=False, note="schedule-init"),
        PO_SCHEDULE: _schedule(po, PO_EVERY, paused=not po_intake_enabled,
                               note="schedule-init" if po_intake_enabled else f"paused: {PO_INTAKE_FLAG} is off"),
    }


async def ensure_schedules(client: Client, gates: HumanGates, *, po_intake_enabled: bool) -> dict[str, str]:
    """Create each schedule, or replace an existing one's definition. Returns id -> created | updated."""
    outcome = {}
    for schedule_id, schedule in desired(gates, po_intake_enabled=po_intake_enabled).items():
        try:
            await client.create_schedule(schedule_id, schedule)
            outcome[schedule_id] = "created"
        except ScheduleAlreadyRunningError:
            handle = client.get_schedule_handle(schedule_id)
            await handle.update(lambda _: ScheduleUpdate(schedule=schedule))   # noqa: B023  (awaited at once)
            # An update does not apply the paused flag; set it explicitly.
            await (handle.pause(note=schedule.state.note) if schedule.state.paused else handle.unpause())
            outcome[schedule_id] = "updated"
    return outcome


async def connect(address: str, namespace: str, *, deadline_s: float = CONNECT_DEADLINE_S,
                  interval_s: float = 2.0) -> Client:
    """Connect, retrying until Temporal answers or `deadline_s` passes (TimeoutError)."""
    give_up = time.monotonic() + deadline_s
    while True:
        try:
            return await asyncio.wait_for(Client.connect(address, namespace=namespace), timeout=max(interval_s, 5.0))
        except Exception as exc:
            if time.monotonic() + interval_s > give_up:
                raise TimeoutError(f"Temporal at {address} ({namespace}) unreachable after {deadline_s:.0f} s: "
                                   f"{type(exc).__name__}: {exc}") from None
            log.info("waiting for Temporal at %s: %s", address, type(exc).__name__)
            await asyncio.sleep(interval_s)


async def main() -> int:
    address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")
    try:
        config = load_factory(os.environ.get("FACTORY_CONFIG") or DEFAULT_FACTORY_CONFIG)
        client = await connect(address, namespace)
        outcome = await ensure_schedules(client, config.human_gates, po_intake_enabled=flag_enabled(PO_INTAKE_FLAG))
    except Exception as exc:
        log.error("schedule-init failed: %s: %s", type(exc).__name__, exc)
        return 1
    log.info("schedules on %s/%s: %s", address, namespace, outcome)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    sys.exit(asyncio.run(main()))
