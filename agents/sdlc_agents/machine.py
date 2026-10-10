"""
The SDLC state machine as pure functions (docs/architecture.md, "State machine").

`next_action(ctx)` decides the single next step for one object from its labels, its state comment,
its pull request and that PR's check results. The `after_*` helpers decide where a step's result
leads. Nothing here performs I/O; tick.py executes the decisions.

Objects:
- issue: an owner-authored issue (type feature or bug).
- pr: an owner-authored PR labelled maintenance:test-repair (the stale-test repair path).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from sdlc_agents import gates
from sdlc_agents.clock import seconds_between
from sdlc_agents.definitions import MAX_REFINEMENT_ROUNDS, QUALITY_THRESHOLD
from sdlc_agents.ports import OWNER, Budget, PullRequest
from sdlc_agents.state import (
    BUILDING,
    ESC_AGENT_ERROR,
    ESC_BUILD_FAILED,
    ESC_COST_CAP,
    ESC_NOT_SUITABLE,
    ESC_REQUIREMENTS,
    ESC_REVIEW_FAILED,
    ESCALATIONS,
    FEASIBLE,
    IN_REVIEW,
    MERGED,
    NEEDS_REFINEMENT,
    READY,
    RELEASED,
    TESTS_WRITTEN,
    State,
)

MAX_REVIEW_REJECTIONS = 2
MAX_CODER_ATTEMPTS = 8            # first build, two rebuilds after test repairs, two CI revisions, a review one
MAX_CI_REVISIONS = 2              # red required checks on an agent PR: coder revise rounds before build-failed
CI_REVISABLE = ("test", "coverage", "e2e")   # code failures; gitleaks, tdd-order, agent-scope escalate at once
MAX_TEST_REPAIRS = 2              # coder reported tests-invalid: designer repairs before agent-error
CODER_DEADLINE_S = 7_200           # sent in every job; the coder stops itself at this point
MAX_CODER_RESUMES = 3              # restarts of an interrupted job before giving up
CODER_GRACE_S = 900                # after which the orchestrator cancels and escalates
FAILURE_LIMIT = 3
POLL_FAILURE_LIMIT = 6             # coder status errors tolerated (30 minutes of ticks)
CHECKS_TIMEOUT_S = 3 * 3600        # required checks missing or pending this long: the run never came
MIN_CODER_BUDGET_USD = 0.01        # below this the coder cannot run (it refuses a zero model budget)
RECONCILING = ("start-unconfirmed", "lease-held")


class Kind(StrEnum):
    IGNORE = "ignore"              # not owner-authored: no spend, no comment
    NOOP = "noop"                  # terminal or nothing to do
    WAIT = "wait"                  # waiting on CI or the coder
    HALT = "halt"                  # total budget reached: no new work
    TRIAGE = "triage"
    GATE = "gate"
    ANSWER = "answer"
    RESCORE = "rescore"
    FEASIBILITY = "feasibility"
    DESIGN_TESTS = "design-tests"
    START_CODER = "start-coder"
    RECONCILE = "reconcile-coder"  # a start whose outcome is unknown, or refused because a lease is held
    POLL_CODER = "poll-coder"
    CI_TRIAGE = "ci-triage"
    REVIEW = "review"
    MERGE = "merge"
    MARK_MERGED = "mark-merged"
    RELEASE = "release"
    CLOSE = "close"
    ESCALATE = "escalate"


# Steps the spend caps can stop. RELEASE is exempt: merged work is always released, and past a cap
# its notes are written without a model call (tick.py), so it never adds spend over a cap.
MODEL_ACTIONS = frozenset({
    Kind.TRIAGE, Kind.GATE, Kind.ANSWER, Kind.RESCORE, Kind.FEASIBILITY, Kind.DESIGN_TESTS,
    Kind.CI_TRIAGE, Kind.REVIEW,
})
SPEND_ACTIONS = MODEL_ACTIONS | {Kind.START_CODER, Kind.RECONCILE}

# Which escalation a repeatedly failing step ends in.
# Only non-transient failures are counted (tick.py defers transient ones). A prompt agent that keeps
# failing ends in escalated:agent-error, never in a verdict label such as not-agent-suitable.
_FAILURE_LABELS = dict.fromkeys(MODEL_ACTIONS | {Kind.RELEASE}, ESC_AGENT_ERROR)


@dataclass(frozen=True)
class Action:
    kind: Kind
    reason: str = ""
    label: str | None = None          # ESCALATE: the escalation label
    mode: str | None = None           # START_CODER: feature | bugfix | revise | maintenance
    cancel_coder: bool = False        # ESCALATE: cancel the running coder job first
    record: dict[str, Any] | None = None   # WAIT: state keys to remember (for example a cancelled head)


@dataclass(frozen=True)
class Context:
    kind: Literal["issue", "pr"]
    number: int
    author: str
    labels: frozenset[str]
    is_open: bool
    object_type: str                                   # feature | bug | maintenance
    state: State | None
    now: str
    budget: Budget
    pr: PullRequest | None = None                      # the linked PR (issue) or the PR itself
    checks: Mapping[str, str] = field(default_factory=dict)  # gates.check_summary of pr.head_sha
    pr_touches_tests: bool | None = None               # maintenance: does the PR diff change test files
    object_usd: float | None = None                    # best known spend (tick.py); else the state's


def next_action(ctx: Context) -> Action:
    if ctx.author != OWNER:
        return Action(Kind.IGNORE, f"author {ctx.author} is not the owner")
    state = ctx.state
    escalated = sorted(label for label in ctx.labels if label in ESCALATIONS)
    if state is not None and state.escalation:
        return Action(Kind.NOOP, f"terminal: {state.escalation}")
    if escalated:
        return Action(Kind.NOOP, f"terminal: {escalated[0]}")

    action = _issue_action(ctx) if ctx.kind == "issue" else _maintenance_action(ctx)
    return _guard(ctx, action)


def _guard(ctx: Context, action: Action) -> Action:
    """Repeated failures and the spend caps override the planned step."""
    state = ctx.state
    failures = state.get("failures") if state else None
    if failures and action.kind.value == failures.get("action"):
        limit = POLL_FAILURE_LIMIT if action.kind is Kind.POLL_CODER else FAILURE_LIMIT
        if int(failures.get("count", 0)) >= limit:
            label = _FAILURE_LABELS.get(action.kind, ESC_BUILD_FAILED)
            reason = f"{action.kind.value} failed {failures['count']} times: {failures.get('error')}"
            return Action(Kind.ESCALATE, reason, label=label, cancel_coder=action.kind is Kind.POLL_CODER)

    if action.kind in SPEND_ACTIONS and not ctx.budget.known:
        # Fail closed: without a trustworthy spend figure nothing that costs money may run.
        return Action(Kind.HALT, "spend cannot be determined (unreadable metrics.json or state comment)")
    object_usd = ctx.object_usd if ctx.object_usd is not None else (state.usd if state else 0.0)
    cap = ctx.budget.usd_cap_issue
    costs_money = action.kind in SPEND_ACTIONS or action.kind in (Kind.POLL_CODER, Kind.MERGE)
    if costs_money and object_usd >= cap:
        return Action(Kind.ESCALATE, f"cost {object_usd:.4f} USD reached the {cap:.2f} USD cap",
                      label=ESC_COST_CAP, cancel_coder=action.kind is Kind.POLL_CODER)
    if action.kind in (Kind.START_CODER, Kind.RECONCILE) and cap - object_usd < MIN_CODER_BUDGET_USD:
        return Action(Kind.ESCALATE, f"cost {object_usd:.4f} USD leaves less than {MIN_CODER_BUDGET_USD:.2f} USD "
                      f"under the {cap:.2f} USD cap for the coder", label=ESC_COST_CAP)
    total, total_cap = ctx.budget.usd_total, ctx.budget.usd_cap_total
    if action.kind in SPEND_ACTIONS and total >= total_cap:
        return Action(Kind.HALT, f"total spend {total:.4f} USD reached {total_cap:.2f} USD")
    return action


def _triaged(state: State | None) -> bool:
    return bool(state and state.get("triage"))


def _issue_action(ctx: Context) -> Action:
    state = ctx.state
    stage = state.stage if state else None
    if not ctx.is_open:
        # Merging the PR auto-closes the issue ("Closes #N"), so a closed issue may still owe a release.
        if stage == IN_REVIEW and ctx.pr is not None and ctx.pr.merged:
            return Action(Kind.MARK_MERGED)
        if stage == BUILDING:
            return Action(Kind.ESCALATE, "issue closed while the coder was building", label=ESC_BUILD_FAILED,
                          cancel_coder=True)
        if stage not in (MERGED, RELEASED):
            return Action(Kind.NOOP, "issue is closed")
    if _reconciling(state):
        return Action(Kind.RECONCILE)
    bug_untriaged = ctx.object_type == "bug" and not _triaged(state)
    if stage is None:
        return Action(Kind.TRIAGE) if bug_untriaged else Action(Kind.GATE)
    if stage == NEEDS_REFINEMENT:
        quality = state.get("quality") if state else None
        return Action(Kind.RESCORE) if quality and quality.get("answers") else Action(Kind.ANSWER)
    if stage == READY:
        return Action(Kind.TRIAGE) if bug_untriaged else Action(Kind.FEASIBILITY)
    if stage == FEASIBLE:
        return Action(Kind.DESIGN_TESTS)
    if stage == TESTS_WRITTEN:
        return _start_coder(state, "bugfix" if ctx.object_type == "bug" else "feature")
    if stage == BUILDING:
        return _poll_coder(ctx)
    if stage == IN_REVIEW:
        return _review_action(ctx, revise_mode="revise")
    if stage == MERGED:
        return Action(Kind.RELEASE)
    return Action(Kind.CLOSE) if ctx.is_open else Action(Kind.NOOP, "released")


def _maintenance_action(ctx: Context) -> Action:
    state = ctx.state
    stage = state.stage if state else None
    pr = ctx.pr
    if _reconciling(state):
        return Action(Kind.RECONCILE)
    if stage == BUILDING:
        return _poll_coder(ctx)
    if stage == IN_REVIEW:
        return _review_action(ctx, revise_mode="maintenance")
    if stage == MERGED:
        return Action(Kind.RELEASE)
    if stage == RELEASED:
        return Action(Kind.NOOP, "released")
    if pr is None or pr.merged or pr.state != "open":
        return Action(Kind.NOOP, "pull request closed outside the pipeline")
    waiting = _waiting(ctx, pr.created_at)
    if waiting:
        return waiting
    grace = _cancel_grace(ctx, pr.head_sha)
    if grace:
        return grace
    failed = gates.failed(ctx.checks)
    ci = state.get("ci_triage") if state else None
    if not failed:
        # This path exists to repair a stale test; a PR that was never red is not the pipeline's to merge.
        return Action(Kind.REVIEW) if ci else Action(Kind.NOOP, "checks green and nothing to repair")
    if "test" not in failed:
        return Action(Kind.ESCALATE, f"required checks failed: {', '.join(failed)}", label=ESC_BUILD_FAILED)
    if ctx.pr_touches_tests:
        return Action(Kind.ESCALATE, "test check fails and the PR already changes test files", label=ESC_BUILD_FAILED)
    if ci and ci.get("head") == pr.head_sha:
        if ci.get("cause") == "stale-test":
            return _start_coder(state, "maintenance")
        return Action(Kind.ESCALATE, f"ci-triage found a real bug: {ci.get('explanation', '')}", label=ESC_BUILD_FAILED)
    return Action(Kind.CI_TRIAGE)


def _reconciling(state: State | None) -> bool:
    return bool(state and (state.get("coder") or {}).get("status") in RECONCILING)


def _waiting(ctx: Context, since: str | None) -> Action | None:
    """WAIT while required checks are pending or missing, but not for ever: after CHECKS_TIMEOUT_S
    (a workflow that never ran, a renamed job, an Actions outage) escalate build-failed."""
    names = gates.waiting(ctx.checks)
    if not names:
        return None
    if since and seconds_between(since, ctx.now) > CHECKS_TIMEOUT_S:
        return Action(Kind.ESCALATE, f"required checks still missing or pending after {CHECKS_TIMEOUT_S // 3600} h: "
                      f"{', '.join(names)}", label=ESC_BUILD_FAILED)
    return Action(Kind.WAIT, f"checks pending: {', '.join(names)}")


def _cancel_grace(ctx: Context, head: str) -> Action | None:
    """ci.yml cancels superseded runs: a cancelled check waits one tick for its rerun before it counts."""
    cancelled = [n for n, s in ctx.checks.items() if s == "cancelled"]
    if cancelled and not (ctx.state and ctx.state.data.get("cancelled_head") == head):
        return Action(Kind.WAIT, f"checks cancelled, waiting one tick for a rerun: {', '.join(cancelled)}",
                      record={"cancelled_head": head})
    return None


def _entered(state: State | None, stage: str) -> str | None:
    if state is None:
        return None
    return next((s["at"] for s in reversed(state.data["stages"]) if s["stage"] == stage), None)


def _start_coder(state: State | None, mode: str) -> Action:
    coder = state.get("coder") if state else None
    attempts = int(coder.get("attempts", 0)) if coder else 0
    retrying = bool(coder and coder.get("status") == "starting")   # bounded by the failure counter
    if attempts >= MAX_CODER_ATTEMPTS and not retrying:
        return Action(Kind.ESCALATE, f"coder attempts exhausted ({attempts})", label=ESC_BUILD_FAILED)
    return Action(Kind.START_CODER, mode=mode)


def _poll_coder(ctx: Context) -> Action:
    coder = ctx.state.get("coder") if ctx.state else None
    if not coder or not coder.get("job_id"):
        return Action(Kind.ESCALATE, "building without a coder job", label=ESC_BUILD_FAILED)
    if coder.get("status") == "starting":
        if int(coder.get("resumes", 0)) > MAX_CODER_RESUMES:
            return Action(Kind.ESCALATE, f"coder interrupted {coder['resumes']} times", label=ESC_BUILD_FAILED)
        return Action(Kind.START_CODER, "resume", mode=str(coder.get("mode")))
    started = coder.get("started_at")
    if started and seconds_between(started, ctx.now) > CODER_DEADLINE_S + CODER_GRACE_S:
        return Action(Kind.ESCALATE, "coder exceeded the six hour deadline", label=ESC_BUILD_FAILED, cancel_coder=True)
    return Action(Kind.POLL_CODER)


def _review_action(ctx: Context, *, revise_mode: str) -> Action:
    pr = ctx.pr
    state = ctx.state
    if pr is None:
        return Action(Kind.ESCALATE, "no pull request recorded", label=ESC_BUILD_FAILED)
    if pr.merged:
        return Action(Kind.MARK_MERGED)
    if pr.state != "open":
        return Action(Kind.ESCALATE, f"pull request #{pr.number} closed without merge", label=ESC_BUILD_FAILED)
    grace = _cancel_grace(ctx, pr.head_sha)
    if grace:
        return grace
    failed = gates.failed(ctx.checks)
    code_failures = [name for name in failed if ctx.checks[name] != "cancelled"]
    if code_failures and ctx.kind == "issue" and set(code_failures) <= set(CI_REVISABLE):
        # An agent PR that fails CI is worked on (tick.py: designer repair or coder revise), not dropped.
        ci = state.get("ci_revise") if state else None
        if ci and ci.get("head") == pr.head_sha and ci.get("action") == "revise":
            return _start_coder(state, revise_mode)
        return Action(Kind.CI_TRIAGE, f"required checks failed on {pr.head_sha[:7]}: {', '.join(code_failures)}")
    if failed:
        return Action(Kind.ESCALATE, f"required checks failed on {pr.head_sha[:7]}: {', '.join(failed)}",
                      label=ESC_BUILD_FAILED)
    waiting = _waiting(ctx, _entered(state, IN_REVIEW))
    if waiting:
        return waiting
    review = state.get("review") if state else None
    if review and review.get("head") == pr.head_sha:
        if review.get("verdict") == "approve":
            return Action(Kind.MERGE)
        if int(review.get("rounds", 0)) >= MAX_REVIEW_REJECTIONS:
            return Action(Kind.ESCALATE, f"reviewer requested changes {review.get('rounds')} times",
                          label=ESC_REVIEW_FAILED)
        return _start_coder(state, revise_mode)
    return Action(Kind.REVIEW)


# ---------------------------------------------------------------------------
# Where results lead
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Outcome:
    stage: str | None = None          # the stage to enter, if any
    escalate: str | None = None       # the escalation label, if any
    reason: str = ""
    resume: bool = False              # restart the same coder job
    repair_tests: bool = False        # the designed tests were invalid: back to the test designer


def after_score(score: int, rounds: int) -> Outcome:
    """`rounds` is the number of refinement rounds already used (questions asked and answered)."""
    if score >= QUALITY_THRESHOLD:
        return Outcome(stage=READY)
    if rounds < MAX_REFINEMENT_ROUNDS:
        return Outcome(stage=NEEDS_REFINEMENT, reason=f"score {score} below {QUALITY_THRESHOLD}")
    return Outcome(escalate=ESC_REQUIREMENTS,
                   reason=f"score {score} still below {QUALITY_THRESHOLD} after {rounds} refinement rounds")


def after_feasibility(suitable: bool) -> Outcome:
    return Outcome(stage=FEASIBLE) if suitable else Outcome(escalate=ESC_NOT_SUITABLE, reason="not agent suitable")


def after_coder(status: str, reason: str = "") -> Outcome:
    """Coder status and reason (w2b's contract): an interrupted job is resumed, other ends escalate."""
    if status == "succeeded":
        return Outcome(stage=IN_REVIEW)
    if status == "failed" and reason == "interrupted":
        return Outcome(resume=True)
    if status == "failed" and reason == "tests-invalid":
        return Outcome(repair_tests=True)
    if status in ("failed", "timeout", "cancelled"):
        return Outcome(escalate=ESC_BUILD_FAILED, reason=f"coder {status}" + (f" ({reason})" if reason else ""))
    return Outcome()
