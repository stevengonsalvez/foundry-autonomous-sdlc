"""
The factory's Temporal worker: `python -m sdlc_factory.worker --role foreman|poller`.

    foreman  workflows + activities on task queue "foreman", ONE activity at a time (D6: run_step
             writes metrics.json and reserves release tags, cross-issue state the lock ref used to guard)
    poller   workflows only, same task queue: extra workflow-task capacity that adds no activity
             concurrency (safe to scale out; the foreman stays the single activity runner)

Env: TEMPORAL_ADDRESS (localhost:7233), TEMPORAL_NAMESPACE (default), plus deps.build_from_env for the
foreman. SIGTERM / SIGINT stop polling, let the running activity finish, then exit.
"""

from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import logging
import os
import signal
from collections.abc import Callable, Sequence
from typing import Any

from temporalio.client import Client
from temporalio.worker import Worker

from sdlc_factory.workflows import TASK_QUEUE, PoIntakeWorkflow, PollWorkflow, WorkItemWorkflow

FOREMAN_MAX_CONCURRENT_ACTIVITIES = 1
ACTIVITY_THREADS = 2
ROLES = ("foreman", "poller")
WORKFLOWS = [WorkItemWorkflow, PollWorkflow, PoIntakeWorkflow]

log = logging.getLogger("sdlc_factory.worker")


def build_worker(client: Client, role: str, activities: Sequence[Callable[..., Any]]) -> Worker:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}: expected one of {', '.join(ROLES)}")
    if role == "poller":
        return Worker(client, task_queue=TASK_QUEUE, workflows=WORKFLOWS)
    return Worker(
        client, task_queue=TASK_QUEUE, workflows=WORKFLOWS, activities=list(activities),
        activity_executor=concurrent.futures.ThreadPoolExecutor(ACTIVITY_THREADS),
        max_concurrent_activities=FOREMAN_MAX_CONCURRENT_ACTIVITIES,
    )


async def serve(worker: Worker, stop: asyncio.Event) -> None:
    """Run `worker` until `stop` is set, then shut it down gracefully."""
    async with worker:
        await stop.wait()
        log.info("stopping: finishing the running activity")


async def main(role: str) -> None:
    address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")
    activities: list[Callable[..., Any]] = []
    if role == "foreman":
        from sdlc_factory.activities import build_activities
        from sdlc_factory.deps import build_from_env

        activities = build_activities(build_from_env())
    client = await Client.connect(address, namespace=namespace)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    log.info("worker %s on %s/%s, task queue %s", role, address, namespace, TASK_QUEUE)
    await serve(build_worker(client, role, activities), stop)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python -m sdlc_factory.worker")
    parser.add_argument("--role", choices=ROLES, required=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main(parser.parse_args().role))
