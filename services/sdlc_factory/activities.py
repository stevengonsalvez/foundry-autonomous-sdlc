"""
Temporal activities over the existing tick (decision D1): sync callables bound to FactoryDeps.

    run_step   one step of ONE object: run_tick(only=N, use_lock=False, hold=...) then object_outcome
    list_work  the objects a WorkItemWorkflow should drive: open owner issues and owner maintenance PRs
    po_intake  the simulated product owner's intake; off unless PO_INTAKE_ENABLED

They run on the foreman task queue, one at a time (D6), which is what keeps run_tick's cross-issue
writes (metrics.json, release tags) serial now that the lock ref is skipped.

run_step also maps two engine failures the tick only defers or counts onto results the workflow acts
on (detected from the tick's "<ExceptionType>: message" detail, so any FoundryPort works):
    QuotaError -> "quota"   the account quota is spent; the workflow waits on a durable timer
    AuthError  -> "auth"    the engine token is missing or expired; the workflow stops stepping
and carries the D7 surrogate spend of the step (CliFoundry.usage_summary delta priced by surrogate_usd).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sdlc_agents.gates import MAINTENANCE_LABEL
from sdlc_agents.ports import OWNER, Budget
from sdlc_agents.tick import object_outcome, run_tick
from temporalio import activity
from temporalio.exceptions import ApplicationError

from sdlc_factory.deps import FactoryDeps

NON_RETRYABLE = "NonRetryable"
PO_INTAKE_FLAG = "PO_INTAKE_ENABLED"
QUOTA, AUTH = "quota", "auth"
_ERROR_RESULTS = {"QuotaError": QUOTA, "AuthError": AUTH}


@dataclass
class StepInput:
    number: int
    hold: list[str]


@dataclass
class StepOutput:
    action: str
    result: str             # the tick's ObjectReport.result, or "quota" / "auth"
    detail: str
    stage: str | None
    terminal: bool
    wait_hint_s: int
    calls: int = 0          # engine calls this step made (D7)
    minutes: float = 0.0    # their wall minutes
    surrogate_usd: float = 0.0


@dataclass
class WorkRef:
    number: int
    kind: str               # "issue" | "pr"

    @property
    def workflow_id(self) -> str:
        return f"{self.kind}-{self.number}"


class _NoSecrets:
    """run_tick's secrets port: the adapters already hold their credentials, the tick reads none."""

    def get_secret(self, name: str) -> str:
        raise RuntimeError(f"the tick does not read secrets ({name})")


def flag_enabled(flag: str) -> bool:
    return os.environ.get(flag, "").strip().lower() in ("1", "true", "yes", "on")


def _usage(foundry: Any) -> tuple[int, float]:
    summary = getattr(foundry, "usage_summary", None)
    if summary is None:
        return 0, 0.0
    usage = summary()
    return int(usage["calls"]), float(usage["minutes"])


def _result(result: str, detail: str) -> str:
    error_type = detail.split(":", 1)[0]
    return _ERROR_RESULTS.get(error_type, result) if result in ("deferred", "error") else result


def build_activities(deps: FactoryDeps) -> list[Callable[..., Any]]:
    @activity.defn(name="run_step")
    def run_step(inp: StepInput) -> StepOutput:
        if inp.number <= 0:
            raise ApplicationError(f"not an issue number: {inp.number}", type=NON_RETRYABLE, non_retryable=True)
        calls_before, minutes_before = _usage(deps.foundry)
        budget = Budget(usd_cap_total=deps.budget.usd_cap_total, usd_cap_issue=deps.budget.usd_cap_issue)
        report = run_tick(deps.github, deps.foundry, _NoSecrets(), deps.clock, budget=budget, sleep=deps.sleep,
                          emitter=deps.emitter, only=inp.number, use_lock=False, hold=frozenset(inp.hold))
        outcome = object_outcome(report, inp.number, deps.github)
        calls_after, minutes_after = _usage(deps.foundry)
        calls, minutes = calls_after - calls_before, round(minutes_after - minutes_before, 4)
        surrogate = getattr(deps.foundry, "surrogate_usd", None)
        return StepOutput(
            action=outcome.action, result=_result(outcome.result, outcome.detail), detail=outcome.detail,
            stage=outcome.stage, terminal=outcome.terminal, wait_hint_s=outcome.wait_hint_s,
            calls=calls, minutes=minutes, surrogate_usd=surrogate(calls, minutes) if surrogate else 0.0,
        )

    @activity.defn(name="list_work")
    def list_work() -> list[WorkRef]:
        refs = []
        for item in sorted(deps.github.list_issues(state="open"), key=lambda i: i.number):
            if item.author != OWNER or any(label.startswith("escalated:") for label in item.labels):
                continue
            if item.is_pull_request:
                if MAINTENANCE_LABEL in item.labels:      # agent PRs are driven through their issue
                    refs.append(WorkRef(item.number, "pr"))
            else:
                refs.append(WorkRef(item.number, "issue"))
        return refs

    @activity.defn(name="po_intake")
    def po_intake() -> str:
        if not flag_enabled(PO_INTAKE_FLAG):
            return "disabled"
        raise ApplicationError("po intake (ROADMAP.md to issues) is not implemented in this slice",
                               type=NON_RETRYABLE, non_retryable=True)

    return [run_step, list_work, po_intake]
