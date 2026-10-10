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
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from sdlc_agents import cost, gates, lock, machine, metrics, release, state
from sdlc_agents.definitions import PO_LABEL
from sdlc_agents.foundry import AgentOutput, AgentOutputError, AgentRunError, Section, run_agent
from sdlc_agents.machine import Action, Context, Kind
from sdlc_agents.paths import is_test_path
from sdlc_agents.ports import (
    OWNER,
    REPO,
    Budget,
    ClockPort,
    Comment,
    FoundryPort,
    GitHubPort,
    Issue,
    PullRequest,
    SecretsPort,
)
from sdlc_agents.sanitise import encode_marker_json, one_line, parse_json_strict, sanitise_markdown
from sdlc_agents.state import State

CODER_AGENT = "sdlc-coder"
TEST_CMD = "npm test"
CODER_WORKDIR = "app"
CODER_MAX_MODEL_USD = 0.5
CODER_MAX_ITERATIONS = 5
RESERVE_S = 45                    # wall time kept back for metrics and unlocking
COMMENT_LIMIT = 65_000            # GitHub rejects comment bodies over 65,536 chars
PAGES_WORKFLOW = "pages.yml"

TESTS_MARKER = "<!-- sdlc-tests:v1\n"
_TESTS_RE = re.compile(r"\A<!-- sdlc-tests:v1\n(.*?)\n-->", re.DOTALL)
_SCENARIO_RE = re.compile(r"<!-- scenario: (a|b|c|d|d-maintenance) -->")


class StepError(RuntimeError):
    """A step could not complete; recorded against the object and retried on a later tick."""


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
    usd_this_tick: float = 0.0          # model spend billed to objects this tick
    orchestrator_usd: float = 0.0       # this tick's own hosted compute
    total_usd: float = 0.0
    metrics_written: bool = False
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
) -> TickReport:
    """Run one bounded tick and return its report. Never raises.

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
        _Tick(github, foundry, clock, report, budget or Budget(), budget_wall_s).run()
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


def _scenario(body: str) -> str | None:
    match = _SCENARIO_RE.search(body)
    return match.group(1) if match else None


class _Tick:
    def __init__(self, github: GitHubPort, foundry: FoundryPort, clock: ClockPort, report: TickReport,
                 budget: Budget, budget_wall_s: int):
        self.github = github
        self.foundry = foundry
        self.clock = clock
        self.report = report
        self.budget = budget
        self.started = clock.monotonic()
        self.deadline = self.started + budget_wall_s - RESERVE_S
        self.objects: list[_Object] = []
        self.previous = {"usd": 0.0, "orchestrator_usd": 0.0}

    # -- loop -------------------------------------------------------------------

    def run(self) -> None:
        self._load()
        # The ledger never shrinks: an object that drops out of the listing keeps its spend.
        self.previous = metrics.previous_totals(self.github)
        objects_usd = sum(o.state.usd for o in self.objects if o.state)
        self.budget.usd_total = max(objects_usd + self.previous["orchestrator_usd"], self.previous["usd"])
        # Coder polls first: they are cheap and keep the coder's sandbox session alive.
        self.objects.sort(key=lambda o: (0 if o.state and o.state.stage == state.BUILDING else 1, o.item.number))
        for obj in self.objects:
            if self.clock.monotonic() > self.deadline:
                self._note(obj, "none", "skipped", "wall budget used")
                continue
            self._step(obj)
        tick_usd = round(cost.orchestrator_tick_usd(self.clock.monotonic() - self.started), 6)
        self.report.orchestrator_usd = tick_usd
        self.budget.usd_total += tick_usd
        self.report.total_usd = round(self.budget.usd_total, 6)
        self._write_metrics(tick_usd)

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
                continue
            self.objects.append(_Object(item, comments, comment, st))

    def _step(self, obj: _Object) -> None:
        action = Action(Kind.NOOP)
        try:
            ctx = self._context(obj)
            action = machine.next_action(ctx)
            if action.kind in (Kind.NOOP, Kind.WAIT, Kind.HALT):
                if obj.state is not None:
                    self._sync_labels(obj)
                self._note(obj, action.kind.value, "ok", action.reason)
                return
            if action.kind is Kind.IGNORE:
                self._note(obj, action.kind.value, "ignored", action.reason)
                return
            if obj.state is None:
                obj.state = State.new(obj.item.number, ctx.object_type, _scenario(obj.item.body))
            obj.committed = copy.deepcopy(obj.state.data)
            detail = getattr(self, f"_do_{action.kind.value.replace('-', '_')}")(obj, ctx, action)
            self._note(obj, action.kind.value, "ok", detail or action.reason)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self._note(obj, action.kind.value, "error", message)
            self._record_failure(obj, action, message)

    def _record_failure(self, obj: _Object, action: Action, message: str) -> None:
        if obj.state is None or obj.committed is None:
            return
        # Roll back to the last saved state; keep what was spent and count the failure.
        spent = copy.deepcopy(obj.state.data["cost"])
        obj.state.data = copy.deepcopy(obj.committed)
        obj.state.data["cost"] = spent
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

    def _upsert(self, number: int, comments: list[Comment], marker: str, body: str) -> Comment:
        """Create the bot comment that starts with `marker`, or update it in place."""
        for i, comment in enumerate(comments):
            if comment.author == OWNER and comment.body.startswith(marker):
                if comment.body != body:
                    self.github.update_comment(comment.id, body)
                    comments[i] = Comment(comment.id, comment.author, body, comment.created_at)
                return comments[i]
        created = self.github.create_comment(number, body)
        comments.append(created)
        return created

    # -- model calls --------------------------------------------------------------

    def _call(self, obj: _Object, agent: str, sections: list[Section]) -> AgentOutput:
        """Run a prompt agent and bill the object, also when the answer fails validation."""
        try:
            out = run_agent(self.foundry, agent, sections)
        except (AgentOutputError, AgentRunError) as exc:
            # Incomplete or invalid answers were still generated, so they are still paid for.
            if exc.input_tokens or exc.output_tokens:
                self._bill(obj, agent, exc.input_tokens, exc.output_tokens)
            raise
        self._bill(obj, agent, out.input_tokens, out.output_tokens)
        return out

    def _bill(self, obj: _Object, agent: str, input_tokens: int, output_tokens: int) -> None:
        usd = cost.record_call(obj.st, agent, input_tokens, output_tokens)
        self.budget.usd_total += usd
        self.report.usd_this_tick = round(self.report.usd_this_tick + usd, 8)
        self.report.model_calls += 1

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
        data = self._call(obj, "sdlc-test-designer", [
            Section("mode", mode, trusted=True), self._issue_section(obj.item), self._spec_section(st),
        ]).data or {}
        tests = [{"path": t["path"], "content": t["content"]} for t in data["tests"]]
        for t in tests:
            if self.github.get_file(t["path"], ref="main") is not None:
                raise StepError(f"test designer proposed an existing file {t['path']}")
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
        if previous.get("status") == "starting" and previous.get("mode") == action.mode:
            attempts = int(previous["attempts"])       # a start that may have reached the coder: same job id
        else:
            attempts = int(previous.get("attempts", 0)) + 1
        job_id = f"j-{'pr' if obj.kind == 'pr' else ''}{obj.item.number}-{attempts}"
        quality = st.get("quality") or {}
        spec = {"acceptance_criteria": quality.get("acceptance_criteria", []), "notes": quality.get("summary", "")}
        job: dict[str, Any] = {
            "job_id": job_id, "repo": REPO, "base": "main", "mode": action.mode,
            "issue": {"number": obj.item.number, "title": obj.item.title, "body": obj.item.body},
            "spec": spec, "tests": [], "test_cmd": TEST_CMD, "workdir": CODER_WORKDIR,
            "max_iterations": CODER_MAX_ITERATIONS, "deadline_s": machine.CODER_DEADLINE_S,
            "allowed_paths": ["app/"],
            # The coder's fallback engine spends model tokens too: give it what is left under the cap.
            "max_model_usd": round(min(CODER_MAX_MODEL_USD, max(self.budget.usd_cap_issue - st.usd, 0.0)), 4),
        }
        findings = (st.get("review") or {}).get("findings", [])
        review_notes = "\n".join(f"- [{f['severity']}] {f['detail']}" for f in findings)
        if action.mode in ("feature", "bugfix"):
            job["branch"] = f"agent/issue-{obj.item.number}"
            job["tests"] = self._designed_tests(obj)
        elif action.mode == "revise":
            pr = st.data["pr"]
            job.update(branch=pr["branch"], pr={"number": pr["number"]})
            spec["notes"] = f"Address the reviewer's findings:\n{review_notes}"
        else:
            pr_obj = ctx.pr
            ci = st.get("ci_triage") or {}
            if pr_obj is None:
                raise StepError("maintenance repair without a pull request")
            job.update(branch=pr_obj.head_ref, pr={"number": pr_obj.number}, allowed_paths=ci.get("test_files") or [])
            job["spec"] = {
                "acceptance_criteria": ["The test check passes", "Only test files change"],
                "notes": "\n".join(filter(None, [ci.get("explanation", ""), review_notes])),
            }
        # Write ahead: if the start reaches the coder but its answer is lost, the retry reuses the job id.
        resuming = previous.get("job_id") == job_id
        st.data["coder"] = {
            "job_id": job_id, "session_id": previous.get("session_id") if resuming else None,
            "mode": action.mode, "attempts": attempts, "started_at": previous.get("started_at") if resuming else None,
            "status": "starting", "engine": None, "iterations": 0, "phase": None, "elapsed_s": 0,
            "resumes": int(previous.get("resumes", 0)) if resuming else 0,
            "prior_seconds": previous.get("prior_seconds", 0) if resuming else st.data["cost"]["coder_seconds"],
            "prior_model_usd": previous.get("prior_model_usd", 0.0) if resuming
            else st.data["cost"].get("coder_model_usd", 0.0),
            "branch": job["branch"],
        }
        self._save(obj)
        resp, session = self.foundry.invoke_hosted(CODER_AGENT, {"op": "start", "job": job},
                                                   session_id=st.data["coder"]["session_id"])
        if resp.get("status") not in ("running", "succeeded"):
            raise StepError(f"coder did not start: {one_line(json.dumps(resp), 200)}")
        st.data["coder"].update(session_id=session, status="running",
                                started_at=st.data["coder"]["started_at"] or self.clock.now_iso())
        st.enter(state.BUILDING, self.clock.now_iso())
        self._save(obj)
        return f"coder job {job_id} ({action.mode})"

    def _do_poll_coder(self, obj: _Object, ctx: Context, action: Action) -> str:
        st = obj.st
        coder = st.section("coder")
        resp, session = self.foundry.invoke_hosted(CODER_AGENT, {"op": "status", "job_id": coder["job_id"]},
                                                   session_id=coder.get("session_id"))
        status = str(resp.get("status", ""))
        if status not in ("running", "succeeded", "failed", "timeout", "cancelled"):
            raise StepError(f"coder status unknown: {one_line(json.dumps(resp), 200)}")
        before = json.dumps(st.data, sort_keys=True)
        coder.update({
            "status": status, "phase": resp.get("phase"), "engine": resp.get("engine"),
            "iterations": int(resp.get("iterations") or 0), "elapsed_s": int(resp.get("elapsed_s") or 0),
            "session_id": session or coder.get("session_id"),
        })
        reason = str(resp.get("reason") or "")
        coder_cost = resp.get("cost") if isinstance(resp.get("cost"), dict) else {}
        cost.set_coder_spend(st, int(coder.get("prior_seconds", 0)) + coder["elapsed_s"],
                             float(coder.get("prior_model_usd", 0.0)) + float(coder_cost.get("model_usd") or 0.0))
        outcome = machine.after_coder(status, reason)
        if outcome.resume:
            # The coder lost its process (sandbox restart): starting the same job id resumes it.
            coder["resumes"] = int(coder.get("resumes", 0)) + 1
            coder["status"] = "starting"
        elif outcome.stage == state.IN_REVIEW:
            pr = self._coder_pull(obj, coder, resp)
            st.data["pr"] = {"number": pr.number, "branch": pr.head_ref, "head": pr.head_sha}
            if obj.kind == "issue" and gates.AGENT_PR_LABEL not in pr.labels:
                self.github.add_labels(pr.number, (gates.AGENT_PR_LABEL,))
            st.enter(state.IN_REVIEW, self.clock.now_iso())
        elif outcome.escalate:
            detail = resp.get("detail") or resp.get("log_tail") or ""
            tail = sanitise_markdown(one_line(str(detail), 300))
            self._escalate(obj, outcome.escalate, [f"{outcome.reason} in phase {resp.get('phase')}", tail])
        else:
            st.data["failures"] = None
        if json.dumps(st.data, sort_keys=True) != before:
            self._save(obj)
        return f"coder {status}"

    def _coder_pull(self, obj: _Object, coder: dict[str, Any], resp: dict[str, Any]) -> PullRequest:
        if obj.kind == "pr":
            return self.github.get_pull(obj.item.number)
        number = (resp.get("pr") or {}).get("number")
        if number is None:
            matches = [p for p in self.github.list_pulls(state="open")
                       if p.head_ref == coder.get("branch") and p.author == OWNER]
            if not matches:
                raise StepError(f"coder succeeded but no open PR for {coder.get('branch')}")
            number = matches[0].number
        pr = self.github.get_pull(int(number))
        if pr.head_ref != coder.get("branch") or pr.author != OWNER:
            raise StepError(f"PR #{pr.number} is not the coder's PR for {coder.get('branch')}")
        return pr

    def _do_ci_triage(self, obj: _Object, ctx: Context, action: Action) -> str:
        st, pr = obj.st, _require_pr(ctx)
        log = self.github.get_check_log(pr.head_sha, "test")
        diff = self.github.get_pull_diff(pr.number)
        files = sorted({f for c in self.github.list_pull_commits(pr.number) for f in c.files})
        data = self._call(obj, "sdlc-ci-triage", [
            Section("pr", f"{pr.title}\n\n{pr.body}"),
            Section("changed_files", "\n".join(files) + "\n\ntest files changed: no"),
            Section("diff", diff),
            Section("log", log, keep_tail=True),
        ]).data or {}
        st.data["ci_triage"] = {**{k: data[k] for k in ("cause", "explanation", "test_files")}, "head": pr.head_sha}
        self._record_gates(st, pr.head_sha, ctx.checks)
        self._upsert(pr.number, obj.comments, "<!-- sdlc-ci-triage:v1 -->", "\n".join([
            "<!-- sdlc-ci-triage:v1 -->",
            f"**CI triage** (sdlc-ci-triage) for `{pr.head_sha[:7]}`: `{data['cause']}`.",
            "",
            sanitise_markdown(one_line(data["explanation"], 600)),
            "",
            *(f"- `{p}`" for p in data["test_files"]),
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
            Section("head", f"head sha: {pr.head_sha}\nbranch: {pr.head_ref}\npull request: #{pr.number}",
                    trusted=True),
            Section("pr", f"{pr.title}\n\n{pr.body}"),
        ]
        if obj.kind == "issue":
            sections += [self._issue_section(obj.item), self._spec_section(st)]
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
        self._upsert(pr.number, pr_comments, marker, "\n".join([
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
            object_usd=st.usd, usd_cap=self.budget.usd_cap_issue,
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
        if st.usd >= self.budget.usd_cap_issue or self.budget.usd_total >= self.budget.usd_cap_total:
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
            coder = st.data["coder"]
            try:
                self.foundry.invoke_hosted(CODER_AGENT, {"op": "cancel", "job_id": coder["job_id"]},
                                           session_id=coder.get("session_id"))
                coder["status"] = "cancelled"
            except Exception as exc:
                self.report.errors.append(f"#{obj.item.number}: cancel failed: {type(exc).__name__}: {exc}")
        if ctx.pr is not None:
            self._record_gates(st, ctx.pr.head_sha, ctx.checks)
        self._escalate(obj, action.label, [action.reason])
        self._save(obj)
        return action.label

    def _escalate(self, obj: _Object, label: str, reasons: list[str]) -> None:
        st = obj.st
        st.escalate(label, [one_line(r, 300) for r in reasons if r], self.clock.now_iso())
        marker = f"<!-- sdlc-escalation:v1 {label} -->"
        self._upsert(obj.item.number, obj.comments, marker, "\n".join([
            marker,
            f"**Escalated** `{label}`: the pipeline stopped here and needs a human decision.",
            "",
            *(f"- {sanitise_markdown(one_line(r, 300))}" for r in reasons if r),
        ]))

    # -- metrics --------------------------------------------------------------------

    def _write_metrics(self, tick_usd: float) -> None:
        try:
            pairs = [(o.item, o.state) for o in self.objects if o.state is not None]
            doc = metrics.build(
                pairs, self.clock.now_iso(),
                orchestrator_usd=self.previous["orchestrator_usd"] + tick_usd,
                floor_usd=self.previous["usd"] + self.report.usd_this_tick + tick_usd,
            )
            written = metrics.publish(self.github, doc)
            self.report.metrics_written = written != metrics.UNCHANGED
            # Every tick adds orchestrator spend, so totals change each time; Pages only rebuilds
            # when the per-issue picture changed.
            if written == metrics.CHANGED:
                self.github.dispatch_workflow(PAGES_WORKFLOW, ref="main")
        except Exception as exc:
            self.report.errors.append(f"metrics: {type(exc).__name__}: {exc}")
