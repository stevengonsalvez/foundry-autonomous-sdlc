"""
One orchestrator tick (docs/architecture.md, "Control loop").

    lock ─▶ load owner objects + state ─▶ per object: next_action ─▶ execute (one step) ─▶ metrics ─▶ unlock

Guarantees:
- Bounded: objects are started only while the wall budget lasts; each object takes at most one step.
- Never raises: every error is recorded against its object (and counted in the state comment, so
  a step that keeps failing escalates) and the tick moves on.
- Transactional: a failing step rolls the state back to its last saved version, keeping only the
  spend it incurred and the failure count, so a half-done step can never change what runs next.
- Owner only: objects not authored by the repo owner are never read further and cost nothing.
- Idempotent: the state comment is the source of truth and is written once per step; labels are a
  projection of it; bot comments carry markers and are updated in place; merges pass the head sha
  and releases check the tag first, so re-running a tick repeats no comment, merge or release.
"""

from __future__ import annotations

import copy
import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any

from sdlc_agents import (
    cost,
    designed_tests,
    gates,
    lock,
    machine,
    metrics,
    paths,
    release,
    repo_context,
    state,
)
from sdlc_agents.clock import seconds_between
from sdlc_agents.definitions import PO_LABEL
from sdlc_agents.foundry import (
    AgentBudgetError,
    AgentOutput,
    AgentRunError,
    RetryPolicy,
    Section,
    call_with_retry,
    run_agent,
)
from sdlc_agents.ledger import events as ledger_events
from sdlc_agents.ledger import model as ledger_model
from sdlc_agents.ledger.emitter import Emitter, NullEmitter
from sdlc_agents.machine import Action, Context, Kind
from sdlc_agents.paths import is_test_path
from sdlc_agents.ports import (
    OWNER,
    REPO,
    Budget,
    ClockPort,
    Comment,
    FoundryPort,
    GitHubError,
    GitHubPort,
    Issue,
    PullRequest,
    SecretsPort,
)
from sdlc_agents.sanitise import (
    encode_marker_json,
    fenced,
    one_line,
    parse_json_strict,
    redact_secrets,
    sanitise_markdown,
)
from sdlc_agents.state import State

CODER_AGENT = "sdlc-coder"
TEST_CMD = "npm test"
CODER_WORKDIR = "app"
CODER_PHASES = frozenset({"setup", "tests", "implement", "push", "pr"})
CODER_ENGINES = frozenset({"agy", "agy-unrestricted", "loop"})
CODER_REASONS = frozenset({
    "tests-not-red", "scope-violation", "max-iterations", "engines-exhausted", "cost-cap", "install-failed",
    "branch-missing", "branch-conflict", "interrupted", "deadline", "cancelled", "error", "tests-invalid",
    "sandbox-unavailable", "lease-held", "lease-error", "engine-unavailable", "internal-error",
    "invalid-allowed-paths",
})
UNREPORTED_CODER_SLACK_S = 900    # one missed poll is normal; longer gaps are billed as estimated time
UNREPORTED_STATUSES = ("running", "starting", "start-unconfirmed", "lease-held")
CODER_STATUSES = ("running", "succeeded", "failed", "timeout", "cancelled")
LEASE_PREFIX = "agent-lease/"     # ref the coder creates per issue; 422 there means a live job holds it
START_RESEND_AFTER_S = 600        # two ticks before an unconfirmed start (no session) is sent again
MAX_START_RESENDS = 1
SESSION_GONE_POLLS = 2          # consecutive session_not_accessible polls before a job counts as lost
CODER_LOG_CHARS = 3_000         # log tail copied onto the issue when a coder job fails
MAX_ENGINE_EVENTS = 20
MAX_TEST_FILES_SCANNED = 60       # test files read at the PR head to find text a PR removed
CI_LOG_CHARS = 20_000            # tail of a failing check log handed to triage and the coder
MAX_TRANSIENT_TICKS = 24          # consecutive deferred ticks before an object is escalated
CODER_MAX_MODEL_USD = 0.5
CODER_MAX_ITERATIONS = 5
RESERVE_S = 45                    # wall time kept back for metrics and unlocking
COMMENT_LIMIT = 65_000            # GitHub rejects comment bodies over 65,536 chars
PAGES_WORKFLOW = "pages.yml"
LEDGER_HEARTBEAT_S = 540          # no activity: still tell the ledger every ~2 ticks that the loop is alive
LEDGER_RECONCILE_S = 3600         # ask the ledger to rebuild from GitHub about hourly (repairs missed events)
QUIET_ACTIONS = frozenset({"none", "noop", "wait", "halt", "ignore"})

UI_PROOF_MARKER = "<!-- ui-proof:v1 -->"
UI_TESTER_MARKER_PREFIX = "<!-- ui-tester:v1 "
UI_TESTER_FEATURE_FLAG = "UI_TESTER_ENABLED"


def is_ui_tester_enabled() -> bool:
    return os.environ.get(UI_TESTER_FEATURE_FLAG, "0").strip().lower() in ("1", "true", "yes", "on")


def render_ui_tester_marker(head: str) -> str:
    return f"<!-- ui-tester:v1 {head} -->"

CODER_LOG_MARKER = "<!-- sdlc-coder-log:v1"
TESTS_MARKER = "<!-- sdlc-tests:v1\n"
_TESTS_RE = re.compile(r"\A<!-- sdlc-tests:v1\n(.*?)\n-->", re.DOTALL)
_SCENARIO_RE = re.compile(r"<!-- scenario: (a|b|c|d|d-maintenance) -->")


class StepError(RuntimeError):
    """A step could not complete; recorded against the object and retried on a later tick."""


def is_transient(exc: BaseException) -> bool:
    """Worth retrying later and never held against the object: rate limits, timeouts, 5xx, dropped
    connections. Bad answers, refusals and contract violations are not transient."""
    if isinstance(exc, AgentRunError):
        return exc.transient
    if isinstance(exc, GitHubError):
        return exc.status in (408, 429) or exc.status >= 500 or (exc.status == 403 and "rate limited" in str(exc))
    return isinstance(exc, OSError)        # URLError, TimeoutError, ConnectionError


@dataclass
class ObjectReport:
    number: int
    kind: str
    action: str
    result: str           # ok | error | skipped | ignored
    detail: str = ""


@dataclass
class TickReport:
    started_at: str
    finished_at: str = ""
    lock: str = ""
    objects: list[ObjectReport] = field(default_factory=list)
    model_calls: int = 0
    calls: list[dict[str, Any]] = field(default_factory=list)   # per model call: number, agent, in, out, usd
    usd_this_tick: float = 0.0          # model spend billed to objects this tick
    orchestrator_usd: float = 0.0       # this tick's own hosted compute
    total_usd: float = 0.0
    metrics_written: bool = False
    ledger_usd: float = 0.0             # this tick's call to the state-keeper agent
    ledger: str = ""                    # emitted | quiet | error
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Object:
    item: Issue
    comments: list[Comment]
    state_comment: Comment | None
    state: State | None
    committed: dict[str, Any] | None = None    # the state as last saved, for rollback

    @property
    def kind(self) -> str:
        return "pr" if self.item.is_pull_request else "issue"

    @property
    def st(self) -> State:
        """The state, which every step has (the tick creates it before the first step)."""
        if self.state is None:
            raise StepError(f"#{self.item.number} has no state")
        return self.state


def _require_pr(ctx: Context) -> PullRequest:
    if ctx.pr is None:
        raise StepError(f"#{ctx.number} has no pull request")
    return ctx.pr


def run_tick(
    github: GitHubPort,
    foundry: FoundryPort,
    secrets: SecretsPort,
    clock: ClockPort,
    budget_wall_s: int = 240,
    *,
    budget: Budget | None = None,
    sleep: Callable[[float], None] = time.sleep,
    emitter: Emitter | None = None,
    ui_tester_enabled: bool | None = None,
) -> TickReport:
    """Run one bounded tick and return its report. Never raises. `sleep` waits out retry backoff.

    `secrets` is part of the hosted entrypoint contract; the adapters already hold what they need,
    so the tick itself reads no secret.
    """
    del secrets
    report = TickReport(started_at=clock.now_iso())
    try:
        held = lock.acquire(github, clock, holder=f"tick {report.started_at}")
    except lock.LockHeld as exc:
        report.lock = "held"
        report.errors.append(str(exc))
        report.finished_at = clock.now_iso()
        return report
    except Exception as exc:
        report.lock = "error"
        report.errors.append(f"lock: {type(exc).__name__}: {exc}")
        report.finished_at = clock.now_iso()
        return report
    report.lock = "took-over-stale" if held.took_over_stale else "acquired"
    try:
        _Tick(
            github,
            foundry,
            clock,
            report,
            budget or Budget(),
            budget_wall_s,
            sleep,
            emitter or NullEmitter(),
            ui_tester_enabled=ui_tester_enabled,
        ).run()
    except Exception as exc:
        report.errors.append(f"tick: {type(exc).__name__}: {exc}")
    finally:
        try:
            lock.release(github, held)
        except Exception as exc:
            report.errors.append(f"unlock: {type(exc).__name__}: {exc}")
    report.finished_at = clock.now_iso()
    return report


def _has_sdlc_labels(item: Issue) -> bool:
    return any(label.startswith(("stage:", "escalated:")) for label in item.labels)


def _object_type(item: Issue, st: State | None) -> str:
    if st is not None:
        return st.type
    if item.is_pull_request:
        return "maintenance"
    for type_ in state.TYPES:
        if f"type:{type_}" in item.labels:
            return type_
    return "feature"


_ERROR_LINE = re.compile(r"error|fail|expected|assert|exception|TS\d{4}|\u2717|\u00d7", re.IGNORECASE)


def _session_gone(exc: AgentRunError) -> bool:
    """The platform no longer has the coder's session (HTTP 400/404 session_not_accessible)."""
    return exc.http_status in (400, 404) and "session_not_accessible" in str(exc)


def _engine_events(events: list[Any]) -> list[dict[str, Any]]:
    """The coder's per-iteration engine trouble, bounded and redacted, for the state comment."""
    kept = []
    for event in events[-MAX_ENGINE_EVENTS:]:
        if isinstance(event, dict):
            kept.append({str(k)[:40]: v if isinstance(v, int | float | bool) or v is None
                         else one_line(redact_secrets(str(v)), 300) for k, v in event.items()})
    return kept


def _error_lines(log: str, limit: int = 20) -> str:
    """The lines of a CI log that say what broke (tsc, vitest, Playwright), else its last lines."""
    lines = [ln.rstrip() for ln in log.splitlines() if ln.strip()]
    picked = [ln for ln in lines if _ERROR_LINE.search(ln)][:limit] or lines[-limit:]
    return "\n".join(one_line(ln, 300) for ln in picked)


def _allowed(value: object, allowed: frozenset[str]) -> str | None:
    """value if it is one of the allowed words, None if absent, else "other"."""
    if value is None or value == "":
        return None
    return value if isinstance(value, str) and value in allowed else "other"


def _scenario(body: str) -> str | None:
    match = _SCENARIO_RE.search(body)
    return match.group(1) if match else None


class _Tick:
    def __init__(self, github: GitHubPort, foundry: FoundryPort, clock: ClockPort, report: TickReport,
                 budget: Budget, budget_wall_s: int, sleep: Callable[[float], None], emitter: Emitter,
                 ui_tester_enabled: bool | None = None):
        self.sleep = sleep
        self.emitter = emitter
        self.ui_tester_enabled = (
            is_ui_tester_enabled() if ui_tester_enabled is None else ui_tester_enabled
        )
        self.pending_events: dict[int, dict[str, Any]] = {}     # one ticket.updated per object, the latest
        self.deferred: dict[int, str] = {}
        self.streaks: dict[int, int] = {}       # consecutive ticks each object was deferred
        self.github = github
        self.foundry = foundry
        self.clock = clock
        self.report = report
        self.budget = budget
        self.started = clock.monotonic()
        self.deadline = self.started + budget_wall_s - RESERVE_S
        self.objects: list[_Object] = []
        self.previous = metrics.Ledger()

    # -- loop -------------------------------------------------------------------

    def run(self) -> None:
        self._load()
        # The ledger never shrinks: an object that drops out of the listing keeps its spend.
        ledger = metrics.previous_totals(self.github)
        if ledger is None:
            self.budget.known = False        # fail closed: no model call, no coder start this tick
            self.report.errors.append("metrics.json is unreadable: spend unknown, spending steps halted")
        self.previous = ledger or metrics.Ledger()
        objects_usd = sum(self._object_usd(o) for o in self.objects)
        self.budget.usd_total = max(objects_usd + self.previous.orchestrator_usd + self.previous.ledger_usd,
                                    self.previous.usd)
        # Coder polls first: they are cheap and keep the coder's sandbox session alive.
        self.objects.sort(key=lambda o: (0 if o.state and o.state.stage == state.BUILDING else 1, o.item.number))
        for obj in self.objects:
            if self.clock.monotonic() > self.deadline:
                self._note(obj, "none", "skipped", "wall budget used")
                if obj.item.number in self.previous.deferrals:      # not tried: the streak carries over
                    self.streaks[obj.item.number] = self.previous.deferrals[obj.item.number]
                continue
            self._step(obj)
        ledger_usd, marks = self._emit_ledger()
        tick_usd = round(cost.orchestrator_tick_usd(self.clock.monotonic() - self.started), 6)
        self.report.orchestrator_usd = tick_usd
        self.report.ledger_usd = ledger_usd
        self.budget.usd_total += tick_usd + ledger_usd
        self.report.total_usd = round(self.budget.usd_total, 6)
        self._write_metrics(tick_usd, ledger_usd, marks)

    def _load(self) -> None:
        for item in sorted(self.github.list_issues(state="all"), key=lambda i: i.number):
            relevant = not item.is_pull_request or gates.MAINTENANCE_LABEL in item.labels
            if not relevant:
                continue          # agent PRs are driven through their issue
            if item.author != OWNER:
                if item.state == "open":
                    self.report.objects.append(ObjectReport(item.number, "pr" if item.is_pull_request else "issue",
                                                            Kind.IGNORE.value, "ignored", f"author {item.author}"))
                continue
            if item.state == "closed" and not _has_sdlc_labels(item):
                continue
            comments = self.github.list_comments(item.number)
            try:
                comment, st = state.find(comments)
            except ValueError as exc:
                self.report.objects.append(ObjectReport(item.number, "issue", "load", "error", str(exc)))
                self.budget.known = False    # its spend is unknown, so the total is too: fail closed
                continue
            self.objects.append(_Object(item, comments, comment, st))

    def _step(self, obj: _Object) -> None:
        action = Action(Kind.NOOP)
        try:
            ctx = self._context(obj)
            action = machine.next_action(ctx)
            if action.kind in (Kind.NOOP, Kind.WAIT, Kind.HALT):
                if action.record:
                    if obj.state is None:
                        obj.state = State.new(obj.item.number, ctx.object_type, _scenario(obj.item.body))
                    obj.state.data.update(action.record)
                    self._save(obj)
                elif obj.state is not None:
                    self._sync_labels(obj)
                self._note(obj, action.kind.value, "ok", action.reason)
                self._maybe_ui_tester(obj, ctx)
                return
            if action.kind is Kind.IGNORE:
                self._note(obj, action.kind.value, "ignored", action.reason)
                return
            if obj.state is None:
                obj.state = State.new(obj.item.number, ctx.object_type, _scenario(obj.item.body))
            obj.committed = copy.deepcopy(obj.state.data)
            detail = getattr(self, f"_do_{action.kind.value.replace('-', '_')}")(obj, ctx, action)
            self._note(obj, action.kind.value, "ok", detail or action.reason)
            self._maybe_ui_tester(obj, ctx)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, AgentBudgetError):
                # A cap was reached part way through the step: keep the spend, count no failure;
                # the next tick escalates cost-cap or halts.
                self._note(obj, action.kind.value, "capped", message)
                self._defer(obj)
            elif is_transient(exc):
                self._transient(obj, _object_type(obj.item, obj.state), action, message)
            else:
                self._note(obj, action.kind.value, "error", message)
                self._record_failure(obj, action, message)

    def _transient(self, obj: _Object, object_type: str, action: Action, message: str) -> None:
        """Defer, but not for ever: after MAX_TRANSIENT_TICKS consecutive deferred ticks escalate."""
        number = obj.item.number
        streak = self.previous.deferrals.get(number, 0) + 1
        if streak < MAX_TRANSIENT_TICKS:
            self._note(obj, action.kind.value, "deferred", message)
            self.deferred[number] = one_line(message, 300)
            self.streaks[number] = streak
            self._defer(obj)
            return
        self._note(obj, action.kind.value, "error", f"transient failures for {streak} consecutive ticks: {message}")
        try:
            self._roll_back(obj)
            if obj.state is None:
                obj.state = State.new(number, object_type, _scenario(obj.item.body))
            self._escalate(obj, state.ESC_AGENT_ERROR, [
                f"{action.kind.value} kept failing transiently for {streak} consecutive ticks", one_line(message, 200)])
            self._save(obj)
        except Exception as exc:
            self.report.errors.append(f"#{number}: could not escalate: {type(exc).__name__}: {exc}")

    def _roll_back(self, obj: _Object) -> bool:
        """Restore the last saved state, keeping what was spent. Returns whether spend was added."""
        if obj.state is None or obj.committed is None:
            return False
        spent = copy.deepcopy(obj.state.data["cost"])
        obj.state.data = copy.deepcopy(obj.committed)
        added = spent != obj.state.data["cost"]
        obj.state.data["cost"] = spent
        return added

    def _defer(self, obj: _Object) -> None:
        """A transient failure: leave the object as it was for the next tick, counting nothing."""
        try:
            if self._roll_back(obj):
                self._save(obj)      # only to persist spend; stage, labels and failures are unchanged
            elif obj.state_comment is None:
                obj.state = None     # nothing was ever written for this object: keep it that way
        except Exception as exc:
            self.report.errors.append(f"#{obj.item.number}: could not defer: {type(exc).__name__}: {exc}")

    def _record_failure(self, obj: _Object, action: Action, message: str) -> None:
        if obj.state is None or obj.committed is None:
            return
        # Roll back to the last saved state; keep what was spent and count the failure.
        self._roll_back(obj)
        try:
            obj.state.record_failure(action.kind.value, message)
            self._save(obj)
        except Exception as exc:
            self.report.errors.append(f"#{obj.item.number}: could not record failure: {type(exc).__name__}: {exc}")

    def _note(self, obj: _Object, action: str, result: str, detail: str) -> None:
        self.report.objects.append(ObjectReport(obj.item.number, obj.kind, action, result, one_line(detail, 400)))

    # -- context ------------------------------------------------------------------

    def _context(self, obj: _Object) -> Context:
        st = obj.state
        stage = st.stage if st else None
        pr: PullRequest | None = None
        checks: dict[str, str] = {}
        touches: bool | None = None
        terminal = bool(st and st.escalation) or any(label.startswith("escalated:") for label in obj.item.labels)
        if obj.item.author == OWNER and not terminal:
            if obj.kind == "pr" and stage not in (state.MERGED, state.RELEASED, state.BUILDING):
                pr = self.github.get_pull(obj.item.number)
            elif obj.kind == "issue" and stage == state.IN_REVIEW and st and st.get("pr"):
                pr = self.github.get_pull(int(st.data["pr"]["number"]))
            if pr is not None and pr.state == "open":
                checks = gates.check_summary(self.github.get_check_runs(pr.head_sha), pr.number)
                if obj.kind == "pr" and stage is None and "test" in gates.failed(checks):
                    commits = self.github.list_pull_commits(pr.number)
                    touches = any(is_test_path(f) for c in commits for f in c.files)
        return Context(
            kind="pr" if obj.kind == "pr" else "issue",
            number=obj.item.number, author=obj.item.author, labels=frozenset(obj.item.labels),
            is_open=obj.item.state == "open", object_type=_object_type(obj.item, st), state=st,
            now=self.clock.now_iso(), budget=self.budget, pr=pr, checks=checks, pr_touches_tests=touches,
            object_usd=self._object_usd(obj),
        )

    # -- persistence --------------------------------------------------------------

    def _save(self, obj: _Object) -> None:
        body = state.render(obj.st)
        if obj.state_comment is None:
            obj.state_comment = self.github.create_comment(obj.item.number, body)
            obj.comments.append(obj.state_comment)
        elif obj.state_comment.body != body:
            self.github.update_comment(obj.state_comment.id, body)
            obj.state_comment = Comment(obj.state_comment.id, obj.state_comment.author, body,
                                        obj.state_comment.created_at)
        obj.committed = copy.deepcopy(obj.st.data)
        self._sync_labels(obj)
        self._queue_ticket(obj)

    def _sync_labels(self, obj: _Object) -> None:
        st = obj.st
        current = set(obj.item.labels)
        wanted = {f"type:{st.type}"}
        if st.stage:
            wanted.add(st.stage)
        if st.escalation:
            wanted.add(st.escalation)
        if triage := st.get("triage"):
            wanted |= {"bug:triaged", f"severity:{triage['severity']}", f"owner:{triage['owner']}"}
        stale = sorted(label for label in current if label.startswith("stage:") and label != st.stage)
        add = tuple(sorted(wanted - current))
        if add:
            self.github.add_labels(obj.item.number, add)
        for label in stale:
            self.github.remove_label(obj.item.number, label)
        if add or stale:
            labels = tuple(sorted((current | set(add)) - set(stale)))
            obj.item = Issue(**{**asdict(obj.item), "labels": labels})

    def _upsert(self, number: int, comments: list[Comment], marker: str, body: str,
                existing: Comment | None = None) -> Comment:
        """Create the bot comment that starts with `marker` (or the given existing one), or update it in place."""
        for i, comment in enumerate(comments):
            if comment.author == OWNER and (comment.id == existing.id if existing else comment.body.startswith(marker)):
                if comment.body != body:
                    self.github.update_comment(comment.id, body)
                    comments[i] = Comment(comment.id, comment.author, body, comment.created_at)
                return comments[i]
        created = self.github.create_comment(number, body)
        comments.append(created)
        return created

    # -- model calls --------------------------------------------------------------

    def _object_usd(self, obj: _Object) -> float:
        """Best known spend: the state comment, the published ledger, and coder time not yet reported."""
        st = obj.state
        known = max(st.usd if st else 0.0, self.previous.objects.get(obj.item.number, 0.0))
        coder = (st.get("coder") or {}) if st else {}
        since = coder.get("unconfirmed_at") or coder.get("started_at")
        if st and not st.escalation and coder.get("status") in UNREPORTED_STATUSES and since:
            # Status calls can fail, and a start can be unconfirmed; the coder may run (and bill) meanwhile.
            wall = seconds_between(since, self.clock.now_iso())
            unreported = wall - int(coder.get("elapsed_s", 0)) - UNREPORTED_CODER_SLACK_S
            known += cost.coder_usd(max(unreported, 0))
        return known

    def _spend_stop(self, obj: _Object) -> str | None:
        """Why no further model call may be made for obj now, or None."""
        if not self.budget.known:
            return "spend cannot be determined"
        if self._object_usd(obj) >= self.budget.usd_cap_issue:
            return f"issue cap {self.budget.usd_cap_issue:.2f} USD reached"
        if self.budget.usd_total >= self.budget.usd_cap_total:
            return f"total cap {self.budget.usd_cap_total:.2f} USD reached"
        return None

    def _retry(self) -> RetryPolicy:
        return RetryPolicy(sleep=self.sleep, monotonic=self.clock.monotonic, deadline=self.deadline)

    def _call(self, obj: _Object, agent: str, sections: list[Section],
              check: Callable[[dict[str, Any]], None] | None = None,
              image_urls: list[str] | None = None) -> AgentOutput:
        """Run a prompt agent with retries; every answered call (valid or not) is billed to the object."""
        return run_agent(self.foundry, agent, sections, retry=self._retry(), allow=lambda: self._spend_stop(obj),
                         check=check,
                         bill=lambda name, tokens_in, tokens_out: self._bill(obj, name, tokens_in, tokens_out),
                         image_urls=image_urls)

    def _hosted(self, body: dict[str, Any], session_id: str | None,
                retry_if: Callable[[AgentRunError], bool] | None = None) -> tuple[dict[str, Any], str]:
        return call_with_retry(lambda: self.foundry.invoke_hosted(CODER_AGENT, body, session_id=session_id),
                               self._retry(), retry_if)

    def _bill(self, obj: _Object, agent: str, input_tokens: int, output_tokens: int) -> None:
        usd = cost.record_call(obj.st, agent, input_tokens, output_tokens)
        self.budget.usd_total += usd
        self.report.usd_this_tick = round(self.report.usd_this_tick + usd, 8)
        self.report.model_calls += 1
        self.report.calls.append({"number": obj.item.number, "agent": agent, "in": input_tokens,
                                  "out": output_tokens, "usd": usd})

    @staticmethod
    def _issue_section(item: Issue) -> Section:
        return Section("issue", f"#{item.number} {item.title}\n\n{item.body}")

    @staticmethod
    def _spec_section(st: State) -> Section:
        quality = st.get("quality") or {}
        criteria = "\n".join(f"- {c}" for c in quality.get("acceptance_criteria", []))
        return Section("spec", f"summary: {quality.get('summary', '')}\nacceptance criteria:\n{criteria}")

    # -- steps --------------------------------------------------------------------

    def _do_triage(self, obj: _Object, ctx: Context, action: Action) -> str:
        st = obj.st
        data = self._call(obj, "sdlc-triage", [self._issue_section(obj.item)]).data or {}
        st.data["triage"] = {k: data[k] for k in ("severity", "owner", "summary", "suspected_area")}
        st.data["failures"] = None
        self._upsert(obj.item.number, obj.comments, "<!-- sdlc-triage:v1 -->", "\n".join([
            "<!-- sdlc-triage:v1 -->",
            f"**Triage** (sdlc-triage): severity `{data['severity']}`, owner `{data['owner']}`.",
            "",
            f"- Summary: {sanitise_markdown(one_line(data['summary'], 200))}",
            f"- Suspected area: {sanitise_markdown(one_line(data['suspected_area'], 200))}",
            f"- Rationale: {sanitise_markdown(one_line(data['rationale'], 300))}",
        ]))
        self._save(obj)
        return f"severity {data['severity']}, owner {data['owner']}"

    def _do_gate(self, obj: _Object, ctx: Context, action: Action) -> str:
        return self._score(obj)

    def _do_rescore(self, obj: _Object, ctx: Context, action: Action) -> str:
        return self._score(obj)

    def _score(self, obj: _Object) -> str:
        st = obj.st
        quality = st.get("quality") or {"score": None, "rounds": 0, "questions": [], "answers": [], "history": []}
        if quality.get("answers"):
            quality.setdefault("history", []).append({
                "round": quality["rounds"], "score": quality.get("score"),
                "questions": quality["questions"], "answers": quality["answers"],
            })
            quality["questions"], quality["answers"] = [], []
        sections = [self._issue_section(obj.item)]
        clarifications = "\n\n".join(
            f"Round {h['round']}\n"
            + "\n".join(f"Q: {q}\nA: {a}" for q, a in zip(h["questions"], h["answers"], strict=False))
            for h in quality.get("history", [])
        )
        if clarifications:
            sections.append(Section("clarifications", clarifications))
        data = self._call(obj, "sdlc-req-gate", sections).data or {}
        quality.update({
            "score": data["score"], "criteria": data["criteria"], "summary": data["summary"],
            "acceptance_criteria": data["acceptance_criteria"],
        })
        st.data["quality"] = quality
        outcome = machine.after_score(data["score"], quality["rounds"])
        now = self.clock.now_iso()
        if outcome.stage == state.NEEDS_REFINEMENT:
            quality["rounds"] += 1
            quality["questions"] = data["questions"]
            marker = f"<!-- sdlc-questions:v1 round={quality['rounds']} -->"
            self._upsert(obj.item.number, obj.comments, marker, "\n".join([
                marker,
                f"**Requirement quality** (sdlc-req-gate): {data['score']} / 100, below the 80 needed to build. "
                f"Clarifying questions, round {quality['rounds']}:",
                "",
                *(f"{i}. {sanitise_markdown(one_line(q, 300))}" for i, q in enumerate(data["questions"], 1)),
            ]))
            st.enter(state.NEEDS_REFINEMENT, now)
        elif outcome.stage == state.READY:
            st.enter(state.READY, now)
        else:
            self._escalate(obj, outcome.escalate or state.ESC_REQUIREMENTS, [outcome.reason])
        self._save(obj)
        return f"score {data['score']}"

    def _do_answer(self, obj: _Object, ctx: Context, action: Action) -> str:
        st = obj.st
        quality = st.section("quality")
        questions = quality.get("questions", [])
        listing = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
        data = self._call(obj, "sdlc-product-owner",
                          [self._issue_section(obj.item), Section("questions", listing)]).data or {}
        answers = [a["answer"] for a in data["answers"]]
        quality["answers"] = answers
        marker = f"<!-- sdlc-po:v1 round={quality.get('rounds', 0)} -->"
        lines = [marker, f"{PO_LABEL} Answers to the round {quality.get('rounds', 0)} questions.", ""]
        for i, item in enumerate(data["answers"], 1):
            lines += [f"**Q{i}.** {sanitise_markdown(one_line(item['question'], 300))}", "",
                      sanitise_markdown(item["answer"]), ""]
        self._upsert(obj.item.number, obj.comments, marker, "\n".join(lines).rstrip() + "\n")
        st.data["failures"] = None
        self._save(obj)
        return f"{len(answers)} answers"

    def _do_feasibility(self, obj: _Object, ctx: Context, action: Action) -> str:
        st = obj.st
        data = self._call(obj, "sdlc-feasibility", [self._issue_section(obj.item), self._spec_section(st)]).data or {}
        st.data["feasibility"] = {k: data[k] for k in ("suitable", "reasons", "risk", "affected_paths")}
        outcome = machine.after_feasibility(data["suitable"])
        if outcome.stage:
            st.enter(outcome.stage, self.clock.now_iso())
        else:
            self._escalate(obj, state.ESC_NOT_SUITABLE, data["reasons"])
        self._save(obj)
        return "suitable" if data["suitable"] else "not suitable"

    def _do_design_tests(self, obj: _Object, ctx: Context, action: Action) -> str:
        st = obj.st
        mode = "bugfix" if st.type == "bug" else "feature"
        sections = [Section("mode", mode, trusted=True), self._issue_section(obj.item), self._spec_section(st)]
        tree = self.github.list_tree("main")
        known = set(tree)
        cache: dict[str, str | None] = {}

        def read(path: str) -> str | None:
            if path not in cache:
                cache[path] = self.github.get_file(path, ref="main") if path in known else None
            return cache[path]

        # Hand over the file list and the most relevant files, so the model rarely needs a tool call.
        listing, files = repo_context.build(tree, f"{obj.item.title}\n{obj.item.body}\n{self._spec_section(st).text}",
                                            read)
        if listing:
            sections += [Section("repo_files", listing), Section("source_files", files)]
        repair = st.get("tests_repair") or {}
        if repair.get("pending"):
            previous = "\n\n".join(f"=== FILE {t['path']} ===\n{t['content']}" for t in self._designed_tests(obj))
            sections += [
                Section("repair", "Your previous tests (section previous_tests) were invalid when the coder "
                                  "ran them; the errors are in section repair_reason. Write corrected tests.",
                        trusted=True),
                Section("previous_tests", previous),
                Section("repair_reason", str(repair.get("errors", ""))),
            ]

        def check(data: dict[str, Any]) -> None:
            tests = data["tests"]
            errors = [f"{t['path']}: already exists on main" for t in tests if t["path"] in known]
            errors += designed_tests.lint(tests, known, read)
            if errors:
                raise ValueError("; ".join(errors[:12]))

        data = self._call(obj, "sdlc-test-designer", sections, check=check).data or {}
        tests = [{"path": t["path"], "content": t["content"]} for t in data["tests"]]
        body = "\n".join([
            f"{TESTS_MARKER}{encode_marker_json({'tests': tests})}\n-->",
            f"**Tests designed first** (sdlc-test-designer, {mode}). The coder commits these before any "
            "implementation and they must fail on main:",
            "",
            *(f"- `{t['path']}`" for t in tests),
            "",
            f"Rationale: {sanitise_markdown(one_line(data['rationale'], 800))}",
        ])
        if len(body) > COMMENT_LIMIT:
            raise StepError(f"designed tests are {len(body)} chars, over the comment limit")
        self._upsert(obj.item.number, obj.comments, TESTS_MARKER, body)
        st.data["tests"] = {"files": [t["path"] for t in tests]}
        if repair:
            repair["pending"] = False
        st.enter(state.TESTS_WRITTEN, self.clock.now_iso())
        self._save(obj)
        return f"{len(tests)} test file(s)"

    def _designed_tests(self, obj: _Object) -> list[dict[str, str]]:
        for comment in obj.comments:
            if comment.author == OWNER and comment.body.startswith(TESTS_MARKER):
                match = _TESTS_RE.match(comment.body)
                if match:
                    return list(parse_json_strict(match.group(1))["tests"])
        raise StepError("no designed tests comment found")

    def _do_start_coder(self, obj: _Object, ctx: Context, action: Action) -> str:
        st = obj.st
        previous = st.get("coder") or {}
        mode = str(action.mode)
        if previous.get("status") == "starting" and previous.get("mode") == mode:
            attempts = int(previous["attempts"])       # the last start provably never left: same job id
        else:
            attempts = int(previous.get("attempts", 0)) + 1
        job = self._coder_job(obj, ctx, mode, attempts)
        if mode in ("feature", "bugfix"):
            old = previous.get("branch")
            if old and old != job["branch"] and str(old).startswith(f"agent/issue-{obj.item.number}"):
                self.github.delete_branch(str(old))   # the abandoned branch with the invalid tests
        # Write ahead: the job id (and any session) is saved before the call, so nothing that happens
        # to the call can lead to a second job under another id.
        resuming = previous.get("job_id") == job["job_id"]
        pr = st.get("pr") or {}
        st.data["coder"] = {
            "job_id": job["job_id"], "session_id": previous.get("session_id") if resuming else None,
            "mode": mode, "attempts": attempts, "started_at": previous.get("started_at") if resuming else None,
            "status": "starting", "engine": None, "iterations": 0, "phase": None, "elapsed_s": 0,
            "resumes": int(previous.get("resumes", 0)) if resuming else 0,
            "prior_seconds": previous.get("prior_seconds", 0) if resuming else st.data["cost"]["coder_seconds"],
            "prior_model_usd": previous.get("prior_model_usd", 0.0) if resuming
            else st.data["cost"].get("coder_model_usd", 0.0),
            "branch": job["branch"], "base_head": pr.get("head") if mode == "revise" else
            (ctx.pr.head_sha if mode == "maintenance" and ctx.pr else None),
            "resends": 0, "lease": "requested",
        }
        self._save(obj)
        return self._send_start(obj, job)

    def _coder_job(self, obj: _Object, ctx: Context, mode: str, attempts: int) -> dict[str, Any]:
        """The start payload, rebuilt the same way for a resend."""
        st = obj.st
        quality = st.get("quality") or {}
        spec = {"acceptance_criteria": quality.get("acceptance_criteria", []), "notes": quality.get("summary", "")}
        job: dict[str, Any] = {
            "job_id": f"j-{'pr' if obj.kind == 'pr' else ''}{obj.item.number}-{attempts}", "repo": REPO,
            "base": "main", "mode": mode,
            "issue": {"number": obj.item.number, "title": obj.item.title, "body": obj.item.body},
            "spec": spec, "tests": [], "test_cmd": TEST_CMD, "workdir": CODER_WORKDIR,
            "max_iterations": CODER_MAX_ITERATIONS, "deadline_s": machine.CODER_DEADLINE_S,
            "allowed_paths": ["app/"],
            # The coder's fallback engine spends model tokens too: give it what is left under the cap.
            "max_model_usd": round(min(CODER_MAX_MODEL_USD,
                                       max(self.budget.usd_cap_issue - self._object_usd(obj), 0.0)), 4),
        }
        findings = (st.get("review") or {}).get("findings", [])
        review_notes = "\n".join(f"- [{f['severity']}] {f['detail']}" for f in findings)
        if mode in ("feature", "bugfix"):
            # After a test repair the coder starts again from main on a new branch, so the PR still
            # opens with exactly one test commit.
            rounds = int((st.get("tests_repair") or {}).get("rounds", 0))
            job["branch"] = f"agent/issue-{obj.item.number}" + (f"-r{rounds}" if rounds else "")
            job["tests"] = self._designed_tests(obj)
        elif mode == "revise":
            pr = st.data["pr"]
            job.update(branch=pr["branch"], pr={"number": pr["number"]})
            head = ctx.pr.head_sha if ctx.pr else pr.get("head")
            ci = st.get("ci_revise") or {}
            if ci.get("head") == head and ci.get("action") == "revise":
                spec["notes"] = str(ci["notes"])           # CI error lines (untrusted; the coder wraps them)
            else:
                spec["notes"] = f"Address the reviewer's findings:\n{review_notes}"
        else:
            pr_obj = ctx.pr or self.github.get_pull(obj.item.number)
            ci = st.get("ci_triage") or {}
            job.update(branch=pr_obj.head_ref, pr={"number": pr_obj.number}, allowed_paths=ci.get("test_files") or [])
            job["spec"] = {
                "acceptance_criteria": ["The test check passes", "Only test files change"],
                "notes": "\n".join(filter(None, [ci.get("explanation", ""), review_notes])),
            }
        return job

    def _send_start(self, obj: _Object, job: dict[str, Any]) -> str:
        """POST start. Without a session id a start is retried only if it provably never left: a
        resent start could land in a fresh sandbox that never saw the job and run it twice."""
        st = obj.st
        coder = st.data["coder"]
        session = coder.get("session_id")
        now = self.clock.now_iso()
        try:
            resp, new_session = self._hosted({"op": "start", "job": job}, session,
                                             retry_if=lambda exc: bool(session) or not exc.ambiguous)
        except AgentRunError as exc:
            if not (exc.transient and exc.ambiguous):
                raise
            coder.update(status="start-unconfirmed", unconfirmed_at=coder.get("unconfirmed_at") or now)
            self._save(obj)
            return f"start of {job['job_id']} unconfirmed: {one_line(str(exc), 120)}"
        if resp.get("status") == "failed" and resp.get("reason") == "lease-held" and int(coder.get("resumes", 0)):
            # Resuming an interrupted job in a sandbox that never saw it: the lease is the interrupted
            # job's own, and nothing runs it any more. Free it and start a new attempt instead.
            self._release_lease(obj)
            coder.update(status="retry")
            self._save(obj)
            return f"{job['job_id']} cannot be resumed in this session: a new attempt follows"
        if resp.get("status") == "failed" and resp.get("reason") == "lease-held":
            coder.update(status="lease-held", unconfirmed_at=coder.get("unconfirmed_at") or now)
            self._save(obj)
            return f"{job['job_id']} refused: another coder job holds the lease"
        if resp.get("status") not in ("running", "succeeded"):
            raise StepError(f"coder did not start: {one_line(json.dumps(resp), 200)}")
        coder.update(session_id=new_session, status="running", lease="held", unconfirmed_at=None,
                     started_at=coder.get("started_at") or now)
        st.enter(state.BUILDING, now)
        self._save(obj)
        return f"coder job {job['job_id']} ({job['mode']})"

    def _do_reconcile_coder(self, obj: _Object, ctx: Context, action: Action) -> str:
        """Find out what became of a start whose answer was lost or that a lease refused."""
        st = obj.st
        coder = st.data["coder"]
        waited = seconds_between(coder.get("unconfirmed_at") or self.clock.now_iso(), self.clock.now_iso())
        if coder["status"] == "start-unconfirmed":
            if coder.get("session_id"):
                try:
                    resp, _ = self._hosted({"op": "status", "job_id": coder["job_id"]}, coder["session_id"])
                except AgentRunError as exc:
                    if exc.http_status != 404:
                        raise
                    resp = {}
                if resp.get("status") in CODER_STATUSES:
                    coder.update(status="running", lease="held", unconfirmed_at=None,
                                 started_at=coder.get("started_at") or self.clock.now_iso())
                    st.enter(state.BUILDING, self.clock.now_iso())
                    self._save(obj)
                    return f"start of {coder['job_id']} confirmed by status"
            elif waited < START_RESEND_AFTER_S:
                return "start unconfirmed: waiting before a resend"
            if int(coder.get("resends", 0)) >= MAX_START_RESENDS:
                self._escalate(obj, state.ESC_BUILD_FAILED, [f"coder start of {coder['job_id']} still unconfirmed "
                                                             f"after {MAX_START_RESENDS} resend"])
                self._save(obj)
                return "start unconfirmed after a resend"
            coder["resends"] = int(coder.get("resends", 0)) + 1
            self._save(obj)
            return self._send_start(obj, self._coder_job(obj, ctx, coder["mode"], int(coder["attempts"])))
        # lease-held: an earlier start of this job is running somewhere we cannot ask
        pr = self._finished_by_orphan(obj, coder)
        if pr is not None:
            unreported = seconds_between(coder["unconfirmed_at"], self.clock.now_iso())
            cost.set_coder_spend(st, int(coder.get("prior_seconds", 0)) + unreported,
                                 float(st.data["cost"].get("coder_model_usd", 0.0)))
            self._release_lease(obj)
            self._adopt(obj, pr)
            self._save(obj)
            return f"adopted #{pr.number} from the job holding the lease"
        if waited > machine.CODER_DEADLINE_S + machine.CODER_GRACE_S:
            self._escalate(obj, state.ESC_BUILD_FAILED, [
                f"orphaned coder job for {coder['job_id']}: no result within the deadline, lease swept"])
            self._save(obj)
            return "orphaned job swept"
        return "waiting for the coder job that holds the lease"

    def _adopt(self, obj: _Object, pr: PullRequest) -> None:
        """Take the PR an unreachable job produced into review."""
        obj.st.data["pr"] = {"number": pr.number, "branch": pr.head_ref, "head": pr.head_sha}
        obj.st.data["coder"].update(status="succeeded", unconfirmed_at=None)
        if obj.kind == "issue" and gates.AGENT_PR_LABEL not in pr.labels:
            self.github.add_labels(pr.number, (gates.AGENT_PR_LABEL,))
        obj.st.enter(state.IN_REVIEW, self.clock.now_iso())

    def _finished_by_orphan(self, obj: _Object, coder: dict[str, Any]) -> PullRequest | None:
        """The PR an unreachable job produced: a new owner PR on its branch, or a new head on the PR."""
        if coder.get("mode") in ("feature", "bugfix"):
            matches = [p for p in self.github.list_pulls(state="open")
                       if p.head_ref == coder.get("branch") and p.author == OWNER and p.head_repo == REPO]
            return matches[0] if matches else None
        number = (obj.st.get("pr") or {}).get("number") or obj.item.number
        pr = self.github.get_pull(int(number))
        return pr if pr.head_sha != coder.get("base_head") else None

    def _release_lease(self, obj: _Object) -> None:
        """Delete the coder's lease ref once its job is over (the coder never deletes it)."""
        coder = (obj.st.get("coder") or {}) if obj.state else {}
        if coder and coder.get("lease") != "released":
            self.github.delete_branch(f"{LEASE_PREFIX}{obj.item.number}")
            coder["lease"] = "released"

    def _do_poll_coder(self, obj: _Object, ctx: Context, action: Action) -> str:
        st = obj.st
        coder = st.section("coder")
        try:
            resp, session = self._hosted({"op": "status", "job_id": coder["job_id"]}, coder.get("session_id"))
        except AgentRunError as exc:
            if not _session_gone(exc):
                raise
            coder["gone_polls"] = int(coder.get("gone_polls", 0)) + 1
            if coder["gone_polls"] >= SESSION_GONE_POLLS:
                return self._coder_lost(obj, f"status answered session_not_accessible {coder['gone_polls']} times")
            self._save(obj)
            return "coder session not accessible"
        status = str(resp.get("status", ""))
        if status not in CODER_STATUSES:
            raise StepError(f"coder status unknown: {one_line(json.dumps(resp), 200)}")
        before = json.dumps(st.data, sort_keys=True)
        coder.update({
            # Coder text is allow-listed before it is stored or shown.
            "status": status, "phase": _allowed(resp.get("phase"), CODER_PHASES),
            "engine": _allowed(resp.get("engine"), CODER_ENGINES),
            "iterations": int(resp.get("iterations") or 0), "elapsed_s": int(resp.get("elapsed_s") or 0),
            "session_id": session or coder.get("session_id"), "gone_polls": 0,
        })
        reason = _allowed(resp.get("reason"), CODER_REASONS) or ""
        if isinstance(resp.get("engine_events"), list):
            coder["engine_events"] = _engine_events(resp["engine_events"])
        if status in ("failed", "timeout"):
            self._post_coder_log(obj, coder, reason, resp)
        coder_cost = resp.get("cost") if isinstance(resp.get("cost"), dict) else {}
        idle_tail = cost.CODER_IDLE_S if status != "running" else 0    # billed after the job until the session idles
        cost.set_coder_spend(st, int(coder.get("prior_seconds", 0)) + coder["elapsed_s"] + idle_tail,
                             float(coder.get("prior_model_usd", 0.0)) + float(coder_cost.get("model_usd") or 0.0))
        outcome = machine.after_coder(status, reason)
        if status != "running" and not outcome.resume:
            self._release_lease(obj)     # the job is over: free the issue for its next job
        if outcome.repair_tests:
            self._tests_invalid(obj, str(resp.get("detail") or ""))
        elif outcome.resume:
            # The coder lost its process (sandbox restart): starting the same job id resumes it.
            coder["resumes"] = int(coder.get("resumes", 0)) + 1
            coder["status"] = "starting"
        elif (outcome.retry and self._may_retry(obj, reason, machine.RETRY_LIMITS[reason])) or (
                outcome.fix_paths and self._fixed_paths(obj, ctx)):
            coder["status"] = "retry"     # nothing was pushed: the next tick starts a new job
        elif outcome.stage == state.IN_REVIEW:
            pr = self._coder_pull(obj, coder, resp)
            st.data["pr"] = {"number": pr.number, "branch": pr.head_ref, "head": pr.head_sha}
            if obj.kind == "issue" and gates.AGENT_PR_LABEL not in pr.labels:
                self.github.add_labels(pr.number, (gates.AGENT_PR_LABEL,))
            st.enter(state.IN_REVIEW, self.clock.now_iso())
        elif outcome.escalate:
            detail = resp.get("detail") or resp.get("log_tail") or ""
            tail = sanitise_markdown(one_line(str(detail), 300))
            self._escalate(obj, outcome.escalate, [f"{outcome.reason} in phase {coder.get('phase')}", tail])
        else:
            st.data["failures"] = None
        if json.dumps(st.data, sort_keys=True) != before:
            self._save(obj)
        return f"coder {status}"

    def _may_retry(self, obj: _Object, reason: str, limit: int) -> bool:
        """Count one more new job for `reason`, if its limit and the attempt limit allow it."""
        retries = obj.st.data.setdefault("coder_retries", {})
        if int(retries.get(reason, 0)) >= limit or int(obj.st.data["coder"].get("attempts", 0)) >= \
                machine.MAX_CODER_ATTEMPTS:
            return False
        retries[reason] = int(retries.get(reason, 0)) + 1
        return True

    def _fixed_paths(self, obj: _Object, ctx: Context) -> bool:
        """A maintenance job's allowed_paths matched nothing at the branch head: run the ci-triage file
        validation again on the current head; True when it yields other real paths for one new job."""
        ci = obj.st.get("ci_triage") or {}
        if obj.st.data["coder"].get("mode") != "maintenance" or not ci:
            return False
        head = ctx.pr.head_sha if ctx.pr else self.github.get_pull(obj.item.number).head_sha
        real = self._repo_test_files(head)
        fixed = paths.resolve_test_files([*ci.get("claimed", []), *ci.get("test_files", [])], real,
                                         self.github.get_check_log(str(ci["head"]), "test"))
        if not fixed or fixed == ci.get("test_files") or not self._may_retry(obj, "invalid-allowed-paths", 1):
            return False
        ci["test_files"] = fixed
        return True

    def _tests_asserting_removed_text(self, ref: str, diff: str, repo_tests: list[str]) -> list[str]:
        """Every real test file that still contains text the PR removed from the app."""
        literals = paths.removed_literals(diff)
        if not literals:
            return []
        return [p for p in repo_tests[:MAX_TEST_FILES_SCANNED]
                if any(t in (self.github.get_file(p, ref=ref) or "") for t in literals)]

    def _repo_test_files(self, ref: str) -> list[str]:
        return [p for p in self.github.list_tree(ref)
                if p.startswith(paths.APP_ROOT) and p.endswith(paths.TEST_FILE_SUFFIXES)]

    def _do_coder_lost(self, obj: _Object, ctx: Context, action: Action) -> str:
        self._cancel_coder(obj)
        return self._coder_lost(obj, action.reason)

    def _coder_lost(self, obj: _Object, detail: str) -> str:
        """The job's session is gone or the job overran: free the lease, adopt anything it already
        pushed, else restart it once under a new job id on the same branch (the coder continues from
        a pushed branch); a further loss, or no attempts left, escalates build-failed."""
        st = obj.st
        coder = st.data["coder"]
        wall = seconds_between(coder.get("started_at") or self.clock.now_iso(), self.clock.now_iso())
        cost.set_coder_spend(st, int(coder.get("prior_seconds", 0)) + max(int(coder.get("elapsed_s", 0)), wall),
                             float(st.data["cost"].get("coder_model_usd", 0.0)))
        self._release_lease(obj)
        lost = int(st.data.get("coder_sessions_lost", 0)) + 1
        st.data["coder_sessions_lost"] = lost
        pr = self._finished_by_orphan(obj, coder)
        if pr is not None:
            self._adopt(obj, pr)
            self._save(obj)
            return f"coder-session-lost: adopted #{pr.number} pushed by {coder['job_id']}"
        if lost > machine.MAX_LOST_RESTARTS or int(coder.get("attempts", 0)) >= machine.MAX_CODER_ATTEMPTS:
            self._escalate(obj, state.ESC_BUILD_FAILED, [f"coder-session-lost: {coder['job_id']}: {detail}"])
            self._save(obj)
            return "coder-session-lost: escalated"
        coder.update(status="lost", lost_reason=one_line(detail, 200))
        self._save(obj)
        return f"coder-session-lost: {coder['job_id']} restarts under a new job id"

    def _cancel_coder(self, obj: _Object) -> None:
        """Best effort: the session may already be gone."""
        coder = obj.st.data["coder"]
        try:
            self.foundry.invoke_hosted(CODER_AGENT, {"op": "cancel", "job_id": coder["job_id"]},
                                       session_id=coder.get("session_id"))
            coder["status"] = "cancelled"
        except Exception as exc:
            self.report.errors.append(f"#{obj.item.number}: cancel failed: {type(exc).__name__}: {exc}")

    def _post_coder_log(self, obj: _Object, coder: dict[str, Any], reason: str, resp: dict[str, Any]) -> None:
        """Copy a failed job's evidence onto the issue: the sandbox log does not outlive its session.
        One comment per job id; every coder-supplied text is redacted and fenced."""
        job_id = coder["job_id"]
        marker = f"<!-- sdlc-coder-log:v1 {job_id} -->"
        tail = redact_secrets(str(resp.get("log_tail") or ""))[-CODER_LOG_CHARS:]
        sections = [
            ("engine_events", json.dumps(coder.get("engine_events", []), indent=1), "json"),
            ("red", redact_secrets(str(resp.get("red") or "")), "text"),
            ("green", redact_secrets(str(resp.get("green") or "")), "text"),
            (f"log_tail (last {CODER_LOG_CHARS} characters)", tail, "text"),
        ]
        lines = [marker,
                 f"**Coder job `{job_id}` {coder['status']}** (reason `{reason or 'none'}`, phase "
                 f"`{coder.get('phase')}`, {coder.get('iterations', 0)} iterations, engine `{coder.get('engine')}`). "
                 "Copied here because the sandbox log does not outlive its session.",
                 "", "<details><summary>Coder log</summary>", ""]
        for title, text, info in sections:
            lines += [f"{title}:", "", fenced(text[:CODER_LOG_CHARS], info), ""]
        self._upsert(obj.item.number, obj.comments, marker, "\n".join([*lines, "</details>"]))

    def _ci_failure(self, obj: _Object, ctx: Context) -> str:
        """Red required checks on an agent PR head. A failure inside the designed (protected) test files
        goes back to the test designer; anything else is triaged and revised by the coder, at most
        MAX_CI_REVISIONS rounds; after that the issue is escalated with the last log line."""
        st, pr = obj.st, _require_pr(ctx)
        failed = [n for n in gates.failed(ctx.checks) if ctx.checks[n] != "cancelled"]
        check = next(n for n in machine.CI_REVISABLE if n in failed)
        log = self.github.get_check_log(pr.head_sha, check)[-CI_LOG_CHARS:]
        errors = _error_lines(log)
        last_line = one_line(next((ln for ln in reversed(log.splitlines()) if ln.strip()), "(empty log)"), 200)
        self._record_gates(st, pr.head_sha, ctx.checks)
        designed = list((st.get("tests") or {}).get("files", []))
        if any(path in log or PurePosixPath(path).name in log for path in designed):
            return self._back_to_designer(obj, pr, f"CI check {check} failed in the designed tests:\n{errors}")
        rounds = int((st.get("ci_revise") or {}).get("rounds", 0))
        if rounds >= machine.MAX_CI_REVISIONS:
            self._escalate(obj, state.ESC_BUILD_FAILED, [
                f"required checks failed on {pr.head_sha[:7]}: {', '.join(failed)} after {rounds} CI revise rounds; "
                f"last log line: {last_line}"])
            self._save(obj)
            return "CI revise rounds exhausted"
        files = sorted({f for c in self.github.list_pull_commits(pr.number) for f in c.files})
        data = self._call(obj, "sdlc-ci-triage", [
            Section("pr", f"{pr.title}\n\n{pr.body}"),
            Section("changed_files", "\n".join(files) + "\n\nprotected test files: " + ", ".join(designed)),
            Section("diff", self.github.get_pull_diff(pr.number)),
            Section("log", log, keep_tail=True),
        ]).data or {}
        if data["cause"] == "stale-test" and set(data["test_files"]) & set(designed):
            return self._back_to_designer(obj, pr, f"CI check {check} failed in the designed tests:\n{errors}")
        notes = (f"CI check {check} failed on {pr.head_sha[:7]}. Make it pass without changing any test file.\n"
                 f"Error lines:\n{errors}\n\nTriage: {data['explanation']}")
        st.data["ci_revise"] = {"rounds": rounds + 1, "head": pr.head_sha, "check": check, "action": "revise",
                                "notes": notes[:4000], "last_line": last_line}
        self._upsert(pr.number, self.github.list_comments(pr.number),
                     "<!-- sdlc-ci-triage:v1 -->", "\n".join([
                         "<!-- sdlc-ci-triage:v1 -->",
                         f"**CI triage** (sdlc-ci-triage) for `{pr.head_sha[:7]}`: check `{check}` failed, "
                         f"`{data['cause']}`; the coder revises the PR (round {rounds + 1} of "
                         f"{machine.MAX_CI_REVISIONS}).",
                         "",
                         sanitise_markdown(one_line(data["explanation"], 600)),
                     ]))
        st.data["failures"] = None
        self._save(obj)
        return f"CI revise round {rounds + 1}"

    def _back_to_designer(self, obj: _Object, pr: PullRequest, errors: str) -> str:
        """The designed tests themselves are wrong: close this PR and run the test repair loop; the
        rebuild opens a new PR from a fresh branch."""
        self.github.close_issue(pr.number)            # closes the PR without merging; the issue stays open
        obj.st.data["pr"] = None
        self._tests_invalid(obj, errors)
        self._save(obj)
        return "failure in the designed tests: back to the test designer"

    def _tests_invalid(self, obj: _Object, detail: str) -> None:
        """The coder found the designed tests invalid (they failed for the wrong reason): send them back
        to the test designer, at most MAX_TEST_REPAIRS times, then escalate as an agent error."""
        st = obj.st
        repair = st.get("tests_repair") or {"rounds": 0}
        errors = detail[:4000] or "the coder reported the tests as invalid without detail"
        if int(repair["rounds"]) >= machine.MAX_TEST_REPAIRS:
            self._escalate(obj, state.ESC_AGENT_ERROR, [
                f"tests still invalid after {repair['rounds']} repairs", one_line(errors, 300)])
            return
        st.data["tests_repair"] = {"rounds": int(repair["rounds"]) + 1, "pending": True, "errors": errors}
        st.enter(state.FEASIBLE, self.clock.now_iso())

    def _coder_pull(self, obj: _Object, coder: dict[str, Any], resp: dict[str, Any]) -> PullRequest:
        if obj.kind == "pr":
            return self.github.get_pull(obj.item.number)
        number = (resp.get("pr") or {}).get("number")
        if number is None:
            matches = [p for p in self.github.list_pulls(state="open")
                       if p.head_ref == coder.get("branch") and p.author == OWNER and p.head_repo == REPO]
            if not matches:
                raise StepError(f"coder succeeded but no open PR for {coder.get('branch')}")
            number = matches[0].number
        pr = self.github.get_pull(int(number))
        if pr.head_ref != coder.get("branch") or pr.author != OWNER or pr.head_repo != REPO:
            raise StepError(f"PR #{pr.number} is not the coder's PR for {coder.get('branch')}")
        return pr

    def _do_ci_triage(self, obj: _Object, ctx: Context, action: Action) -> str:
        if obj.kind == "issue":
            return self._ci_failure(obj, ctx)
        st, pr = obj.st, _require_pr(ctx)
        log = self.github.get_check_log(pr.head_sha, "test")
        diff = self.github.get_pull_diff(pr.number)
        files = sorted({f for c in self.github.list_pull_commits(pr.number) for f in c.files})
        repo_tests = self._repo_test_files(pr.head_sha)
        data = self._call(obj, "sdlc-ci-triage", [
            Section("pr", f"{pr.title}\n\n{pr.body}"),
            Section("changed_files", "\n".join(files) + "\n\ntest files changed: no"),
            Section("repo_test_files", "\n".join(repo_tests)),
            Section("diff", diff),
            Section("log", log, keep_tail=True),
        ]).data or {}
        # The agent's paths are a hint: only real test files, matched or seen failing in the log, are kept.
        test_files = paths.resolve_test_files(data["test_files"], repo_tests, log) \
            if data["cause"] == "stale-test" else []
        if data["cause"] == "stale-test":
            test_files = sorted({*test_files, *self._tests_asserting_removed_text(pr.head_sha, diff, repo_tests)})
        st.data["ci_triage"] = {"cause": data["cause"], "explanation": data["explanation"], "test_files": test_files,
                                "claimed": [one_line(str(p), 200) for p in data["test_files"][:20]],
                                "head": pr.head_sha}
        self._record_gates(st, pr.head_sha, ctx.checks)
        if data["cause"] == "stale-test" and not test_files:
            self._escalate(obj, state.ESC_AGENT_ERROR, [
                f"ci-triage named no test file that exists at {pr.head_sha[:7]} and the failing log names none"])
            self._save(obj)
            return "stale-test without a real test file"
        self._upsert(pr.number, obj.comments, "<!-- sdlc-ci-triage:v1 -->", "\n".join([
            "<!-- sdlc-ci-triage:v1 -->",
            f"**CI triage** (sdlc-ci-triage) for `{pr.head_sha[:7]}`: `{data['cause']}`.",
            "",
            sanitise_markdown(one_line(data["explanation"], 600)),
            "",
            *(f"- `{p}`" for p in test_files),
        ]))
        st.data["failures"] = None
        self._save(obj)
        return str(data["cause"])

    def _do_review(self, obj: _Object, ctx: Context, action: Action) -> str:
        st, pr = obj.st, _require_pr(ctx)
        commits = self.github.list_pull_commits(pr.number)
        diff = self.github.get_pull_diff(pr.number)
        commit_text = "\n".join(
            f"{i}. {c.sha[:7]} {c.message.splitlines()[0] if c.message else ''}\n   files: {', '.join(c.files)}"
            for i, c in enumerate(commits, 1)
        )
        sections = [
            # Only values the orchestrator controls are trusted; the branch name is PR data.
            Section("head", f"head sha: {pr.head_sha}\npull request: #{pr.number}", trusted=True),
            Section("pr", f"branch: {pr.head_ref}\ntitle: {pr.title}\n\n{pr.body}"),
        ]
        if obj.kind == "issue":
            sections += [self._issue_section(obj.item), self._spec_section(st)]
        else:
            sections.append(Section("kind", "maintenance test repair: the owner's app change comes first, the tests "
                                    "are repaired after it, so tests-first ordering does not apply", trusted=True))
        sections += [
            Section("commits", commit_text),
            Section("checks", "\n".join(f"{k}: {v}" for k, v in ctx.checks.items()), trusted=True),
            Section("diff", diff),
        ]
        data = self._call(obj, "sdlc-reviewer", sections).data or {}
        if not pr.head_sha.startswith(data["head"]):
            raise StepError(f"reviewer answered for {data['head']}, head is {pr.head_sha[:7]}")
        verdict = data["verdict"]
        previous = st.get("review") or {}
        rounds = int(previous.get("rounds", 0)) + (1 if verdict == "request-changes" else 0)
        findings = [{"severity": f["severity"], "area": f["area"], "detail": one_line(f["detail"], 400)}
                    for f in data["findings"]]
        # The marker comment is what the merge gate trusts, so it lands before the state records the verdict.
        pr_comments = obj.comments if obj.kind == "pr" else self.github.list_comments(pr.number)
        marker = gates.render_review_marker(verdict, pr.head_sha)
        # One marker comment per head sha: a re-review replaces it, whatever the earlier verdict was.
        same_head = next((c for c in pr_comments if c.author == OWNER and gates.review_of(c) == pr.head_sha), None)
        self._upsert(pr.number, pr_comments, marker, existing=same_head, body="\n".join([
            marker,
            f"**Review** (sdlc-reviewer) for `{pr.head_sha[:7]}`: **{verdict}**.",
            "",
            sanitise_markdown(one_line(data["summary"], 400)),
            "",
            *(f"- [{f['severity']}] {f['area']}: {sanitise_markdown(f['detail'])}" for f in findings),
        ]))
        st.data["review"] = {"verdict": verdict, "head": pr.head_sha, "rounds": rounds, "findings": findings}
        self._record_gates(st, pr.head_sha, ctx.checks)
        if obj.kind == "pr":
            st.data["pr"] = {"number": pr.number, "branch": pr.head_ref, "head": pr.head_sha}
            st.enter(state.IN_REVIEW, self.clock.now_iso())
        st.data["failures"] = None
        self._save(obj)
        return verdict

    @staticmethod
    def _record_gates(st: State, head: str, checks: dict[str, str] | Any) -> None:
        if not checks:
            return
        st.data["gates"] = dict(checks)
        history = st.data.setdefault("gate_history", [])
        if not history or history[-1].get("head") != head:
            history.append({"head": head, "results": dict(checks)})
        else:
            history[-1]["results"] = dict(checks)

    def _do_merge(self, obj: _Object, ctx: Context, action: Action) -> str:
        st = obj.st
        pr = self.github.get_pull(_require_pr(ctx).number)
        result = gates.verify_merge(
            pr=pr, issue=obj.item if obj.kind == "issue" else None,
            check_runs=self.github.get_check_runs(pr.head_sha),
            pr_comments=self.github.list_comments(pr.number),
            pr_files=self.github.list_pull_files(pr.number),
            object_usd=self._object_usd(obj), usd_cap=self.budget.usd_cap_issue,
        )
        if result.scope_violation:
            self._record_gates(st, pr.head_sha, result.checks)
            self._escalate(obj, state.ESC_BUILD_FAILED, ["merge refused: " + "; ".join(result.reasons)])
            self._save(obj)
            return "merge refused: files outside app/"
        if not result.passed:
            raise StepError("merge gate failed: " + "; ".join(result.reasons))
        merge_sha = self.github.merge_pull(pr.number, sha=pr.head_sha, method="merge")
        st.data["pr"] = {"number": pr.number, "branch": pr.head_ref, "head": pr.head_sha, "merge_sha": merge_sha}
        self._record_gates(st, pr.head_sha, result.checks)
        st.enter(state.MERGED, self.clock.now_iso())
        self._save(obj)
        return f"merged #{pr.number} as {merge_sha[:7]}"

    def _do_mark_merged(self, obj: _Object, ctx: Context, action: Action) -> str:
        st, pr = obj.st, _require_pr(ctx)
        st.data["pr"] = {"number": pr.number, "branch": pr.head_ref, "head": pr.head_sha,
                         "merge_sha": pr.merge_commit_sha}
        st.enter(state.MERGED, self.clock.now_iso())
        self._save(obj)
        return f"#{pr.number} already merged"

    def _do_release(self, obj: _Object, ctx: Context, action: Action) -> str:
        st = obj.st
        pr = self.github.get_pull(int(st.data["pr"]["number"]))
        merge_sha = st.data["pr"].get("merge_sha") or pr.merge_commit_sha
        if not merge_sha:
            raise StepError(f"no merge commit recorded for #{pr.number}")
        rel = st.get("release") or {}
        tag = rel.get("tag")
        if not tag:
            reserved = {
                str((o.state.get("release") or {}).get("tag")) for o in self.objects
                if o is not obj and o.state and (o.state.get("release") or {}).get("tag")
            }
            tag = release.next_version([*self.github.list_tags(), *reserved], release.bump_for(st.type))
            st.data["release"] = {"tag": tag, "pending": True}
            self._save(obj)
        messages = [c.message.splitlines()[0] for c in self.github.list_pull_commits(pr.number) if c.message]
        if self._spend_stop(obj):
            # Merged work is always released; past a cap the notes are written without a model call.
            text = release.plain_notes(pr.title, messages)
        else:
            text = self._call(obj, "sdlc-release-notes", [
                Section("release", f"version {tag}, change type {st.type}", trusted=True),
                Section("pr", f"{pr.title}\n\n{pr.body}\n\ncommits:\n" + "\n".join(messages)),
            ]).text
        source = f"Pull request #{pr.number}" + (f" for issue #{obj.item.number}" if obj.kind == "issue" else "")
        notes = f"{text.strip()}\n\n{source}. Released by the SDLC orchestrator."
        url = release.publish(self.github, tag=tag, target_sha=merge_sha, name=f"{tag}: {pr.title}", notes=notes)
        st.data["release"] = {"tag": tag, "url": url, "pending": False}
        st.enter(state.RELEASED, self.clock.now_iso())
        self._save(obj)
        if obj.kind == "issue" and obj.item.state == "open":
            self.github.close_issue(obj.item.number)
        return f"released {tag}"

    def _do_close(self, obj: _Object, ctx: Context, action: Action) -> str:
        self.github.close_issue(obj.item.number)
        if obj.state is not None:
            self._sync_labels(obj)
        return "closed"

    def _do_escalate(self, obj: _Object, ctx: Context, action: Action) -> str:
        st = obj.st
        if action.label is None:
            raise StepError("escalation without a label")
        if action.cancel_coder and (st.get("coder") or {}).get("job_id"):
            self._cancel_coder(obj)
        if ctx.pr is not None:
            self._record_gates(st, ctx.pr.head_sha, ctx.checks)
        self._escalate(obj, action.label, [action.reason])
        self._save(obj)
        return action.label

    def _maybe_ui_tester(self, obj: _Object, ctx: Context) -> None:
        """Advisory vision review of UI screenshots for open agent PRs (feature-flagged)."""
        if not self.ui_tester_enabled:
            return
        if obj.state is None or obj.st.stage != state.IN_REVIEW:
            return
        if ctx.pr is None or ctx.pr.state != "open":
            return
        is_agent_pr = ctx.pr.head_ref.startswith(gates.AGENT_BRANCH_PREFIX) or gates.AGENT_PR_LABEL in ctx.pr.labels
        if not is_agent_pr:
            return

        try:
            pr_comments = obj.comments if obj.kind == "pr" else self.github.list_comments(ctx.pr.number)
            ui_proof = next(
                (c for c in pr_comments if c.author == "github-actions[bot]" and c.body.startswith(UI_PROOF_MARKER)),
                None,
            )
            if ui_proof is None:
                return

            # Require proof comment to correspond to current PR head sha
            if f"`{ctx.pr.head_sha}`" not in ui_proof.body:
                return

            # Dedupe only on markers authored by OWNER; upsert one marker comment instead of one per sha
            existing = next(
                (c for c in pr_comments if c.author == OWNER and c.body.startswith(UI_TESTER_MARKER_PREFIX)),
                None,
            )
            if existing is not None and existing.body.startswith(render_ui_tester_marker(ctx.pr.head_sha)):
                return

            base = f"https://raw.githubusercontent.com/{REPO}/pr-screenshots/pr-{ctx.pr.number}/{ctx.pr.head_sha[:8]}/"
            filename_re = re.compile(r"^[a-z-]+\.png$")
            raw_urls = re.findall(
                r"https://raw\.githubusercontent\.com/[^\s\"\'\)<>]+",
                ui_proof.body,
            )
            image_urls = [
                u
                for u in dict.fromkeys(raw_urls)
                if u.startswith(base) and filename_re.match(u[len(base) :])
            ]
            if not image_urls:
                return

            if self._spend_stop(obj):
                return

            sections = [
                Section(
                    "head",
                    f"head sha: {ctx.pr.head_sha}\npull request: #{ctx.pr.number}",
                    trusted=True,
                ),
                Section("images", "\n".join(image_urls), trusted=False),
                Section(
                    "routes",
                    "Routes tested: home, parcel-found, not-found, invalid-input at "
                    "desktop (1280) and mobile (390)",
                    trusted=True,
                ),
                Section("pr", f"title: {ctx.pr.title}\n\n{ctx.pr.body}"),
            ]

            output = self._call(obj, "sdlc-ui-tester", sections, image_urls=image_urls)
            data = output.data or {}
            verdict = sanitise_markdown(one_line(str(data.get("verdict", "pass")), 50))
            findings = data.get("findings", [])
            summary = sanitise_markdown(one_line(str(data.get("summary", "")), 400))

            target_marker = render_ui_tester_marker(ctx.pr.head_sha)
            lines = [
                target_marker,
                f"**UI Vision Tester** (sdlc-ui-tester) for `{ctx.pr.head_sha[:7]}`: **{verdict.upper()}** (advisory).",
                "",
                summary,
                "",
            ]
            if findings:
                lines.append("### Findings")
                for f in findings:
                    route = sanitise_markdown(one_line(str(f.get("route", "")), 100))
                    vp = sanitise_markdown(one_line(str(f.get("viewport", "")), 50))
                    sev = sanitise_markdown(one_line(str(f.get("severity", "info")), 50))
                    issue = sanitise_markdown(one_line(str(f.get("issue", "")), 300))
                    lines.append(f"- [{sev}] {route}/{vp}: {issue}")
            else:
                lines.append("No visual UI anomalies detected.")

            self._upsert(ctx.pr.number, pr_comments, UI_TESTER_MARKER_PREFIX, "\n".join(lines), existing=existing)
            if obj.state is not None:
                obj.state.data["ui_tester"] = {
                    "verdict": verdict,
                    "head": ctx.pr.head_sha,
                    "findings": findings,
                    "summary": summary,
                }
                self._save(obj)
        except Exception as exc:
            self.report.errors.append(f"ui-tester on #{ctx.pr.number}: {type(exc).__name__}: {exc}")

    def _escalate(self, obj: _Object, label: str, reasons: list[str]) -> None:
        st = obj.st
        try:
            self._release_lease(obj)
        except Exception as exc:     # the sweep must not stop the escalation; the next tick retries
            self.report.errors.append(f"#{obj.item.number}: lease release failed: {type(exc).__name__}: {exc}")
        st.escalate(label, [one_line(r, 300) for r in reasons if r], self.clock.now_iso())
        marker = f"<!-- sdlc-escalation:v1 {label} -->"
        self._upsert(obj.item.number, obj.comments, marker, "\n".join([
            marker,
            f"**Escalated** `{label}`: the pipeline stopped here and needs a human decision.",
            "",
            *(f"- {sanitise_markdown(one_line(r, 300))}" for r in reasons if r),
        ]))

    # -- metrics --------------------------------------------------------------------

    # -- ledger ---------------------------------------------------------------------

    def _queue_ticket(self, obj: _Object) -> None:
        """Remember the object's ticket record as it stands now; the tick sends the latest one per object."""
        try:
            comment_ids = {"state": obj.state_comment.id} if obj.state_comment else {}
            coder_log = next(
                (c for c in obj.comments if c.author == OWNER and c.body.startswith(CODER_LOG_MARKER)), None
            )
            if coder_log:
                comment_ids["coder_log"] = coder_log.id
            ticket = ledger_model.ticket(
                number=obj.item.number, kind=obj.kind, title=obj.item.title, author=obj.item.author,
                opened_at=obj.item.created_at, closed_at=obj.item.closed_at, labels=obj.item.labels,
                state_data=obj.st.data, comment_ids=comment_ids,
                comments=obj.comments,
                updated_at=getattr(obj.item, "updated_at", None),
                reopened_at=getattr(obj.item, "reopened_at", None),
            )
            self.pending_events[obj.item.number] = ledger_events.make(
                "ticket.updated", ticket["updated_at"], {"ticket": ticket}, issue=obj.item.number)
        except Exception as exc:        # the ledger must never break a transition
            self.report.errors.append(f"ledger: #{obj.item.number}: {type(exc).__name__}: {exc}")

    def _emit_ledger(self) -> tuple[float, dict[str, str | None]]:
        """Never raises: whatever goes wrong here is a note in the report, and the tick goes on to write
        metrics.json (the spend record the 22 USD halt reads)."""
        try:
            return self._emit_ledger_unchecked()
        except Exception as exc:
            self.report.ledger = "error"
            self.report.errors.append(f"ledger: {type(exc).__name__}: {str(exc)[:160]}")
            return 0.0, {
                "emitted_at": self.previous.ledger_emitted_at,
                "reconciled_at": self.previous.ledger_reconciled_at,
            }

    def _emit_ledger_unchecked(self) -> tuple[float, dict[str, str | None]]:
        """Send this tick's events to the state-keeper. Best effort: a failure is noted and the next call
        (or its hourly reconcile from GitHub) repairs it. Returns the call's compute USD and the marks."""
        now = self.clock.now_iso()
        marks: dict[str, str | None] = {"emitted_at": self.previous.ledger_emitted_at,
                                        "reconciled_at": self.previous.ledger_reconciled_at}
        active = bool(self.pending_events) or bool(self.report.errors) or any(
            o.action not in QUIET_ACTIONS or o.result != "ok" for o in self.report.objects)
        heartbeat_due = marks["emitted_at"] is None or seconds_between(marks["emitted_at"], now) >= LEDGER_HEARTBEAT_S
        if not active and not heartbeat_due:
            self.report.ledger = "quiet"
            return 0.0, marks
        reconcile = marks["reconciled_at"] is None or seconds_between(marks["reconciled_at"], now) >= LEDGER_RECONCILE_S
        batch = list(self.pending_events.values())
        try:
            batch.append(ledger_events.make("tick.finished", now, {
                "started_at": self.report.started_at, "finished_at": now, "lock": self.report.lock,
                "objects": [{**asdict(o), "detail": one_line(o.detail, 160)} for o in self.report.objects][:150],
                "errors": [one_line(e, 200) for e in self.report.errors][:20],
                "model_calls": self.report.model_calls, "calls": self.report.calls[:40],
                "usd_this_tick": self.report.usd_this_tick, "orchestrator_usd": cost.orchestrator_tick_usd(
                    self.clock.monotonic() - self.started)}))
            batch.append(ledger_events.make("metrics.observed", now, {
                "usd": round(self.budget.usd_total, 6), "orchestrator_usd": self.previous.orchestrator_usd,
                "issues": len(self.objects), "generated_at": now}))
        except Exception as exc:
            self.report.errors.append(f"ledger: could not build events: {type(exc).__name__}: {exc}")
        result = self.emitter.emit(batch, reconcile=reconcile)
        if result.error:
            self.report.ledger = "error"
            self.report.errors.append(result.error)
            # A call that reached the ledger bills even when its answer was lost: the emitter prices it.
            return round(result.usd, 6), marks
        self.report.ledger = "emitted"
        marks["emitted_at"] = now
        if reconcile:
            marks["reconciled_at"] = now        # retried in an hour either way: no retry storm
            if result.reply.get("reconciled") is False:
                self.report.errors.append("ledger: reconcile from GitHub failed, will retry in an hour")
        return round(result.usd, 6), marks

    def _write_metrics(self, tick_usd: float, ledger_usd: float = 0.0,
                       marks: dict[str, str | None] | None = None) -> None:
        try:
            pairs = [(o.item, o.state) for o in self.objects if o.state is not None]
            doc = metrics.build(
                pairs, self.clock.now_iso(),
                orchestrator_usd=self.previous.orchestrator_usd + tick_usd, deferred=self.deferred,
                deferrals=self.streaks, ledger_usd=self.previous.ledger_usd + ledger_usd, ledger_marks=marks,
                floor_usd=self.previous.usd + self.report.usd_this_tick + tick_usd + ledger_usd,
            )
            written = metrics.publish(self.github, doc)
            self.report.metrics_written = written != metrics.UNCHANGED
            # Every tick adds orchestrator spend, so totals change each time; Pages only rebuilds
            # when the per-issue picture changed.
            if written == metrics.CHANGED:
                self.github.dispatch_workflow(PAGES_WORKFLOW, ref="main")
        except Exception as exc:
            self.report.errors.append(f"metrics: {type(exc).__name__}: {exc}")
