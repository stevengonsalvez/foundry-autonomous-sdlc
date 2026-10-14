"""
In-memory fakes for the ports: a GitHub that behaves like the REST API where the orchestrator
depends on it (atomic refs, merge with head sha, auto-close on 'Closes #N', check runs per sha),
a Foundry whose prompt agents answer from scripts, and a coder that commits tests first, then the
implementation, pushes and opens its PR.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sdlc_agents.clock import format_iso, parse_iso
from sdlc_agents.foundry import AgentRunError
from sdlc_agents.gates import REQUIRED_CHECKS
from sdlc_agents.ports import (
    OWNER,
    REPO,
    AgentResult,
    CheckRun,
    Comment,
    GitHubError,
    Issue,
    PullCommit,
    PullRequest,
)

START = "2026-10-10T12:00:00Z"


class FakeClock:
    def __init__(self, start: str = START, step_s: float = 0.5):
        self._now = parse_iso(start)
        self._mono = 1000.0
        self._step = step_s

    def now_iso(self) -> str:
        return format_iso(self._now)

    def monotonic(self) -> float:
        self._mono += self._step
        return self._mono

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        self._mono += seconds


CiPolicy = Callable[["FakeGitHub", int, str], dict[str, str]]


def green(_gh: FakeGitHub, _number: int, _sha: str) -> dict[str, str]:
    return dict.fromkeys(REQUIRED_CHECKS, "success")


class FakeGitHub:
    def __init__(self, clock: FakeClock):
        self.clock = clock
        self.issues: dict[int, dict[str, Any]] = {}
        self.pulls: dict[int, dict[str, Any]] = {}
        self.comments: dict[int, list[Comment]] = {}
        self.commits: dict[str, dict[str, Any]] = {}
        self.branches: dict[str, str] = {}
        self.check_runs: dict[str, list[CheckRun]] = {}
        self.logs: dict[tuple[str, str], str] = {}
        self.files: dict[tuple[str, str], str] = {}
        self.tags: list[str] = []
        self.releases: list[dict[str, str]] = []
        self.dispatches: list[tuple[str, str]] = []
        self.merges: list[tuple[int, str, str]] = []
        self.calls: list[str] = []
        self.ci: CiPolicy = green
        self.fail_on: dict[str, Exception] = {}
        self.fail_once: dict[str, int] = {}     # method name -> how many next calls fail with 502
        self._number = 0
        self._comment_id = 1000
        self._sha = 0
        self.branches["main"] = self._commit("initial commit", (), None)

    # -- test helpers ---------------------------------------------------------

    def _new_sha(self) -> str:
        self._sha += 1
        return hashlib.sha1(f"commit-{self._sha}".encode()).hexdigest()  # noqa: S324 (fake ids only)

    def _commit(self, message: str, files: tuple[str, ...], parent: str | None, *, at: str | None = None) -> str:
        sha = self._new_sha()
        self.commits[sha] = {"message": message, "files": files, "parent": parent, "time": at or self.clock.now_iso()}
        return sha

    def _record(self, name: str) -> None:
        self.calls.append(name)
        if name in self.fail_on:
            raise self.fail_on[name]
        if self.fail_once.get(name):
            self.fail_once[name] -= 1
            raise GitHubError(502, f"injected failure in {name}")

    def open_issue(self, title: str, body: str, *, author: str = OWNER, labels: tuple[str, ...] = ()) -> int:
        self._number += 1
        self.issues[self._number] = {
            "title": title, "body": body, "author": author, "labels": list(labels), "state": "open",
            "created_at": self.clock.now_iso(), "closed_at": None, "is_pr": False,
        }
        self.comments[self._number] = []
        return self._number

    def open_pr(self, title: str, body: str, branch: str, commits: list[tuple[str, tuple[str, ...]]], *,
                author: str = OWNER, labels: tuple[str, ...] = (), head_repo: str = REPO) -> int:
        """A PR from `branch`. With another head_repo it is a fork PR: its branch lives in the fork
        (not in this repo's refs) and GitHub ties none of its check runs to a base-repo PR."""
        fork = head_repo != REPO
        head = self.branches["main"] if fork or branch not in self.branches else self.branches[branch]
        for message, files in commits:
            head = self._commit(message, files, head)
        if not fork:
            self.branches[branch] = head
        self._number += 1
        number = self._number
        self.issues[number] = {
            "title": title, "body": body, "author": author, "labels": list(labels), "state": "open",
            "created_at": self.clock.now_iso(), "closed_at": None, "is_pr": True,
        }
        self.pulls[number] = {"head_ref": branch, "base_ref": "main", "merged": False, "merge_sha": None,
                              "merged_at": None, "base_sha": self.branches["main"], "head_repo": head_repo,
                              "fork_head": head if fork else None}
        self.comments[number] = []
        self.run_ci(number)
        return number

    def push(self, branch: str, message: str, files: tuple[str, ...]) -> str:
        sha = self._commit(message, files, self.branches[branch])
        self.branches[branch] = sha
        for number, pr in self.pulls.items():
            if pr["head_ref"] == branch and self.issues[number]["state"] == "open":
                self.run_ci(number)
        return sha

    def head_of(self, number: int) -> str:
        pr = self.pulls[number]
        return pr["fork_head"] or self.branches.get(pr["head_ref"], pr.get("final_head", ""))

    def run_ci(self, number: int) -> None:
        sha = self.head_of(number)
        results = self.ci(self, number, sha)
        tied = () if self.pulls[number]["fork_head"] else (number,)
        self.check_runs[sha] = [
            CheckRun(name, "in_progress", None, None, tied) if result == "pending"
            else CheckRun(name, "completed", result, self.clock.now_iso(), tied)
            for name, result in results.items()
        ]

    def pr_commits(self, number: int) -> list[str]:
        """Commit shas on the PR branch since its base, oldest first."""
        pr = self.pulls[number]
        shas, sha = [], self.head_of(number)
        while sha and sha != pr["base_sha"]:
            shas.append(sha)
            sha = self.commits[sha]["parent"]
        return list(reversed(shas))

    def bodies(self, number: int) -> list[str]:
        return [c.body for c in self.comments[number]]

    def labels(self, number: int) -> set[str]:
        return set(self.issues[number]["labels"])

    def state_of(self, number: int) -> dict[str, Any]:
        from sdlc_agents import state

        _, st = state.find(self.comments[number])
        assert st is not None, f"#{number} has no state comment"
        return st.data

    # -- issues ---------------------------------------------------------------

    def _issue(self, number: int) -> Issue:
        i = self.issues[number]
        return Issue(number, i["title"], i["body"], i["author"], tuple(i["labels"]), i["state"],
                     i["created_at"], i["closed_at"], i["is_pr"])

    def list_issues(self, *, state: str = "open", labels: tuple[str, ...] = ()) -> list[Issue]:
        self._record("list_issues")
        return [self._issue(n) for n, i in self.issues.items()
                if (state == "all" or i["state"] == state) and set(labels) <= set(i["labels"])]

    def get_issue(self, number: int) -> Issue:
        self._record("get_issue")
        return self._issue(number)

    def add_labels(self, number: int, labels: tuple[str, ...]) -> None:
        self._record("add_labels")
        for label in labels:
            if label not in self.issues[number]["labels"]:
                self.issues[number]["labels"].append(label)

    def remove_label(self, number: int, label: str) -> None:
        self._record("remove_label")
        if label in self.issues[number]["labels"]:
            self.issues[number]["labels"].remove(label)

    def list_comments(self, number: int) -> list[Comment]:
        self._record("list_comments")
        return list(self.comments[number])

    def create_comment(self, number: int, body: str) -> Comment:
        self._record("create_comment")
        if len(body) > 65_536:
            raise GitHubError(422, "body is too long")
        self._comment_id += 1
        comment = Comment(self._comment_id, OWNER, body, self.clock.now_iso())
        self.comments[number].append(comment)
        return comment

    def add_comment_as(self, number: int, author: str, body: str) -> None:
        self._comment_id += 1
        self.comments[number].append(Comment(self._comment_id, author, body, self.clock.now_iso()))

    def update_comment(self, comment_id: int, body: str) -> None:
        self._record("update_comment")
        if len(body) > 65_536:
            raise GitHubError(422, "body is too long")
        for comments in self.comments.values():
            for i, c in enumerate(comments):
                if c.id == comment_id:
                    comments[i] = Comment(c.id, c.author, body, c.created_at)
                    return
        raise GitHubError(404, f"comment {comment_id} not found")

    def close_issue(self, number: int) -> None:
        self._record("close_issue")
        self.issues[number]["state"] = "closed"
        self.issues[number]["closed_at"] = self.clock.now_iso()

    # -- pulls ----------------------------------------------------------------

    def _pull(self, number: int) -> PullRequest:
        i, p = self.issues[number], self.pulls[number]
        return PullRequest(number, i["title"], i["body"], i["author"], tuple(i["labels"]), i["state"],
                           p["merged"], p["head_ref"], self.head_of(number),
                           p["base_ref"], i["created_at"], p["merged_at"], p["merge_sha"], p["head_repo"])

    def list_pulls(self, *, state: str = "open") -> list[PullRequest]:
        self._record("list_pulls")
        return [self._pull(n) for n in self.pulls if state == "all" or self.issues[n]["state"] == state]

    def get_pull(self, number: int) -> PullRequest:
        self._record("get_pull")
        return self._pull(number)

    def get_pull_diff(self, number: int) -> str:
        self._record("get_pull_diff")
        files = sorted({f for sha in self.pr_commits(number) for f in self.commits[sha]["files"]})
        return "\n".join(f"diff --git a/{f} b/{f}\n+changed" for f in files)

    def list_pull_commits(self, number: int) -> list[PullCommit]:
        self._record("list_pull_commits")
        return [PullCommit(sha, self.commits[sha]["message"], tuple(self.commits[sha]["files"]))
                for sha in self.pr_commits(number)]

    def list_pull_files(self, number: int) -> list[str]:
        """Files changed between base and head (every commit here adds or edits), capped like GitHub."""
        self._record("list_pull_files")
        return sorted({f for sha in self.pr_commits(number) for f in self.commits[sha]["files"]})[:3000]

    def create_pull(self, *, title: str, head: str, base: str, body: str) -> PullRequest:
        self._record("create_pull")
        number = self.open_pr(title, body, head, [], labels=())
        return self._pull(number)

    def merge_pull(self, number: int, *, sha: str, method: str = "merge") -> str:
        self._record("merge_pull")
        pr = self.pulls[number]
        if pr["merged"] or self.issues[number]["state"] != "open":
            raise GitHubError(405, "Pull Request is not mergeable")
        if self.head_of(number) != sha:
            raise GitHubError(409, "Head branch was modified")
        merge_sha = self._commit(f"Merge pull request #{number}", (), self.branches["main"])
        self.branches["main"] = merge_sha
        pr.update(merged=True, merge_sha=merge_sha, merged_at=self.clock.now_iso(), final_head=sha)
        self.issues[number]["state"] = "closed"
        self.issues[number]["closed_at"] = self.clock.now_iso()
        self.merges.append((number, sha, method))
        for ref in re.findall(r"(?i)\bcloses #(\d+)", self.issues[number]["body"]):
            if int(ref) in self.issues:
                self.issues[int(ref)]["state"] = "closed"
                self.issues[int(ref)]["closed_at"] = self.clock.now_iso()
        return merge_sha

    def get_check_runs(self, sha: str) -> list[CheckRun]:
        self._record("get_check_runs")
        return list(self.check_runs.get(sha, []))

    def get_check_log(self, sha: str, name: str) -> str:
        self._record("get_check_log")
        return self.logs.get((sha, name), "")

    # -- contents and refs ----------------------------------------------------

    def get_file(self, path: str, *, ref: str) -> str | None:
        self._record("get_file")
        return self.files.get((ref, path))

    def list_tree(self, ref: str) -> list[str]:
        self._record("list_tree")
        names = {ref} | {b for b, sha in self.branches.items() if sha == ref}     # a branch or its tip sha
        return sorted(path for branch, path in self.files if branch in names)

    def put_file(self, path: str, content: str, *, branch: str, message: str) -> None:
        self._record("put_file")
        if branch not in self.branches:
            raise GitHubError(404, "branch not found")
        self.files[(branch, path)] = content
        self.branches[branch] = self._commit(message, (path,), self.branches[branch])

    def get_branch_sha(self, branch: str) -> str | None:
        self._record("get_branch_sha")
        return self.branches.get(branch)

    def create_branch(self, branch: str, *, from_sha: str) -> None:
        self._record("create_branch")
        if branch in self.branches:
            raise GitHubError(422, "Reference already exists")
        self.branches[branch] = from_sha

    def delete_branch(self, branch: str) -> None:
        self._record("delete_branch")
        self.branches.pop(branch, None)

    def branch_commit_time(self, branch: str) -> str | None:
        self._record("branch_commit_time")
        sha = self.branches.get(branch)
        return self.commits[sha]["time"] if sha else None

    def create_commit(self, message: str, *, parent_sha: str) -> str:
        self._record("create_commit")
        return self._commit(message, (), parent_sha)

    def plant_lock(self, age_s: int) -> str:
        at = format_iso(parse_iso(self.clock.now_iso()) - timedelta(seconds=age_s))
        sha = self._commit("sdlc-lock other", (), self.branches["main"], at=at)
        self.branches["sdlc-lock"] = sha
        return sha

    # -- releases -------------------------------------------------------------

    def list_tags(self) -> list[str]:
        self._record("list_tags")
        return list(self.tags)

    def create_release(self, *, tag: str, target_sha: str, name: str, body: str) -> str:
        self._record("create_release")
        if tag in self.tags:
            raise GitHubError(422, "tag already exists")
        self.tags.append(tag)
        self.releases.append({"tag": tag, "target": target_sha, "name": name, "body": body})
        return f"https://github.com/stevengonsalvez/foundry-autonomous-sdlc/releases/tag/{tag}"

    def dispatch_workflow(self, workflow_file: str, *, ref: str) -> None:
        self._record("dispatch_workflow")
        self.dispatches.append((workflow_file, ref))


# ---------------------------------------------------------------------------
# Foundry and coder
# ---------------------------------------------------------------------------

Responder = Callable[[str], Any] | dict[str, Any] | str


def issue_number(text: str) -> int:
    match = re.search(r"name=issue>\n#(\d+)", text)
    return int(match.group(1)) if match else 0


def head_sha(text: str) -> str:
    match = re.search(r"head sha: ([0-9a-f]{40})", text)
    return match.group(1) if match else "0000000"


def default_responses() -> dict[str, Responder]:
    return {
        "sdlc-req-gate": {
            "criteria": {"clear_goal": 25, "testable_acceptance_criteria": 23, "defined_scope": 22, "edge_cases": 20},
            "score": 90, "summary": "Show the estimated delivery date.",
            "acceptance_criteria": ["Shows 'Estimated delivery: Mon 12 Oct 2026'"], "questions": [],
        },
        "sdlc-product-owner": lambda text: {"answers": [
            {"question": q, "answer": "[Simulated product owner] Filter the list by status, kept in the URL."}
            for q in re.findall(r"^\d+\. (.+)$", text, re.MULTILINE)[:5]
        ] or [{"question": "?", "answer": "[Simulated product owner] Filter by status."}]},
        "sdlc-feasibility": {"suitable": True, "reasons": ["Limited to app/web"], "risk": "low",
                             "affected_paths": ["app/web/src"]},
        "sdlc-test-designer": lambda text: {
            "tests": [{"path": f"app/web/tests/issue-{issue_number(text)}.test.tsx",
                       "content": "import { describe, it, expect } from 'vitest';\n"
                                  "describe('x', () => { it('fails', () => { expect(1).toBe(2); }); });\n"}],
            "rationale": "Fails today because the behaviour is missing.",
        },
        "sdlc-reviewer": lambda text: {"verdict": "approve", "head": head_sha(text), "findings": [],
                                       "summary": "Tests first, scope ok, criteria covered."},
        "sdlc-triage": {"severity": "s3", "owner": "api", "summary": "Lowercase tracking numbers rejected.",
                        "suspected_area": "app/core validation", "rationale": "Workaround exists."},
        "sdlc-ci-triage": {"cause": "stale-test", "explanation": "Heading copy changed on purpose.",
                           "test_files": ["app/web/tests/home-page.test.tsx"]},
        "sdlc-release-notes": ("### Highlights\n- Shipped the change.\n\n### Changes\n- feat: change\n\n"
                               "### Quality\n- Tests added."),
        "sdlc-ui-tester": {
            "verdict": "pass",
            "findings": [],
            "summary": "No visual UI anomalies detected across viewports.",
        },
    }


class FakeCoder:
    """Models the hosted coder as the platform runs it.

    - A call without a session id lands in a NEW session (a fresh sandbox that knows no jobs); jobs
      live per session. `start` on a job id the session already has returns its status (idempotent).
    - A new job takes the lease ref agent-lease/<issue>; if another job holds it the start is
      refused with reason lease-held. The orchestrator, not the coder, deletes leases.
    - Jobs advance on status polls (the job finishes on the `polls_to_finish`-th poll), or all at
      once with run_orphans(), standing in for the background thread of a job nobody polls.
    - `status` for a job the session does not know is HTTP 404 unknown_job.
    """

    def __init__(self, github: FakeGitHub, *, polls_to_finish: int = 2):
        self.github = github
        self.polls_to_finish = polls_to_finish
        self.outcomes: list[str] = []          # per finished job, default succeeded
        self.jobs: dict[str, dict[str, Any]] = {}            # job id -> latest record (for assertions)
        self.by_session: dict[tuple[str, str], dict[str, Any]] = {}
        self.sessions = 0
        self.duplicate_starts = 0
        self.lease_refusals = 0
        self.lose_next_start_reply = False
        self.report_pr = True                    # include the PR number in the succeeded status
        self.invalid_detail = "app/web/tests/x.test.tsx: ReferenceError: expect is not defined"
        self.start_status = "running"
        self.status_override: dict[str, Any] | None = None
        self.extra_status: dict[str, Any] = {}          # merged into every status reply (log_tail, engine_events, ...)
        self.cancel_error: Exception | None = None
        self.lost_jobs: set[str] = set()       # status for these job ids: HTTP 400 session_not_accessible

    def _new_session(self) -> str:
        self.sessions += 1
        return f"sess-{self.sessions}"

    def handle(self, body: dict[str, Any], session_id: str | None) -> tuple[dict[str, Any], str]:
        op = body["op"]
        session = session_id or self._new_session()
        if op == "start":
            job = body["job"]
            known = self.by_session.get((session, job["job_id"]))
            if known is not None:
                self.duplicate_starts += 1
                return {"job_id": job["job_id"], "status": known["status"]}, session
            lease = f"agent-lease/{job['issue']['number']}"
            if lease in self.github.branches:
                self.lease_refusals += 1
                return {"job_id": job["job_id"], "status": "failed", "reason": "lease-held"}, session
            if self.start_status == "running":       # a refused start takes no lease
                self.github.branches[lease] = self.github.branches["main"]
            record = {"job": job, "polls": 0, "session": session, "status": self.start_status, "pr": None}
            self.by_session[(session, job["job_id"])] = record
            self.jobs[job["job_id"]] = record
            if self.lose_next_start_reply:      # started, but the caller never hears back
                self.lose_next_start_reply = False
                raise AgentRunError("read timed out", transient=True, ambiguous=True)
            return {"job_id": job["job_id"], "status": self.start_status}, session
        if op == "status" and body["job_id"] in self.lost_jobs:
            raise AgentRunError("sdlc-coder: invocation returned HTTP 400: session_not_accessible", http_status=400)
        record = self.by_session.get((session, body["job_id"]))
        if record is None:
            raise AgentRunError("sdlc-coder: invocation returned HTTP 404: unknown_job", http_status=404)
        if op == "cancel":
            if self.cancel_error is not None:
                raise self.cancel_error
            record["status"] = "cancelled"
            return {"job_id": body["job_id"], "status": "cancelled"}, session
        record["polls"] += 1
        if self.status_override is not None:
            return dict(self.status_override), session
        if record["status"] == "running" and record["polls"] >= self.polls_to_finish:
            self._finish(record)
        response = {"job_id": body["job_id"], "status": record["status"], "phase": "pr", "iterations": 2,
                    "engine": "agy", "elapsed_s": 300 * record["polls"], "log_tail": "ok", **self.extra_status}
        for key in ("reason", "detail"):
            if record.get(key):
                response[key] = record[key]
        if record["pr"] and self.report_pr:
            response["pr"] = {"number": record["pr"], "url": "https://example.invalid/pr"}
        return response, session

    def wipe_session(self, session: str) -> None:
        """The platform replaced the sandbox: the session's jobs are gone (leases stay on GitHub)."""
        self.by_session = {k: v for k, v in self.by_session.items() if k[0] != session}

    def run_orphans(self) -> None:
        """Finish every running job, as their background threads would without anyone polling."""
        for record in list(self.by_session.values()):
            if record["status"] == "running":
                self._finish(record)

    def _finish(self, record: dict[str, Any]) -> None:
        outcome = self.outcomes.pop(0) if self.outcomes else "succeeded"
        if outcome != "succeeded":
            status, _, reason = outcome.partition(":")     # e.g. "failed:tests-invalid"
            record.update(status=status, reason=reason or None,
                          detail=self.invalid_detail if reason == "tests-invalid" else None)
            return
        job, gh = record["job"], self.github
        number = job["issue"]["number"]
        if job["mode"] in ("feature", "bugfix"):
            gh.create_branch(job["branch"], from_sha=gh.branches["main"])
            gh.push(job["branch"], "test: add failing tests", tuple(t["path"] for t in job["tests"]))
            gh.push(job["branch"], f"{'fix' if job['mode'] == 'bugfix' else 'feat'}: implement #{number}",
                    (f"app/web/src/feature-{number}.tsx",))
            pr = gh.open_pr(f"feat: {job['issue']['title']}", f"Closes #{number}\n\nred then green.",
                            job["branch"], [], labels=("agent:pr",))
            record["pr"] = pr
        elif job["mode"] == "revise":
            gh.push(job["branch"], "fix: address review findings", (f"app/web/src/feature-{number}.tsx",))
        else:
            gh.push(job["branch"], "test: repair stale test", tuple(job["allowed_paths"]))
        record["status"] = "succeeded"


class FakeFoundry:
    def __init__(self, coder: FakeCoder | None = None, clock: FakeClock | None = None):
        self.coder = coder
        self.clock = clock
        self.latency_s = 0.0          # simulated model latency, charged to the clock
        self.calls: list[tuple[str, str]] = []
        self.image_calls: list[tuple[str, str, list[str] | None]] = []
        self.hosted: list[tuple[str, dict[str, Any], str | None]] = []
        self.scripts: dict[str, list[Responder]] = {}
        self.defaults = default_responses()
        self.usage = (1000, 400)
        self.errors: dict[str, Exception] = {}              # raised on every call to the agent
        self.fail_next: dict[str, list[Exception]] = {}     # raised once each, in order
        self.hosted_fail_next: list[Exception] = []

    def script(self, agent: str, *responses: Responder) -> None:
        self.scripts.setdefault(agent, []).extend(responses)

    def agent_calls(self, agent: str) -> list[str]:
        return [text for name, text in self.calls if name == agent]

    def agent_image_parts(self, agent: str) -> list[list[dict[str, Any]]]:
        parts_list: list[list[dict[str, Any]]] = []
        for name, text, urls in self.image_calls:
            if name == agent and urls:
                parts: list[dict[str, Any]] = [{"type": "input_text", "text": text}]
                for u in urls:
                    parts.append({"type": "input_image", "image_url": u})
                parts_list.append(parts)
        return parts_list

    def call_prompt_agent(self, agent: str, input_text: str, *, image_urls: list[str] | None = None,
                          max_output_tokens: int = 8000) -> AgentResult:
        self.calls.append((agent, input_text))
        self.image_calls.append((agent, input_text, image_urls))
        if self.clock is not None and self.latency_s:
            self.clock.advance(self.latency_s)
        if agent in self.errors:
            raise self.errors[agent]
        if self.fail_next.get(agent):
            raise self.fail_next[agent].pop(0)
        queue = self.scripts.get(agent)
        responder = queue.pop(0) if queue else self.defaults[agent]
        value = responder(input_text) if callable(responder) else responder
        text = value if isinstance(value, str) else json.dumps(value)
        return AgentResult(text, *self.usage)

    def invoke_hosted(self, agent: str, body: dict[str, Any], *, session_id: str | None = None,
                      timeout_s: int = 240) -> tuple[dict[str, Any], str]:
        self.hosted.append((agent, body, session_id))
        if self.hosted_fail_next:
            raise self.hosted_fail_next.pop(0)
        assert self.coder is not None, "no coder configured"
        return self.coder.handle(body, session_id)


class NoSecrets:
    def get_secret(self, name: str) -> str:
        raise AssertionError(f"the tick must not read secrets ({name})")
