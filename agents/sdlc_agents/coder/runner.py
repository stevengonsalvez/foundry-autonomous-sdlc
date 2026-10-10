"""
The coder job runner and the Invocations-level service (ops start, status, cancel).

Steps (docs/architecture.md, Coder contract), all in code; engines only edit files:

  setup ─▶ tests (feature/bugfix: commit tests alone, prove red, push)
        ─▶ implement (engine edit ─▶ post-run scan + scope check ─▶ commit+push ─▶ run tests, until green)
        ─▶ push ─▶ pr (feature/bugfix: open or reuse the PR, label agent:pr; revise and
                       maintenance push to the existing PR's branch)

Every push is a checkpoint: a job restarted after the sandbox was evicted re-clones, finds
the branch and continues from it instead of redoing finished steps.
"""

from __future__ import annotations

import json
import os
import pwd
import secrets
import shutil
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sdlc_agents.coder import sandbox, scope, shell
from sdlc_agents.coder.git_adapter import resolve_author
from sdlc_agents.coder.job import JobSpec, JobSpecError, JobState, JobStore, Mode, Phase, Status
from sdlc_agents.coder.testrun import TestOutcome, TestRunner
from sdlc_agents.cost import HOSTED_GIB_USD_PER_HOUR, HOSTED_VCPU_USD_PER_HOUR, token_usd
from sdlc_agents.ports import REPO, ClockPort, CodingEnginePort, CommandResult, GitHubPort, GitPort, SecretsPort

AGENT_PR_LABEL = "agent:pr"
INSTALL_TIMEOUT_S = 1800
TEST_TIMEOUT_S = 1800
EDIT_TIMEOUT_S = 3600
ISSUE_BODY_CHARS = 6000
FEEDBACK_CHARS = 6000


class CoderGit(GitPort, Protocol):
    def remote_has_branch(self, name: str) -> bool: ...
    def commits_since(self, base: str) -> list[tuple[str, str]]: ...
    def files_in_commit(self, sha: str) -> list[str]: ...
    def tracked_files(self) -> list[str]: ...
    def metadata_digest(self) -> str: ...
    def current_branch(self) -> str: ...
    def reset_soft(self, sha: str) -> None: ...
    def changed_since(self, sha: str) -> list[str]: ...
    def clean_ignored(self, subdir: str) -> None: ...


class Toolchain(Protocol):
    agy_path: Path

    def env(self) -> dict[str, str]: ...
    def ensure_git(self) -> None: ...
    def ensure_node(self) -> None: ...
    def ensure_agy(self) -> Path: ...
    def write_agy_token(self, token: str, *, home: Path | None = None,
                        owner: tuple[int, int] | None = None) -> Path: ...
    def node_bin(self) -> Path: ...


@dataclass(frozen=True)
class EngineContext:
    spec: JobSpec
    protected: tuple[str, ...]  # files the engine must not change: existing test files (feature, bugfix)
    tests_only: bool
    cancel: threading.Event
    tool_env: dict[str, str]
    agy_binary: Path | None     # None when agy could not be installed or has no token
    agy_home: Path              # HOME for agy: its own user's home, or the coder's
    run_as: sandbox.RunAs | None = None   # the unprivileged engine user, when the sandbox allows one
    dirty: Callable[[], bool] = lambda: False   # whether the working tree has changes right now


@dataclass
class CoderDeps:
    home: Path
    secrets: SecretsPort
    github: Callable[[str], GitHubPort]                                # PAT -> client
    git: Callable[[tuple[str, str], threading.Event], CoderGit]        # (author, cancel) -> git
    engines: Callable[[EngineContext], list[CodingEnginePort]]         # fallback order
    toolchain: Toolchain
    clock: ClockPort
    owner_user_id: Callable[[str], int | None] = lambda pat: None
    engine_user: Callable[[], sandbox.RunAs | None] = lambda: None
    agy_installer: Callable[[Path], Path] = sandbox.install_agy_binary
    reap: Callable[[sandbox.RunAs], int] = sandbox.reap_user
    privileged_work_root: Path = sandbox.PRIVILEGED_WORK_ROOT
    compute_usd_per_hour: float = 0.0   # this agent's vCPU and memory at the hosted list price; 0 if unknown


class JobStop(Exception):
    def __init__(self, status: Status, reason: str, detail: str = ""):
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.detail = detail


def _untrusted(text: str) -> str:
    nonce = secrets.token_hex(8)
    return f"<untrusted_input nonce={nonce}>\n{text}\n</untrusted_input nonce={nonce}>"


class JobRunner:
    def __init__(self, spec: JobSpec, state: JobState, store: JobStore, deps: CoderDeps, cancel: threading.Event):
        self.spec = spec
        self.state = state
        self.store = store
        self.deps = deps
        self.cancel = cancel
        self.checkout = deps.home / "work" / spec.job_id / "checkout"
        self._run_as: sandbox.RunAs | None = None
        self._node_bin: Path | None = None
        self._agy: Path | None = None
        self._t0 = 0.0
        self._elapsed_before = state.elapsed_s
        self._tokens_before = (state.input_tokens, state.output_tokens)
        self._pat = ""
        self._git: CoderGit | None = None
        self._red_sha = ""
        self._last_sha = ""
        self._red_output = ""

    # -- lifecycle -------------------------------------------------------------------------

    def run(self) -> None:
        self._t0 = self.deps.clock.monotonic()
        self._log(f"start job {self.spec.job_id} mode={self.spec.mode} branch={self.spec.branch}")
        self._log(f"cost note: hosted compute {HOSTED_VCPU_USD_PER_HOUR} USD per vCPU-hour and "
                  f"{HOSTED_GIB_USD_PER_HOUR} USD per GiB-hour (UK South list price), this agent "
                  f"{self.deps.compute_usd_per_hour:.5f} USD per active hour; agy is billed to its plan")
        try:
            self._setup()
            if self.spec.mode.writes_red_tests:
                self._red()
            elif self.spec.mode is Mode.REVISE:
                self._find_red()
            self._implement()
            self._publish()
            self._finish(Status.SUCCEEDED, None)
        except JobStop as stop:
            self._finish(stop.status, stop.reason, stop.detail)
        except Exception as exc:
            self._finish(Status.FAILED, "error", f"{type(exc).__name__}: {exc}")

    def _finish(self, status: Status, reason: str | None, detail: str = "") -> None:
        self.state.status = status
        self.state.reason = reason
        self.state.detail = self.store.redact(detail)[-2000:]
        self._checkpoint()
        self._log(f"finished: {status} {reason or ''} {self.state.detail}")

    @property
    def git(self) -> CoderGit:
        assert self._git is not None, "git used before setup"
        return self._git

    def _log(self, text: str) -> None:
        self.store.log(self.spec.job_id, text)

    def _elapsed(self) -> float:
        return self._elapsed_before + self.deps.clock.monotonic() - self._t0

    def _checkpoint(self, phase: Phase | None = None) -> None:
        if phase is not None:
            self.state.phase = phase
        self.state.elapsed_s = self._elapsed()
        self.state.updated_at = self.deps.clock.now_iso()
        self.store.save(self.state)

    def _check_stops(self) -> None:
        if self.cancel.is_set():
            raise JobStop(Status.CANCELLED, "cancelled")
        if self._elapsed() >= self.spec.deadline_s:
            raise JobStop(Status.TIMEOUT, "deadline", f"deadline_s={self.spec.deadline_s} reached")

    def _timeout(self, cap: int) -> int:
        return max(1, int(min(cap, self.spec.deadline_s - self._elapsed())))

    # -- step 1: setup ---------------------------------------------------------------------

    def _setup(self) -> None:
        self._checkpoint(Phase.SETUP)
        tools = self.deps.toolchain
        tools.ensure_git()
        tools.ensure_node()
        self._pat = self.deps.secrets.get_secret("github-pat")
        self.store.redact.add(self._pat)
        self._run_as = self.deps.engine_user()
        self.state.agy_user = self._run_as.name if self._run_as else pwd.getpwuid(os.geteuid()).pw_name
        self.state.tests_user = self.state.agy_user   # install and tests run as the same user as agy
        self._log(f"agy_user: {self.state.agy_user}")
        self._log(f"tests_user: {self.state.tests_user}")
        if self._run_as is not None:
            self._node_bin = tools.node_bin()
            # Outside the coder's $HOME, which the engine user cannot traverse; root owns the top level.
            self.deps.privileged_work_root.mkdir(mode=0o755, parents=True, exist_ok=True)
            self.checkout = self.deps.privileged_work_root / self.spec.job_id / "checkout"
        self._agy = self._prepare_agy()
        self._git = self.deps.git(resolve_author(self.deps.owner_user_id(self._pat)), self.cancel)
        self._quiesce()   # a previous job's leftovers must not race the delete
        shutil.rmtree(self.checkout, ignore_errors=True)
        self.git.clone(self.spec.repo, str(self.checkout), token=self._pat)
        if self.git.remote_has_branch(self.spec.branch):
            self._log(f"branch {self.spec.branch} exists, continuing from it")
            self.git.checkout_existing_branch(self.spec.branch)
            self._last_sha = self.git.head_sha()
        elif not self.spec.mode.writes_red_tests:
            raise JobStop(Status.FAILED, "branch-missing", f"{self.spec.branch} does not exist")
        else:
            self.git.checkout_new_branch(self.spec.branch, base=self.spec.base)
            self._last_sha = self.git.head_sha()
        self._install()

    def _prepare_agy(self) -> Path | None:
        try:
            token = self.deps.secrets.get_secret("agy-cli-token")
            self.store.redact.add(token)
            binary = self.deps.toolchain.ensure_agy()
            if self._run_as is None:
                self.deps.toolchain.write_agy_token(token)
                return binary
            # The token lives in the engine user's home; the Key Vault read stayed in this process.
            self.deps.toolchain.write_agy_token(token, home=self._run_as.home,
                                                owner=(self._run_as.uid, self._run_as.gid))
            return self.deps.agy_installer(binary)
        except Exception as exc:
            self._log(f"agy unavailable, using the fallback engines: {type(exc).__name__}: {exc}")
            return None

    # -- running untrusted code (install, tests): as the engine user when there is one ----------

    def _work_env(self) -> dict[str, str]:
        if self._run_as is not None and self._node_bin is not None:
            return sandbox.user_env(self._run_as, self._node_bin)
        return self.deps.toolchain.env()

    def _as_user(self) -> dict[str, int]:
        return {"user": self._run_as.uid, "group": self._run_as.gid} if self._run_as else {}

    def _quiesce(self) -> None:
        """Kill every engine-user process; root only touches the user's tree while nothing of it runs."""
        if self._run_as is not None:
            left = self.deps.reap(self._run_as)
            if left:
                raise JobStop(Status.FAILED, "error", f"{left} {self._run_as.name} processes survived SIGKILL")

    def _hand_over(self) -> None:
        if self._run_as is not None:
            self._quiesce()
            sandbox.give_tree(self.checkout, self._run_as)

    def _snapshot(self) -> tuple[str, dict[str, str]]:
        self._quiesce()
        return self.git.metadata_digest(), sandbox.symlinks(self.checkout)

    def _push(self, sha: str) -> None:
        """Push exactly the commit root verified, with no engine-user process alive."""
        self._check_stops()
        self._quiesce()
        self.git.push(self.spec.branch, sha=sha)

    def _report_path(self) -> Path:
        if self._run_as is None:
            return self.store.job_dir(self.spec.job_id) / "report.json"
        reports = self.checkout.parent / "reports"
        reports.mkdir(mode=0o700, exist_ok=True)
        os.lchown(reports, self._run_as.uid, self._run_as.gid)
        return reports / "report.json"

    def _install(self) -> None:
        if not self.spec.install_cmd.strip():
            return
        self._hand_over()
        before = self._snapshot()
        result = shell.run(self.spec.install_cmd, cwd=self.checkout / self.spec.workdir,
                           env=self._work_env(), timeout_s=self._timeout(INSTALL_TIMEOUT_S),
                           cancel=self.cancel, **self._as_user())
        self._quiesce()
        self._scan(before, "install")
        self._log(f"install ({result.returncode}): {result.output[-3000:]}")
        if result.returncode != 0:
            self._check_stops()
            raise JobStop(Status.FAILED, "install-failed", result.output[-1500:])

    # -- step 2: red -----------------------------------------------------------------------

    def _find_red(self) -> bool:
        """Locate the red commit on an existing branch. False when the branch has no commits yet."""
        commits = self.git.commits_since(self.spec.base)
        if not commits:
            if self.spec.mode is Mode.REVISE:
                raise JobStop(Status.FAILED, "branch-conflict", f"{self.spec.branch} has no commits to revise")
            return False
        sha, subject = commits[0]
        if not subject.startswith("test:"):
            raise JobStop(Status.FAILED, "branch-conflict",
                          f"{self.spec.branch} does not start with a test commit: {subject}")
        self._red_sha = sha
        self._log(f"red commit {sha[:12]} already on the branch, not redoing the tests step")
        return True

    def _red(self) -> None:
        self._checkpoint(Phase.TESTS)
        if self._find_red():
            return
        self.git.write_files({t.path: t.content for t in self.spec.tests})
        self._red_sha = self._last_sha = self.git.commit_all(f"test: add failing tests for #{self.spec.issue_number}")
        outcome = self._run_tests()
        if not outcome.report.is_red_for([t.path for t in self.spec.tests]):
            raise JobStop(Status.FAILED, "tests-not-red",
                          f"{outcome.report.summary()}\n{outcome.feedback(1500)}")
        self.state.red_summary = outcome.report.summary()
        self._red_output = outcome.feedback(3000)
        self._push(self._red_sha)
        self._checkpoint()

    def _run_tests(self) -> TestOutcome:
        self._check_stops()
        self._hand_over()
        before = self._snapshot()
        runner = TestRunner(test_cmd=self.spec.test_cmd, cwd=self.checkout / self.spec.workdir,
                            report_path=self._report_path(), env=self._work_env(), cancel=self.cancel,
                            run_as=self._as_user())
        outcome = runner.run(timeout_s=self._timeout(TEST_TIMEOUT_S))
        self._quiesce()
        self._scan(before, "tests")
        self._log(f"tests ({outcome.returncode}): {outcome.report.summary()}\n{outcome.output[-3000:]}")
        self._check_stops()
        return outcome

    # -- step 3: implement -----------------------------------------------------------------

    def _implement(self) -> None:
        self._checkpoint(Phase.IMPLEMENT)
        tests_only = self.spec.mode is Mode.MAINTENANCE
        protected = () if tests_only else tuple(p for p in self.git.tracked_files() if scope.is_test_path(p))
        red_files = () if tests_only else tuple(self.git.files_in_commit(self._red_sha))
        agy_home = self._run_as.home if self._run_as else self.deps.home
        engines = self.deps.engines(EngineContext(self.spec, protected, tests_only, self.cancel,
                                                  self.deps.toolchain.env(), self._agy, agy_home, self._run_as,
                                                  dirty=lambda: bool(self.git.changed_paths())))
        current = 0
        outcome = self._run_tests()
        # The suites that define done: the new tests, or in maintenance the ones failing at the start.
        must_pass = red_files or tuple(outcome.report.failing_paths(str(self.checkout)))
        # A revise job exists to put a new head on the PR, so green alone is not done until it commits.
        committed = self.spec.mode is not Mode.REVISE
        while True:
            if committed and self._green(outcome, must_pass):
                if not self.spec.install_cmd.strip():
                    break
                outcome = self._clean_rerun()
                if self._green(outcome, must_pass):
                    break
                self._log("green did not hold after a clean install; continuing")
            self._check_stops()
            if self.state.iterations >= self.spec.max_iterations:
                raise JobStop(Status.FAILED, "max-iterations", outcome.report.summary())
            if current >= len(engines):
                raise JobStop(Status.FAILED, "engines-exhausted", "every engine in the chain failed")
            engine = engines[current]
            pre = self.git.head_sha()
            before = self._snapshot()
            result = self._edit(engine, outcome, red_files)
            self._account(engines)
            self._quiesce()
            self._scan(before, f"engine {engine.name}")
            changed = self._contain(pre)
            if result.returncode != 0:
                self._check_stops()
                self._log(f"engine {engine.name} failed ({result.returncode}), falling back: {result.output[-1500:]}")
                self.git.revert_paths(changed)
                current += 1
                continue
            self.state.iterations += 1
            self.state.engine = engine.name
            self._check_stops()
            self._enforce_scope(changed, protected, tests_only)
            committed = self._commit_iteration(changed, protected, tests_only) or committed
            outcome = self._run_tests()
            self._checkpoint()
        self.state.green_summary = outcome.report.summary()

    @staticmethod
    def _green(outcome: TestOutcome, must_pass: tuple[str, ...]) -> bool:
        return outcome.green and outcome.report.suites_passed(must_pass)

    def _clean_rerun(self) -> TestOutcome:
        """Reinstall from scratch so nothing an engine hid in ignored files (node_modules) can fake green."""
        self._log("green: confirming from a clean install")
        self.git.clean_ignored(self.spec.workdir)
        self._install()
        return self._run_tests()

    def _scan(self, before: tuple[str, dict[str, str]], step: str) -> None:
        """After anything that ran untrusted code: no new or retargeted symlinks, .git/config and hooks unchanged."""
        digest, links = before
        if self.git.metadata_digest() != digest:
            raise JobStop(Status.FAILED, "scope-violation", f"{step} changed .git/config or .git/hooks")
        added = sorted(path for path, target in sandbox.symlinks(self.checkout).items() if links.get(path) != target)
        if added:
            for path in added:
                os.unlink(self.checkout / path)
            raise JobStop(Status.FAILED, "scope-violation", f"{step} created symlinks (removed): " + ", ".join(added))

    def _contain(self, pre: str) -> list[str]:
        """Everything the engine changed since `pre`, even if it ran git itself; it must stay on the branch."""
        branch = self.git.current_branch()
        if branch != self.spec.branch:
            raise JobStop(Status.FAILED, "scope-violation", f"engine switched the checkout to {branch}")
        if self.git.head_sha() != pre:
            self._log("engine created commits; undoing them so its edits are checked like any other change")
            self.git.reset_soft(pre)
        return self.git.changed_since(pre)

    def _edit(self, engine: CodingEnginePort, outcome: TestOutcome, red_files: tuple[str, ...]) -> CommandResult:
        self._log(f"iteration {self.state.iterations + 1} with engine {engine.name}")
        result = engine.edit(self._prompt(outcome, red_files), workdir=str(self.checkout),
                             timeout_s=self._timeout(EDIT_TIMEOUT_S))
        self._log(f"engine {engine.name} ({result.returncode}): {result.output[-3000:]}")
        return result

    def _account(self, engines: list[CodingEnginePort]) -> None:
        used_in = sum(e.usage.input_tokens for e in engines if hasattr(e, "usage"))
        used_out = sum(e.usage.output_tokens for e in engines if hasattr(e, "usage"))
        self.state.input_tokens = self._tokens_before[0] + used_in
        self.state.output_tokens = self._tokens_before[1] + used_out
        self.state.model_usd = token_usd(self.state.input_tokens, self.state.output_tokens)
        if self.state.model_usd > self.spec.max_model_usd:
            raise JobStop(Status.FAILED, "cost-cap",
                          f"model spend {self.state.model_usd:.4f} USD over {self.spec.max_model_usd} USD")

    def _enforce_scope(self, changed: list[str], protected: tuple[str, ...], tests_only: bool) -> None:
        bad = scope.violations(changed, allowed_paths=self.spec.allowed_paths, protected=protected,
                               tests_only=tests_only)
        if bad:
            self.git.revert_paths(bad)
            self.state.violations = bad
            raise JobStop(Status.FAILED, "scope-violation", "reverted out-of-scope edits: " + ", ".join(bad))

    def _commit_iteration(self, changed: list[str], protected: tuple[str, ...], tests_only: bool) -> bool:
        if not changed:
            self._log("engine made no changes")
            return False
        n, i, prefix = self.spec.issue_number, self.state.iterations, self.spec.mode.commit_prefix
        if self.spec.mode is Mode.MAINTENANCE:
            message = f"test: repair stale tests for #{n}"
        elif self.spec.mode is Mode.REVISE:
            message = f"fix: address review findings for #{n}"
        else:
            message = f"{prefix}: {self._title()} (#{n})"
        if i > 1:
            message = (f"{prefix}: address failing tests for #{n} (iteration {i})" if self.spec.mode.writes_red_tests
                       else f"{message} (iteration {i})")
        sha = self.git.commit_all(message)
        # Re-check what the commit actually contains, then push exactly that commit.
        bad = scope.violations(self.git.files_in_commit(sha), allowed_paths=self.spec.allowed_paths,
                               protected=protected, tests_only=tests_only)
        if bad:
            raise JobStop(Status.FAILED, "scope-violation", "commit contained out-of-scope paths: " + ", ".join(bad))
        self._last_sha = sha
        self._push(sha)
        return True

    def _title(self) -> str:
        return " ".join(self.spec.issue_title.split())[:72] or f"issue {self.spec.issue_number}"

    def _prompt(self, outcome: TestOutcome, red_files: tuple[str, ...]) -> str:
        s = self.spec
        allowed = ", ".join(s.allowed_paths)
        if s.mode is Mode.MAINTENANCE:
            task = ("An intended app change made some tests stale. Update only these test files so they pass "
                    f"against the current app: {allowed}. Do not change application source.")
        elif s.mode is Mode.REVISE:
            task = ("A reviewer requested changes on this pull request; the notes below are the findings. "
                    f"Address them while keeping every test passing. Never edit the test files {', '.join(red_files)} "
                    f"or any other existing test file or vitest config; touch only paths under {allowed}.")
        else:
            task = (f"Make the committed tests pass. Rules: never edit the test files {', '.join(red_files)} "
                    f"or any other existing test file or vitest config; touch only paths under {allowed}; "
                    "do not run git; keep the change small and typed.")
        criteria = "\n".join(f"- {c}" for c in s.acceptance_criteria) or "- (none given)"
        return (
            f"{task}\n\nRepository checkout: the current directory. Tests run with `{s.test_cmd}` in `{s.workdir}`.\n\n"
            f"Issue #{s.issue_number}:\n{_untrusted(s.issue_title + chr(10) + s.issue_body[:ISSUE_BODY_CHARS])}\n\n"
            f"Acceptance criteria:\n{_untrusted(criteria)}\n\nNotes:\n{_untrusted(s.notes or '(none)')}\n\n"
            f"Current failing test output:\n{_untrusted(outcome.feedback(FEEDBACK_CHARS))}\n"
        )

    # -- step 4: push and PR ---------------------------------------------------------------

    def _publish(self) -> None:
        self._checkpoint(Phase.PUSH)
        self._push(self._last_sha)
        if not self.spec.mode.writes_red_tests:
            # revise and maintenance update the PR they were given; they never open one.
            number = self.spec.pr_number
            self.state.pr = {"number": number, "url": f"https://github.com/{REPO}/pull/{number}"}
            return
        self._checkpoint(Phase.PR)
        github = self.deps.github(self._pat)
        existing = [p for p in github.list_pulls(state="open") if p.head_ref == self.spec.branch]
        title = f"{self.spec.mode.commit_prefix}: {self._title()} (#{self.spec.issue_number})"
        pr = existing[0] if existing else github.create_pull(
            title=title, head=self.spec.branch, base=self.spec.base, body=self.store.redact(self._pr_body()))
        github.add_labels(pr.number, (AGENT_PR_LABEL,))
        self.state.pr = {"number": pr.number, "url": f"https://github.com/{REPO}/pull/{pr.number}"}
        self._log(f"pull request #{pr.number} {'reused' if existing else 'opened'}")

    def _pr_body(self) -> str:
        red_output = self._red_output or "(red verified in an earlier run of this job)"
        return (
            f"Closes #{self.spec.issue_number}\n\n"
            f"Engine: {self.state.engine}\nIterations: {self.state.iterations}\n"
            f"Engine user: {self.state.agy_user}\nTests user: {self.state.tests_user}\n\n"
            f"## Red (tests committed first)\n\n{self.state.red_summary or 'red commit on branch'}\n\n"
            f"```\n{red_output}\n```\n\n"
            f"## Green\n\n{self.state.green_summary}\n"
        )


class CoderService:
    """Maps Invocations request bodies to jobs. One background thread per running job."""

    def __init__(self, store: JobStore, deps: CoderDeps):
        self._store = store
        self._deps = deps
        self._threads: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self._lock = threading.Lock()

    def handle_raw(self, raw: bytes, *, session_id: str = "") -> tuple[int, dict[str, Any]]:
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return 400, {"error": "invalid_json"}
        return self.handle(body, session_id=session_id)

    def handle(self, body: Any, *, session_id: str = "") -> tuple[int, dict[str, Any]]:
        if not isinstance(body, dict):
            return 400, {"error": "invalid_request", "message": "body must be a JSON object"}
        op = body.get("op")
        if op == "start":
            return self.start(body.get("job"), session_id=session_id)
        if op == "status":
            return self.status(str(body.get("job_id", "")))
        if op == "cancel":
            return self.cancel(str(body.get("job_id", "")))
        return 400, {"error": "unknown_op", "message": "op must be start, status or cancel"}

    def start(self, job: Any, *, session_id: str = "") -> tuple[int, dict[str, Any]]:
        """Idempotent per job_id: a retried start returns the existing job, never a second one."""
        try:
            spec = JobSpec.from_request(job)
        except JobSpecError as exc:
            return 400, {"error": "invalid_job", "message": str(exc)}
        with self._lock:
            if self._alive_locked(spec.job_id):
                existing = self._store.load(spec.job_id)
                return 200, {"job_id": spec.job_id, "status": Status.RUNNING.value,
                             "session_id": existing.session_id if existing else session_id}
            state = self._settle(self._store.load(spec.job_id))
            if state is not None and state.reason != "interrupted":
                return 200, state.view(self._store.tail(spec.job_id), usd_per_hour=self._usd_per_hour)
            if state is None:
                state = JobState.new(spec, started_at=self._deps.clock.now_iso())
                state.session_id = session_id
            else:
                state.status, state.reason, state.detail = Status.RUNNING, None, ""
                state.request = spec.to_request()
                self._store.log(spec.job_id, "resuming an interrupted job")
            self._store.save(state)
            cancel = threading.Event()
            runner = JobRunner(spec, state, self._store, self._deps, cancel)
            thread = threading.Thread(target=runner.run, name=f"coder-{spec.job_id}", daemon=True)
            self._threads[spec.job_id] = (thread, cancel)
            thread.start()
        return 200, {"job_id": spec.job_id, "status": Status.RUNNING.value, "session_id": state.session_id}

    def status(self, job_id: str) -> tuple[int, dict[str, Any]]:
        with self._lock:
            state = self._settle(self._store.load(job_id))
        if state is None:
            return 404, {"error": "unknown_job", "job_id": job_id}
        return 200, state.view(self._store.tail(job_id), usd_per_hour=self._usd_per_hour)

    @property
    def _usd_per_hour(self) -> float:
        return float(getattr(self._deps, "compute_usd_per_hour", 0.0))

    def cancel(self, job_id: str) -> tuple[int, dict[str, Any]]:
        with self._lock:
            entry = self._threads.get(job_id)
            if entry and entry[0].is_alive():
                entry[1].set()
                self._store.log(job_id, "cancel requested")
                return 200, {"job_id": job_id, "status": "cancelling"}
        return self.status(job_id)

    def _alive(self, job_id: str) -> bool:
        with self._lock:
            return self._alive_locked(job_id)

    def _alive_locked(self, job_id: str) -> bool:
        entry = self._threads.get(job_id)
        return bool(entry and entry[0].is_alive())

    def _settle(self, state: JobState | None) -> JobState | None:
        """A job recorded as running with no live thread in this process was killed by an eviction."""
        if state is not None and state.status is Status.RUNNING and not self._alive_locked(state.job_id):
            state.status = Status.FAILED
            state.reason = "interrupted"
            state.detail = "the session restarted while the job ran; start the same job_id to resume"
            self._store.save(state)
            self._store.log(state.job_id, "marked interrupted: no live worker for a running job")
        return state
