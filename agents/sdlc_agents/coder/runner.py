"""
The coder job runner and the Invocations-level service (ops start, status, cancel).

Steps (docs/architecture.md, Coder contract), all in code; engines only edit files:

  setup ─▶ tests (feature/bugfix: commit tests alone, typecheck and lint them, prove red, push)
        ─▶ implement (engine edit ─▶ post-run scan + scope check ─▶ commit (+push for feature/bugfix)
                      ─▶ run tests, until green: tests pass, then typecheck and lint pass, as in CI;
                      a model-loop round is kept only if strictly better, else reverted)
        ─▶ push ─▶ pr (feature/bugfix: open or reuse the PR, label agent:pr; revise and
                       maintenance push to the existing PR's branch)

revise and maintenance push once, squashed, when green (the branch belongs to a PR someone owns).
For feature and bugfix every push is a checkpoint: a job restarted after the sandbox was evicted re-clones, finds
the branch and continues from it instead of redoing finished steps.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import stat
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sdlc_agents.coder import checks, sandbox, scope, shell
from sdlc_agents.coder.git_adapter import resolve_author
from sdlc_agents.coder.job import JobSpec, JobSpecError, JobState, JobStore, Mode, Phase, Redactor, Status
from sdlc_agents.coder.testrun import TestOutcome, TestRunner
from sdlc_agents.coder.toolchain import AGY_COMMANDS_HELP, AGY_SETTINGS_BYTES
from sdlc_agents.cost import HOSTED_GIB_USD_PER_HOUR, HOSTED_VCPU_USD_PER_HOUR, token_usd
from sdlc_agents.ports import (
    OWNER,
    REPO,
    ClockPort,
    CodingEnginePort,
    CommandResult,
    GitHubError,
    GitHubPort,
    GitPort,
    SecretsPort,
)

AGENT_PR_LABEL = "agent:pr"
LEASE_PREFIX = "agent-lease/"   # refs/heads/agent-lease/<issue>: one live coder job per issue
INSTALL_TIMEOUT_S = 1800
TEST_TIMEOUT_S = 1800
CHECK_TIMEOUT_S = 900   # each of checks.CHECK_COMMANDS
EDIT_TIMEOUT_S = 3600
HEARTBEAT_S = 30          # a running job rewrites state.json (updated_at) at least this often
WATCHDOG_GRACE_S = 60     # past deadline_s + this, the heartbeat cancels the job and records the timeout
TRACEBACK_CHARS = 1800
ISSUE_BODY_CHARS = 6000
FEEDBACK_CHARS = 6000
MAX_FAILING_LISTED = 40
AGY_LOG_READ_BYTES = 2_000_000
AGY_LOG_EXCERPT_CHARS = 3000
AGY_LOG_LINES = re.compile(
    r"CLI settings initialized|SANDBOX_COMMAND_BLOCKED|"
    r"(?i:permission|denied|auto-den|ask|tool call|run_command|command\()")
NO_PROGRESS_ROUNDS = 2
# Rounds an engine gets before the next one takes over, progress or not; others run until no progress.
ENGINE_MAX_ROUNDS = {"agy": 1, "agy-unrestricted": 2}
# Engines whose every round is re-checked (tests, typecheck, lint) and kept only if strictly better.
GUARDED_ENGINES = frozenset({"loop"})
AGY_SETUP_ATTEMPTS = 2
ENGINE_LABELS = {
    "agy": "agy (agyuser, allow-list)",
    "agy-unrestricted": "agy-unrestricted (agyuser, skip-permissions after allow-list denial)",
    "loop": "loop (model deployment sdlc-default, edits written by the coder)",
}   # rounds without any change before the next engine takes over
# agy exits 0 without editing when a tool it wanted was refused by the headless permission rules.
SOFT_DENY = re.compile(r'permission that headless mode cannot prompt for|no output produced', re.IGNORECASE)


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
    def special_paths_since(self, sha: str) -> list[str]: ...
    def special_paths_in_commit(self, sha: str) -> list[str]: ...


class Toolchain(Protocol):
    agy_path: Path

    def env(self) -> dict[str, str]: ...
    def ensure_git(self) -> None: ...
    def ensure_node(self) -> None: ...
    def ensure_agy(self) -> Path: ...
    def write_agy_token(self, token: str, *, home: Path | None = None,
                        owner: tuple[int, int] | None = None) -> Path: ...
    def write_agy_settings(self, *, home: Path | None = None, owner: tuple[int, int] | None = None) -> Path: ...
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
    refresh_agy_settings: Callable[[], None] = lambda: None   # root rewrites agy's allow-list (each call)
    agy_log_dir: Path = Path("/nonexistent")   # where agy writes --log-file (engine-user owned when isolated)
    round_no: Callable[[], int] = lambda: 0    # the iteration number about to run
    failing: Callable[[], tuple[str, ...]] = lambda: ()   # test files failing in the latest run


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
        self._watchdog_fired = False
        self._failing: tuple[str, ...] = ()
        self._start_sha = ""

    # -- lifecycle -------------------------------------------------------------------------

    def run(self) -> None:
        """The job thread. It never dies silently: anything unexpected ends as `internal-error`."""
        self._t0 = self.deps.clock.monotonic()
        done = threading.Event()
        threading.Thread(target=self._heartbeat, args=(done,), name=f"beat-{self.spec.job_id}", daemon=True).start()
        try:
            self._log(f"start job {self.spec.job_id} mode={self.spec.mode} branch={self.spec.branch}")
            self._log(f"cost note: hosted compute {HOSTED_VCPU_USD_PER_HOUR} USD per vCPU-hour and "
                      f"{HOSTED_GIB_USD_PER_HOUR} USD per GiB-hour (UK South list price), this agent "
                      f"{self.deps.compute_usd_per_hour:.5f} USD per active hour; agy is billed to its plan")
            self._log_cgroup("start")
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
        except BaseException as exc:   # also SystemExit, KeyboardInterrupt: they would end the thread unseen
            self._internal_error(exc)
        finally:
            done.set()
            self._log_cgroup("end")

    def _internal_error(self, exc: BaseException) -> None:
        # Redacted and without local variables everywhere it goes: stdout (the platform logstream), log, state.
        print(f"coder job {self.spec.job_id}: unhandled {type(exc).__name__}\n{self.store.redact.traceback(exc)}",
              flush=True)
        try:
            self._finish(Status.FAILED, "internal-error", self.store.redact.traceback(exc, limit=TRACEBACK_CHARS))
        except Exception as failure:
            print(f"coder job {self.spec.job_id}: could not record the failure\n"
                  f"{self.store.redact.traceback(failure)}", flush=True)
        self._release_lease()

    def _release_lease(self) -> None:
        """After a crash the orchestrator may never see a clean end, so free the issue for the next attempt."""
        try:
            pat = self._pat or self.deps.secrets.get_secret("github-pat")
            self.deps.github(pat).delete_branch(f"{LEASE_PREFIX}{self.spec.issue_number}")
            self._log(f"released lease {LEASE_PREFIX}{self.spec.issue_number}")
        except Exception as exc:
            self._log(f"could not release lease {LEASE_PREFIX}{self.spec.issue_number}: {type(exc).__name__}: {exc}")

    def _heartbeat(self, done: threading.Event) -> None:
        """Save state every HEARTBEAT_S (status shows how stale it is) and stop a job stuck past its deadline."""
        while not done.wait(HEARTBEAT_S):
            try:
                self._checkpoint()
                over = self._elapsed() - self.spec.deadline_s
                if over > WATCHDOG_GRACE_S and not self._watchdog_fired:
                    self._watchdog_fired = True
                    # Recorded before cancelling, so status reports it even if the step never returns.
                    self.state.status, self.state.reason = Status.TIMEOUT, "deadline"
                    self.state.detail = (f"watchdog: still in phase {self.state.phase} {over:.0f}s past "
                                         f"deadline_s={self.spec.deadline_s}; cancelled")
                    self._checkpoint()
                    self._log(self.state.detail)
                    print(f"coder job {self.spec.job_id}: {self.state.detail}", flush=True)
                    self.cancel.set()   # every shell.run polls it and kills its process group
                    if self._run_as is not None:
                        self.deps.reap(self._run_as)
            except Exception as exc:
                print(f"coder job {self.spec.job_id}: heartbeat failed\n{self.store.redact.traceback(exc)}", flush=True)

    def _log_cgroup(self, when: str) -> None:
        memory = shell.cgroup_memory()
        if memory:
            self._log(f"{when}: {memory}")

    def _log_memory(self, step: str) -> None:
        peak = shell.take_memory()
        if peak is not None:
            self._log(f"memory {step}: {peak.describe()}")

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
        # Deadline first: the watchdog cancels a job that overran, and that is a timeout, not a cancel.
        if self._elapsed() >= self.spec.deadline_s:
            raise JobStop(Status.TIMEOUT, "deadline", f"deadline_s={self.spec.deadline_s} reached")
        if self.cancel.is_set():
            raise JobStop(Status.CANCELLED, "cancelled")

    def _timeout(self, cap: int) -> int:
        return max(1, int(min(cap, self.spec.deadline_s - self._elapsed())))

    # -- step 1: setup ---------------------------------------------------------------------

    def _setup(self) -> None:
        self._checkpoint(Phase.SETUP)
        # Fail closed: agy, install and tests run code nobody reviewed, so they never run as root.
        self._run_as = self.deps.engine_user()
        if self._run_as is None:
            raise JobStop(Status.FAILED, "sandbox-unavailable",
                          "could not create the unprivileged engine user; agy, install and tests never run as root")
        self.state.agy_user = self.state.tests_user = self._run_as.name
        sandbox.ensure_shell_files(self._run_as)
        self._log(f"agy_user: {self.state.agy_user}")
        self._log(f"tests_user: {self.state.tests_user}")
        tools = self.deps.toolchain
        tools.ensure_git()
        tools.ensure_node()
        self._pat = self.deps.secrets.get_secret("github-pat")
        self.store.redact.add(self._pat)
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
            self._last_sha = self._start_sha = self.git.head_sha()
        elif not self.spec.mode.writes_red_tests:
            raise JobStop(Status.FAILED, "branch-missing", f"{self.spec.branch} does not exist")
        else:
            self.git.checkout_new_branch(self.spec.branch, base=self.spec.base)
            self._last_sha = self.git.head_sha()
        if not self.spec.mode.writes_red_tests:
            self._check_allowed_paths()
        self._install()

    def _check_allowed_paths(self) -> None:
        """revise and maintenance work on an existing branch: allowed_paths must name something there."""
        tracked = self.git.tracked_files()
        missing = [a for a in self.spec.allowed_paths if not any(scope.within_allowed(t, (a,)) for t in tracked)]
        if not missing:
            return
        kept = tuple(a for a in self.spec.allowed_paths if a not in missing)
        if not kept:
            raise JobStop(Status.FAILED, "invalid-allowed-paths",
                          f"allowed_paths match no file at the head of {self.spec.branch}: {', '.join(missing)}")
        self._log(f"ignoring allowed_paths that match no file at the branch head: {', '.join(missing)}")
        self.spec = dataclasses.replace(self.spec, allowed_paths=kept)

    def _prepare_agy(self) -> Path:
        """agy ready to run as the engine user, retried once. Without it the job stops: the model loop
        alone repaired tests blind (job j-pr33-1), so a new attempt is better than a weaker engine."""
        reason = ""
        for attempt in range(1, AGY_SETUP_ATTEMPTS + 1):
            step = "read the agy-cli-token secret"
            try:
                token = self.deps.secrets.get_secret("agy-cli-token")
                self.store.redact.add(token)
                step = "install agy"
                binary = self.deps.toolchain.ensure_agy()
                # Token and allow-list live in the engine user's home; the Key Vault read stayed in this process.
                owner = (self.user.uid, self.user.gid)
                step = "write the agy token"
                self.deps.toolchain.write_agy_token(token, home=self.user.home, owner=owner)
                step = "write the agy settings"
                self._log_settings(self.deps.toolchain.write_agy_settings(home=self.user.home, owner=owner))
                step = "copy agy to /opt/agy"
                return self.deps.agy_installer(binary)
            except Exception as exc:
                reason = self.store.redact(f"{step}: {type(exc).__name__}: {exc}")[-1500:]
                self._log(f"agy unavailable (attempt {attempt} of {AGY_SETUP_ATTEMPTS}): {reason}")
        self._engine_event("agy", "agy-unavailable", detail=reason)
        raise JobStop(Status.FAILED, "engine-unavailable", reason)

    # -- running untrusted code (agy, install, tests): always as the engine user --------------

    @property
    def user(self) -> sandbox.RunAs:
        assert self._run_as is not None, "engine user used before setup"
        return self._run_as

    def _work_env(self) -> dict[str, str]:
        assert self._node_bin is not None
        return sandbox.user_env(self.user, self._node_bin)

    def _as_user(self) -> dict[str, int]:
        return {"user": self.user.uid, "group": self.user.gid}

    def _quiesce(self) -> None:
        """Kill every engine-user process; root only touches the user's tree while nothing of it runs."""
        if self._run_as is not None:
            left = self.deps.reap(self._run_as)
            if left:
                raise JobStop(Status.FAILED, "error", f"{left} {self._run_as.name} processes survived SIGKILL")

    def _hand_over(self) -> None:
        self._quiesce()
        sandbox.give_tree(self.checkout, self.user)

    def _snapshot(self) -> tuple[str, dict[str, str]]:
        self._quiesce()
        return self.git.metadata_digest(), self._inventory().symlinks

    def _inventory(self) -> sandbox.Inventory:
        return sandbox.inventory(self.checkout, owner_uid=self.user.uid)

    def _push(self, sha: str) -> None:
        """Push exactly the commit root verified, with no engine-user process alive."""
        self._check_stops()
        self._quiesce()
        self.git.push(self.spec.branch, sha=sha)

    def _report_path(self) -> Path:
        reports = self.checkout.parent / "reports"
        reports.mkdir(mode=0o700, exist_ok=True)
        os.lchown(reports, self.user.uid, self.user.gid)
        return reports / "report.json"

    def _install(self) -> None:
        if not self.spec.install_cmd.strip():
            return
        result = self._run_untrusted(self.spec.install_cmd, "install", INSTALL_TIMEOUT_S)
        self._log(f"install ({result.returncode}): {result.output[-3000:]}")
        if result.returncode != 0:
            self._check_stops()
            raise JobStop(Status.FAILED, "install-failed", result.output[-1500:])

    def _run_untrusted(self, cmd: str, step: str, cap: int) -> CommandResult:
        """Run a job command as the engine user in the workdir, then scan what it left behind."""
        self._hand_over()
        before = self._snapshot()
        result = shell.run(cmd, cwd=self.checkout / self.spec.workdir, env=self._work_env(),
                           timeout_s=self._timeout(cap), cancel=self.cancel, **self._as_user())
        self._log_memory(step)
        self._quiesce()
        self._scan(before, step)
        return result

    def _run_checks(self) -> list[checks.CheckResult]:
        results = []
        for cmd in checks.CHECK_COMMANDS:
            self._check_stops()
            raw = self._run_untrusted(cmd, cmd, CHECK_TIMEOUT_S)
            result = checks.parse(cmd, raw.returncode, raw.output, str(self.checkout))
            self._log("\n".join([result.summary(), *result.lines()]))
            results.append(result)
        self._check_stops()
        return results

    def _checks_if_green(self, outcome: TestOutcome, must_pass: tuple[str, ...]) -> list[checks.CheckResult]:
        """Typecheck and lint only once the tests pass; an empty list means not run."""
        return self._run_checks() if self._green(outcome, must_pass) else []

    def _check_lines(self, results: list[checks.CheckResult]) -> list[str]:
        lines = [line for r in results for line in r.lines()][:checks.MAX_CHECK_LINES]
        return [self.store.redact(line) for line in lines]

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
        # Errors in the new test files are the designer's to fix (the engine may not edit them); errors
        # elsewhere would exist on main too and are not the tests' fault, so they only block green later.
        broken = checks.errors_in(self._run_checks(), [t.path for t in self.spec.tests], workdir=self.spec.workdir)
        if broken:
            raise JobStop(Status.FAILED, "tests-invalid", "\n".join(broken[:20]))
        outcome = self._run_tests()
        verdict = outcome.report.red_verdict([t.path for t in self.spec.tests])
        if verdict.kind == "invalid":
            # Broken tests go back to the test designer; the coder never implements against them.
            raise JobStop(Status.FAILED, "tests-invalid", "\n".join(verdict.invalid[:20]))
        if verdict.kind != "red":
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
        self._failing = tuple(outcome.report.failing_paths(str(self.checkout)))
        self._log_memory("tests")
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
        agy_home = self.user.home
        engines = self.deps.engines(EngineContext(self.spec, protected, tests_only, self.cancel,
                                                  self.deps.toolchain.env(), self._agy, agy_home, self._run_as,
                                                  dirty=lambda: bool(self.git.changed_paths()),
                                                  refresh_agy_settings=self._refresh_agy_settings,
                                                  agy_log_dir=self._agy_log_dir(),
                                                  round_no=lambda: self.state.iterations + 1,
                                                  failing=lambda: self._failing))
        self._protected, self._tests_only = protected, tests_only
        current = 0
        rejected: tuple[TestOutcome, list[checks.CheckResult]] | None = None   # a reverted round's results
        idle_rounds = 0   # consecutive rounds in which the current engine changed nothing (or was reverted)
        rounds = 0        # rounds the current engine has had
        outcome = self._run_tests()
        # The suites that define done: the new tests, or in maintenance the ones failing at the start.
        must_pass = red_files or tuple(outcome.report.failing_paths(str(self.checkout)))
        found = self._checks_if_green(outcome, must_pass)
        # A revise job exists to put a new head on the PR, so green alone is not done until it commits.
        committed = self.spec.mode is not Mode.REVISE
        while True:
            if committed and self._done(outcome, must_pass, found):
                if not self.spec.install_cmd.strip():
                    break
                outcome = self._clean_rerun()
                found = self._checks_if_green(outcome, must_pass)
                if self._done(outcome, must_pass, found):
                    break
                self._log("green did not hold after a clean install; continuing")
            self._check_stops()
            if self.state.iterations >= self.spec.max_iterations:
                raise JobStop(Status.FAILED, "max-iterations",
                              "\n".join([outcome.report.summary(), *self._check_lines(found)]))
            if current >= len(engines):
                raise JobStop(Status.FAILED, "engines-exhausted", "every engine in the chain failed")
            engine = engines[current]
            if engine.name in GUARDED_ENGINES and not found:
                found = self._run_checks()   # the baseline its rounds are judged against
            pre = self.git.head_sha()
            before = self._snapshot()
            started = self.deps.clock.monotonic()
            shown, rejected = rejected, None
            result = self._edit(engine, *(shown or (outcome, found)), red_files, reverted=shown is not None)
            self._engine_event(engine.name, "round", iteration=self.state.iterations + 1,
                               seconds=round(self.deps.clock.monotonic() - started),
                               timed_out=bool(getattr(engine, "last_timed_out", False)),
                               returncode=result.returncode)
            self._account(engines)
            self._quiesce()
            self._scan(before, f"engine {engine.name}")
            changed = self._contain(pre)
            if result.returncode != 0:
                self._check_stops()
                self._log(f"engine {engine.name} failed ({result.returncode}), falling back: {result.output[-1500:]}")
                self.git.revert_paths(changed)
                current, rounds = current + 1, 0
                continue
            self.state.iterations += 1
            rounds += 1
            used_up = rounds >= ENGINE_MAX_ROUNDS.get(engine.name, self.spec.max_iterations)
            self.state.engine = engine.name
            self._check_stops()
            if not changed:
                idle_rounds += 1
                if SOFT_DENY.search(result.output):
                    self._engine_event(engine.name, "engine-permission-denied")
                    current, idle_rounds, rounds = current + 1, 0, 0   # next: agy-unrestricted, then the loop
                elif used_up or idle_rounds >= NO_PROGRESS_ROUNDS:
                    self._engine_event(engine.name, "engine-no-progress")
                    current, idle_rounds, rounds = current + 1, 0, 0
                self._checkpoint()
                continue
            self._enforce_scope(changed, pre, protected, tests_only)
            if engine.name in GUARDED_ENGINES:
                candidate, tried = self._run_tests(), self._run_checks()
                if not _better(_score(candidate, tried), _score(outcome, found)):
                    self.git.revert_paths(self.git.changed_since(pre))
                    self._engine_event(engine.name, "reverted", tests=candidate.report.summary(),
                                       checks=", ".join(r.summary() for r in tried))
                    rejected = (candidate, tried)
                    idle_rounds += 1
                    if idle_rounds >= NO_PROGRESS_ROUNDS:
                        self._engine_event(engine.name, "engine-no-progress")
                        current, idle_rounds, rounds = current + 1, 0, 0
                    self._checkpoint()
                    continue
                idle_rounds = 0
                committed = self._commit_iteration(changed, protected, tests_only) or committed
                outcome, found = candidate, tried
                self._checkpoint()
                continue
            idle_rounds = 0
            if used_up:
                current, rounds = current + 1, 0   # agy: one round, agy-unrestricted: two, then the loop
            committed = self._commit_iteration(changed, protected, tests_only) or committed
            outcome = self._run_tests()
            found = self._checks_if_green(outcome, must_pass)
            self._checkpoint()
        self.state.green_summary = "\n".join([outcome.report.summary(), *(r.summary() for r in found)])

    @staticmethod
    def _green(outcome: TestOutcome, must_pass: tuple[str, ...]) -> bool:
        return outcome.green and outcome.report.suites_passed(must_pass)

    @classmethod
    def _done(cls, outcome: TestOutcome, must_pass: tuple[str, ...], found: list[checks.CheckResult]) -> bool:
        """CI's `test` job: the tests pass, then typecheck and lint pass."""
        return cls._green(outcome, must_pass) and bool(found) and all(r.passed for r in found)

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
        # Checked before any root git call: a nested repository's own config could make root's git run code.
        found = self._inventory()
        if found.nested_git:
            for path in found.nested_git:
                target = self.checkout / path
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            raise JobStop(Status.FAILED, "scope-violation",
                          f"{step} created nested git repositories (removed): " + ", ".join(found.nested_git))
        added = sorted({path for path, target in found.symlinks.items() if links.get(path) != target}
                       | set(found.escaping))
        if added:
            for path in added:
                os.unlink(self.checkout / path)
            raise JobStop(Status.FAILED, "scope-violation",
                          f"{step} created symlinks or links leaving the checkout (removed): " + ", ".join(added))

    def _contain(self, pre: str) -> list[str]:
        """Everything the engine changed since `pre`, even if it ran git itself; it must stay on the branch."""
        branch = self.git.current_branch()
        if branch != self.spec.branch:
            raise JobStop(Status.FAILED, "scope-violation", f"engine switched the checkout to {branch}")
        if self.git.head_sha() != pre:
            self._log("engine created commits; undoing them so its edits are checked like any other change")
            self.git.reset_soft(pre)
        return self.git.changed_since(pre)

    def _edit(self, engine: CodingEnginePort, outcome: TestOutcome, found: list[checks.CheckResult],
              red_files: tuple[str, ...], *, reverted: bool = False) -> CommandResult:
        iteration = self.state.iterations + 1
        self._log(f"iteration {iteration} with engine {engine.name}")
        prompt = self._prompt(outcome, red_files, found)
        if reverted:
            prompt = ("Your previous change was reverted: it did not reduce the failures without adding new "
                      "errors. Its test, typecheck and lint results are below; try a different change.\n\n" + prompt)
        result = engine.edit(prompt, workdir=str(self.checkout),
                             timeout_s=self._timeout(EDIT_TIMEOUT_S))
        self._log_memory(f"engine {engine.name}")
        self._log(f"{engine.name} output (iteration {iteration}) exit {result.returncode}:\n{result.output[-4000:]}")
        self._quiesce()
        self._log_agy_debug(engine, iteration)
        return result

    def _refresh_agy_settings(self) -> None:
        """Rewrite agy's settings.json from the constant: whatever agy changed in an earlier round is gone."""
        self._quiesce()
        path = self.deps.toolchain.write_agy_settings(home=self.user.home, owner=(self.user.uid, self.user.gid))
        self._log(f"agy settings rewritten, sha256 {hashlib.sha256(AGY_SETTINGS_BYTES).hexdigest()[:16]}")
        self._log_settings(path)

    def _log_settings(self, path: Path) -> None:
        try:
            info = os.lstat(path)
            self._log(f"agy settings {path} mode {stat.S_IMODE(info.st_mode):04o} owner {info.st_uid}:{info.st_gid}")
        except OSError as exc:
            self._log(f"agy settings {path} not readable: {exc}")

    def _agy_log_dir(self) -> Path:
        return self._report_path().parent

    def _log_agy_debug(self, engine: CodingEnginePort, iteration: int) -> None:
        """A filtered, redacted excerpt of agy's own debug log: was the allow-list loaded, what was refused."""
        for path in getattr(engine, "last_logs", ()):
            try:
                text = sandbox.safe_read(path, max_bytes=AGY_LOG_READ_BYTES, tail=True).decode("utf-8", "replace")
            except sandbox.UnsafePathError:
                self._log(f"agy log (iteration {iteration}): {path.name} unreadable")
                continue
            lines = [line for line in text.splitlines() if AGY_LOG_LINES.search(line)]
            excerpt = "\n".join(lines)
            if len(excerpt) > AGY_LOG_EXCERPT_CHARS:
                settings = [line for line in lines if "CLI settings initialized" in line][:1]
                excerpt = "\n".join(settings) + "\n...\n" + excerpt[-AGY_LOG_EXCERPT_CHARS:]
            self._log(f"agy log (iteration {iteration}) {path.name}:\n{excerpt or '(no permission lines)'}")

    def _engine_event(self, engine: str, reason: str, **extra: Any) -> None:
        event = {"iteration": self.state.iterations, "engine": engine, "reason": reason, **extra}
        self.state.engine_events.append(event)
        details = " ".join(f"{k}={v}" for k, v in extra.items() if k != "iteration")
        self._log(f"iteration {event['iteration']}: {engine} {reason} {details}".rstrip())

    def _account(self, engines: list[CodingEnginePort]) -> None:
        used_in = sum(e.usage.input_tokens for e in engines if hasattr(e, "usage"))
        used_out = sum(e.usage.output_tokens for e in engines if hasattr(e, "usage"))
        self.state.input_tokens = self._tokens_before[0] + used_in
        self.state.output_tokens = self._tokens_before[1] + used_out
        self.state.model_usd = token_usd(self.state.input_tokens, self.state.output_tokens)
        if self.state.model_usd > self.spec.max_model_usd:
            raise JobStop(Status.FAILED, "cost-cap",
                          f"model spend {self.state.model_usd:.4f} USD over {self.spec.max_model_usd} USD")

    def _enforce_scope(self, changed: list[str], pre: str, protected: tuple[str, ...], tests_only: bool) -> None:
        bad = scope.violations(changed, allowed_paths=self.spec.allowed_paths, protected=protected,
                               tests_only=tests_only)
        bad += [p for p in self.git.special_paths_since(pre) if p not in bad]   # gitlinks and symlinks
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
        self._verify_commit(sha)   # what the commit actually contains; only that exact commit is ever pushed
        self._last_sha = sha
        self._engine_event(self.state.engine or "", "committed", sha=sha)
        if self.spec.mode.writes_red_tests:
            self._push(sha)   # our own branch: every commit is a checkpoint a resumed job continues from
        return True

    def _verify_commit(self, sha: str) -> None:
        bad = scope.violations(self.git.files_in_commit(sha), allowed_paths=self.spec.allowed_paths,
                               protected=self._protected, tests_only=self._tests_only)
        bad += self.git.special_paths_in_commit(sha)
        if bad:
            raise JobStop(Status.FAILED, "scope-violation", "commit contained out-of-scope paths: " + ", ".join(bad))

    def _squash(self) -> str:
        """revise and maintenance push to a branch a person owns: one commit, made only once green."""
        n = self.spec.issue_number
        message = (f"test: repair stale tests for #{n}" if self.spec.mode is Mode.MAINTENANCE
                   else f"fix: address review findings for #{n}")
        self.git.reset_soft(self._start_sha)
        sha = self.git.commit_all(message)
        self._verify_commit(sha)
        self._engine_event(self.state.engine or "", "squashed", sha=sha)
        return sha

    def _title(self) -> str:
        return " ".join(self.spec.issue_title.split())[:72] or f"issue {self.spec.issue_number}"

    def _prompt(self, outcome: TestOutcome, red_files: tuple[str, ...], found: list[checks.CheckResult]) -> str:
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
        failing = "\n".join(f"- {path} > {name}: {line}" for path, name, line
                            in outcome.report.failing_tests(str(self.checkout))[:MAX_FAILING_LISTED])
        how = ("How to work: read the failing test first, make the smallest change that satisfies it, "
               "do not edit any test file. "
               f"The only shell commands you may run are: {AGY_COMMANDS_HELP}. Anything else is denied.")
        return (
            f"{task}\n\n{how}\n\n"
            f"Repository checkout: the current directory. Tests run with `{s.test_cmd}` in `{s.workdir}`.\n\n"
            f"Failing tests:\n{_untrusted(failing or '(none reported)')}\n\n"
            f"Issue #{s.issue_number}:\n{_untrusted(s.issue_title + chr(10) + s.issue_body[:ISSUE_BODY_CHARS])}\n\n"
            f"Acceptance criteria:\n{_untrusted(criteria)}\n\nNotes:\n{_untrusted(s.notes or '(none)')}\n\n"
            f"Current failing test output:\n{_untrusted(outcome.feedback(FEEDBACK_CHARS))}\n"
            + self._checks_prompt(found)
        )

    def _checks_prompt(self, found: list[checks.CheckResult]) -> str:
        lines = self._check_lines(found)
        if not lines:
            return ""
        commands = " and ".join(f"`{c}`" for c in checks.CHECK_COMMANDS)
        return (f"\nCI also runs {commands} in `{self.spec.workdir}` and they fail. "
                f"Fix these within the rules above. Typecheck and lint errors:\n"
                f"{_untrusted(chr(10).join(lines))}\n")

    # -- step 4: push and PR ---------------------------------------------------------------

    def _publish(self) -> None:
        self._checkpoint(Phase.PUSH)
        if self.spec.mode.writes_red_tests:
            self._push(self._last_sha)
        elif self.git.head_sha() != self._start_sha:
            self._push(self._squash())
        if not self.spec.mode.writes_red_tests:
            # revise and maintenance update the PR they were given; they never open one.
            number = self.spec.pr_number
            self.state.pr = {"number": number, "url": f"https://github.com/{REPO}/pull/{number}"}
            return
        self._checkpoint(Phase.PR)
        github = self.deps.github(self._pat)
        # Only our own PR on this repository: anyone can open a PR from a branch with the same name.
        existing = [p for p in github.list_pulls(state="open")
                    if p.head_ref == self.spec.branch and p.author == OWNER and p.head_repo == REPO]
        title = f"{self.spec.mode.commit_prefix}: {self._title()} (#{self.spec.issue_number})"
        pr = existing[0] if existing else github.create_pull(
            title=title, head=self.spec.branch, base=self.spec.base, body=self.store.redact(self._pr_body()))
        github.add_labels(pr.number, (AGENT_PR_LABEL,))
        self.state.pr = {"number": pr.number, "url": f"https://github.com/{REPO}/pull/{pr.number}"}
        self._log(f"pull request #{pr.number} {'reused' if existing else 'opened'}")

    def _pr_body(self) -> str:
        red_output = self._red_output or "(red verified in an earlier run of this job)"
        commits = "\n".join(f"- {e['sha'][:12]} {e['engine']}" for e in self.state.engine_events
                            if e["reason"] == "committed") or "- (none)"
        return (
            f"Closes #{self.spec.issue_number}\n\n"
            f"Engine: {ENGINE_LABELS.get(self.state.engine or '', self.state.engine)}\n"
            f"Iterations: {self.state.iterations}\n"
            f"Commits:\n{commits}\n"
            f"Engine user: {self.state.agy_user}\nTests user: {self.state.tests_user}\n\n"
            f"## Red (tests committed first)\n\n{self.state.red_summary or 'red commit on branch'}\n\n"
            f"```\n{red_output}\n```\n\n"
            f"## Green\n\n{self.state.green_summary}\n"
        )


def _score(outcome: TestOutcome, found: list[checks.CheckResult]) -> tuple[float, float, float]:
    """(files that fail to load, failing assertions, typecheck and lint errors); lower is better."""
    report = outcome.report
    if not report.parsed:
        return math.inf, math.inf, math.inf
    errors = sum(len(r.errors) or (0 if r.passed else 1) for r in found)
    return len(report.load_errors), report.failed, errors


def _better(new: tuple[float, ...], old: tuple[float, ...]) -> bool:
    """Strictly better: nothing got worse and something got better."""
    return all(n <= o for n, o in zip(new, old, strict=True)) and new != old


class CoderService:
    """Maps Invocations request bodies to jobs. One background thread per running job."""

    def __init__(self, store: JobStore, deps: CoderDeps):
        self._store = store
        self._deps = deps
        self._threads: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self._lock = threading.Lock()
        self._sweep()

    @property
    def redact(self) -> Redactor:
        return self._store.redact

    def _sweep(self) -> None:
        """A (re)started server has no job threads: whatever was left running died with the last process."""
        for job_id in self._store.job_ids():
            try:
                state = self._store.load(job_id)
                if state is not None and state.status is Status.RUNNING:
                    with self._lock:
                        self._settle(state)
                    print(f"coder: job {job_id} was running when the server restarted; marked interrupted",
                          flush=True)
            except Exception as exc:
                print(f"coder: could not read job {job_id}\n{self._store.redact.traceback(exc)}", flush=True)

    def handle_raw(self, raw: bytes, *, session_id: str = "") -> tuple[int, dict[str, Any]]:
        """Never raises: a bug in one request is a 500 and a logged traceback, not a dead server."""
        try:
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                return 400, {"error": "invalid_json"}
            return self.handle(body, session_id=session_id)
        except Exception as exc:
            print(f"coder: request failed\n{self._store.redact.traceback(exc)}", flush=True)
            return 500, {"error": "internal_error"}

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
                return 200, self._view(state)
            if state is None:
                refused = self._take_lease(spec)
                if refused is not None:
                    return 200, refused
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

    def _take_lease(self, spec: JobSpec) -> dict[str, Any] | None:
        """Atomically claim the issue (ref agent-lease/<issue>); None on success, else the refusal.

        Only a new job takes it: a resumed or retried job already holds it. The orchestrator releases it.
        """
        refusal = {"job_id": spec.job_id, "status": Status.FAILED.value}
        try:
            pat = self._deps.secrets.get_secret("github-pat")
            self._store.redact.add(pat)
            github = self._deps.github(pat)
            base = github.get_branch_sha(spec.base)
            if base is None:
                return {**refusal, "reason": "lease-error", "detail": f"base branch {spec.base} not found"}
            github.create_branch(f"{LEASE_PREFIX}{spec.issue_number}", from_sha=base)
        except GitHubError as exc:
            if exc.status == 422:
                return {**refusal, "reason": "lease-held"}
            return {**refusal, "reason": "lease-error", "detail": self._store.redact(str(exc))}
        except Exception as exc:
            return {**refusal, "reason": "lease-error", "detail": self._store.redact(f"{type(exc).__name__}: {exc}")}
        return None

    def status(self, job_id: str) -> tuple[int, dict[str, Any]]:
        with self._lock:
            state = self._settle(self._store.load(job_id))
        if state is None:
            return 404, {"error": "unknown_job", "job_id": job_id}
        return 200, self._view(state)

    def _view(self, state: JobState) -> dict[str, Any]:
        return state.view(self._store.tail(state.job_id), usd_per_hour=self._usd_per_hour,
                          now=self._deps.clock.now_iso())

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
