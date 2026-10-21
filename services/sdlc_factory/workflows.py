"""
Durable drivers for the tick (decision D5).

    PollWorkflow (Schedule github-poll, every 60 s)
        list_work ──▶ start WorkItemWorkflow(id=issue-N | pr-N) per ref, already running: skip
    WorkItemWorkflow(id=issue-N)
        loop: run_step ──▶ terminal?  return summary
                       ──▶ held?      wait for human_approved(<kind>), no re-step meanwhile
                       ──▶ quota?     durable timer (quota_wait_s), give up after quota_max_attempts
                       ──▶ auth?      stop, the engine token needs an owner
                       ──▶ else       wait wait_hint_s, or until poke()
    PoIntakeWorkflow (Schedule po-intake, every 4 h, paused unless PO_INTAKE_ENABLED)

humanGates: gate_spec holds `design-tests`, gate_merge holds `merge`, until human_approved names the
kind ("spec" is accepted for design-tests, matching the factory.yaml key). Approvals and progress are
carried through continue-as-new.
"""

from __future__ import annotations

import contextlib
import dataclasses
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from sdlc_factory.activities import AUTH, NON_RETRYABLE, QUOTA, StepInput, StepOutput, WorkRef

TASK_QUEUE = "foreman"
STEP_TIMEOUT = timedelta(minutes=45)
LIST_TIMEOUT = timedelta(minutes=2)
STEP_RETRY = RetryPolicy(initial_interval=timedelta(seconds=5), maximum_attempts=3,
                         non_retryable_error_types=[NON_RETRYABLE])
HOLD_WAIT = timedelta(days=1)
FAILED_STEP_WAIT_S = 60
GATE_KINDS = {"spec": "design-tests", "design-tests": "design-tests", "merge": "merge"}


@dataclass
class Progress:
    """What a WorkItemWorkflow has done so far, across continue-as-new runs."""

    runs: int = 1
    steps: int = 0
    holds: int = 0
    calls: int = 0
    minutes: float = 0.0
    surrogate_usd: float = 0.0
    quota_attempts: int = 0     # consecutive steps that hit the engine quota


@dataclass
class WorkInput:
    number: int
    gate_spec: bool
    gate_merge: bool
    max_iterations: int = 500
    approved: list[str] = field(default_factory=list)
    quota_wait_s: int = 3600
    quota_max_attempts: int = 6
    progress: Progress = field(default_factory=Progress)


@dataclass
class PollInput:
    gate_spec: bool
    gate_merge: bool


@workflow.defn
class WorkItemWorkflow:
    def __init__(self) -> None:
        self._number = 0
        self._gates: set[str] = set()
        self._approved: set[str] = set()
        self._poke = False
        self._waiting_for: str | None = None
        self._last: StepOutput | None = None
        self._progress = Progress()

    @workflow.run
    async def run(self, inp: WorkInput) -> dict[str, Any]:
        self._number = inp.number
        self._gates = {kind for kind, on in (("design-tests", inp.gate_spec), ("merge", inp.gate_merge)) if on}
        self._approved |= set(inp.approved)
        self._progress = p = dataclasses.replace(inp.progress)
        for _ in range(inp.max_iterations):
            if workflow.info().is_continue_as_new_suggested():
                break
            out = await self._step()
            if out is None:
                await self._pause(FAILED_STEP_WAIT_S)
                continue
            if out.result == AUTH:
                return await self._finish("agent-auth")
            if out.result == QUOTA:
                p.quota_attempts += 1
                if p.quota_attempts >= inp.quota_max_attempts:
                    return await self._finish("agent-quota", escalate_quota=True)
                await workflow.sleep(inp.quota_wait_s)
                continue
            p.quota_attempts = 0
            if out.terminal:
                return await self._finish("settled")
            if out.result == "held":
                p.holds += 1
                await self._await_approval(out.action)
                continue
            await self._pause(out.wait_hint_s)
        await workflow.wait_condition(workflow.all_handlers_finished)
        p.runs += 1
        return workflow.continue_as_new(dataclasses.replace(inp, approved=sorted(self._approved), progress=p))

    async def _step(self) -> StepOutput | None:
        """One run_step; None when it failed after its retries (it is tried again after a pause)."""
        hold = sorted(self._gates - self._approved)
        try:
            out = await workflow.execute_activity(
                "run_step", StepInput(number=self._number, hold=hold), result_type=StepOutput,
                task_queue=TASK_QUEUE, start_to_close_timeout=STEP_TIMEOUT, retry_policy=STEP_RETRY)
        except ActivityError as exc:
            if isinstance(exc.cause, ApplicationError) and exc.cause.non_retryable:
                raise
            workflow.logger.warning("run_step #%s failed after retries: %s", self._number, exc.cause)
            return None
        p = self._progress
        p.steps += 1
        p.calls += out.calls
        p.minutes = round(p.minutes + out.minutes, 4)
        p.surrogate_usd = round(p.surrogate_usd + out.surrogate_usd, 6)
        self._last = out
        return out

    async def _await_approval(self, kind: str) -> None:
        self._waiting_for = kind
        while kind not in self._approved:
            try:
                await workflow.wait_condition(lambda: kind in self._approved, timeout=HOLD_WAIT)
            except TimeoutError:
                continue
        self._waiting_for = None

    async def _pause(self, seconds: int) -> None:
        with contextlib.suppress(TimeoutError):
            await workflow.wait_condition(lambda: self._poke, timeout=timedelta(seconds=seconds))
        self._poke = False

    async def _finish(self, reason: str, *, escalate_quota: bool = False) -> dict[str, Any]:
        await workflow.wait_condition(workflow.all_handlers_finished)
        last = self._last
        return {
            "number": self._number, "terminal": True, "reason": reason, "escalate_quota": escalate_quota,
            "stage": last.stage if last else None, "action": last.action if last else None,
            "result": last.result if last else None, "detail": last.detail if last else "",
            **dataclasses.asdict(self._progress),
        }

    @workflow.signal
    def poke(self) -> None:
        self._poke = True

    @workflow.signal
    def human_approved(self, kind: str) -> None:
        gate = GATE_KINDS.get(kind)
        if gate is None:
            workflow.logger.warning("#%s: ignoring approval for unknown gate %r", self._number, kind)
            return
        self._approved.add(gate)

    @workflow.query
    def status(self) -> dict[str, Any]:
        return {
            "number": self._number, "gates": sorted(self._gates), "approved": sorted(self._approved),
            "waiting_for": self._waiting_for, "last": dataclasses.asdict(self._last) if self._last else None,
            **dataclasses.asdict(self._progress),
        }


@workflow.defn
class PollWorkflow:
    @workflow.run
    async def run(self, inp: PollInput) -> dict[str, int]:
        refs = await workflow.execute_activity("list_work", result_type=list[WorkRef], task_queue=TASK_QUEUE,
                                               start_to_close_timeout=LIST_TIMEOUT, retry_policy=STEP_RETRY)
        started = running = 0
        for ref in refs:
            try:
                await workflow.start_child_workflow(
                    WorkItemWorkflow.run,
                    WorkInput(number=ref.number, gate_spec=inp.gate_spec, gate_merge=inp.gate_merge),
                    id=ref.workflow_id, task_queue=TASK_QUEUE, parent_close_policy=workflow.ParentClosePolicy.ABANDON)
                started += 1
            except WorkflowAlreadyStartedError:
                running += 1
        return {"listed": len(refs), "started": started, "running": running}


@workflow.defn
class PoIntakeWorkflow:
    @workflow.run
    async def run(self) -> str:
        return await workflow.execute_activity("po_intake", result_type=str, task_queue=TASK_QUEUE,
                                               start_to_close_timeout=STEP_TIMEOUT, retry_policy=STEP_RETRY)
