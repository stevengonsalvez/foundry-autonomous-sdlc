"""tdd-order gate: on an `agent/*` branch the tests come first, and they are red.

Commits between the merge base and the head are listed oldest first and each is
classified as test-only (every changed file matches a test glob) or not. The
branch passes when

  a. its first commit is test-only,
  b. the leading run of test-only commits ends before any other commit, and
  c. the test command fails at the tip of that leading run, in a clean worktree,
     with at least one failed test (a run that only fails to load test files
     is not red evidence), and
  d. later commits never modify or delete a test file that exists at that tip
     (adding new test files is fine), so the tests that were red cannot be edited green.

A branch made only of test-only commits (maintenance) passes with note `test-only`.
Any other branch passes with note `not-agent-branch`. Merge commits and commits
that change no files are rejected, because neither can be classified.

The failed-test count is read from the vitest or jest summary line
(`Tests  1 failed | 3 passed`); output without one is not accepted as red.

    python -m scripts.gates.tdd_order --base origin/main --head HEAD \\
        --branch agent/issue-12 --setup-cmd "npm ci --prefix app"
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .common import (
    EXIT_ERROR,
    GateError,
    GateResult,
    commit_changes,
    emit,
    git,
    glob_to_regex,
    is_agent_branch,
    merge_base,
    resolve_commit,
    tree_changes,
)

TEST_GLOBS = (
    "**/*.test.ts",
    "**/*.test.tsx",
    "**/*.spec.ts",
    "app/e2e/**",
    "**/tests/**",
    "**/__fixtures__/**",
)
DEFAULT_TEST_CMD = "npm test --prefix app"
DEFAULT_TIMEOUT_S = 900
EVIDENCE_TAIL_LINES = 25

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_TESTS_LINE = re.compile(r"^\s*Tests:?\s+(.*)$", re.MULTILINE)
_FILES_LINE = re.compile(r"^\s*Test (?:Files|Suites):?\s+(.*)$", re.MULTILINE)
_FAILED = re.compile(r"\b(\d+) failed")


_TEST_PATTERNS = tuple(glob_to_regex(g) for g in TEST_GLOBS)


def is_test_path(path: str) -> bool:
    return any(p.fullmatch(path) for p in _TEST_PATTERNS)


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    subject: str
    parents: int
    paths: tuple[str, ...]

    @property
    def test_only(self) -> bool:
        return bool(self.paths) and all(is_test_path(p) for p in self.paths)


def list_commits(repo: Path, fork_point: str, head: str) -> list[CommitInfo]:
    # Subjects are free text, so each is read on its own rather than parsed out of a stream.
    listing = git(
        repo, "rev-list", "--reverse", "--topo-order", "--parents", f"{fork_point}..{head}"
    )
    commits = []
    for line in listing.splitlines():
        sha, *parents = line.split()
        subject = git(repo, "log", "-1", "--format=%s", sha).strip()
        paths = tuple(sorted({c.path for c in commit_changes(repo, sha)}))
        commits.append(CommitInfo(sha, subject, len(parents), paths))
    return commits


@dataclass(frozen=True)
class RedOutcome:
    exit_code: int | None  # None when the command timed out
    failed_tests: int
    failed_suites: int
    tail: str


def parse_failed_tests(output: str) -> tuple[int, int]:
    """Return (failed tests, failed test files or suites) from a vitest or jest summary.

    The runner prints its summary last, so the last match wins and a lookalike line
    printed earlier by a test cannot fake red evidence.
    """
    text = _ANSI.sub("", output)
    return _failed_in_last(_TESTS_LINE, text), _failed_in_last(_FILES_LINE, text)


def _failed_in_last(line_pattern: re.Pattern[str], text: str) -> int:
    lines = line_pattern.findall(text)
    found = _FAILED.search(lines[-1]) if lines else None
    return int(found.group(1)) if found else 0


def _execute(cmd: str, cwd: Path, env: dict[str, str], timeout_s: int) -> tuple[int | None, str]:
    """Run a shell command; the exit code is None when it timed out."""
    # Own session so a timeout kills grandchildren too (npm spawns the test runner).
    proc = subprocess.Popen(
        cmd,
        shell=True,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        start_new_session=True,
    )
    try:
        output, _ = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        output, _ = proc.communicate()
        return None, output
    return proc.returncode, output


def run_red_check(
    repo: Path, sha: str, test_cmd: str, setup_cmd: str | None, timeout_s: int
) -> RedOutcome:
    scratch = Path(tempfile.mkdtemp(prefix="tdd-order-"))
    worktree = scratch / "worktree"
    git(repo, "worktree", "add", "--detach", str(worktree), sha)
    try:
        env = {**os.environ, "CI": "true", "NO_COLOR": "1", "FORCE_COLOR": "0"}
        if setup_cmd:
            code, output = _execute(setup_cmd, worktree, env, timeout_s)
            if code != 0:
                reason = "timed out" if code is None else f"exited {code}"
                raise GateError(f"setup command {reason}:\n{_tail(output)}")
        code, output = _execute(test_cmd, worktree, env, timeout_s)
        tests, suites = parse_failed_tests(output)
        return RedOutcome(code, tests, suites, _tail(output))
    finally:
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", "--force", str(worktree)],
            capture_output=True,
            check=False,
        )
        shutil.rmtree(scratch, ignore_errors=True)


def _tail(text: str) -> str:
    lines = _ANSI.sub("", text).rstrip().splitlines()
    return "\n".join(lines[-EVIDENCE_TAIL_LINES:])


def _indent(text: str) -> list[str]:
    return [f"    | {line}" for line in text.splitlines()]


def evaluate(
    repo: Path,
    base: str,
    head: str,
    branch: str,
    test_cmd: str = DEFAULT_TEST_CMD,
    setup_cmd: str | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> GateResult:
    if not is_agent_branch(branch):
        return GateResult(True, "not-agent-branch", [f"branch {branch!r} is not agent/*"])

    head_sha = resolve_commit(repo, head)
    fork_point = merge_base(repo, resolve_commit(repo, base), head_sha)
    commits = list_commits(repo, fork_point, head_sha)

    report = [f"branch {branch}", f"merge base {fork_point[:12]}", f"head {head_sha[:12]}"]
    report += [
        f"  {i + 1:>2}. {c.sha[:12]} {'test-only' if c.test_only else 'other    '} {c.subject}"
        for i, c in enumerate(commits)
    ]

    if not commits:
        return GateResult(False, "no-commits", [*report, "no commits between base and head"])
    merges = [c for c in commits if c.parents > 1]
    if merges:
        shown = ", ".join(c.sha[:12] for c in merges)
        return GateResult(
            False, "merge-commit", [*report, f"merge commit(s) cannot be classified: {shown}"]
        )
    empty = [c for c in commits if not c.paths]
    if empty:
        shown = ", ".join(c.sha[:12] for c in empty)
        return GateResult(False, "empty-commit", [*report, f"commit(s) change no files: {shown}"])

    if all(c.test_only for c in commits):
        return GateResult(True, "test-only", [*report, "every commit is test-only"])
    if not commits[0].test_only:
        first = commits[0]
        return GateResult(
            False,
            "first-commit-not-test-only",
            [
                *report,
                f"first commit {first.sha[:12]} changes non-test files; tests must come first",
            ],
        )

    leading = 0
    while commits[leading].test_only:
        leading += 1
    tip = commits[leading - 1]
    report.append(
        f"red check at {tip.sha[:12]} ({leading} leading test-only commit(s)): {test_cmd}"
    )

    outcome = run_red_check(repo, tip.sha, test_cmd, setup_cmd, timeout_s)
    report += _indent(outcome.tail)
    if outcome.exit_code is None:
        return GateResult(
            False, "tests-not-red", [*report, f"test command timed out after {timeout_s}s"]
        )
    if outcome.exit_code == 0:
        return GateResult(
            False, "tests-not-red", [*report, "tests passed before any implementation"]
        )
    if outcome.failed_tests == 0:
        return GateResult(
            False,
            "tests-not-red",
            [
                *report,
                "tests exited non-zero but no test failed an assertion"
                f" ({outcome.failed_suites} file(s) failed to load);"
                " load errors are not red evidence",
            ],
        )
    report.append(f"red: {outcome.failed_tests} failed test(s), exit code {outcome.exit_code}")

    # Red only means something if the tests that were red are the tests that later go green.
    edited = [
        c for c in tree_changes(repo, tip.sha, head_sha) if c.status != "A" and is_test_path(c.path)
    ]
    if edited:
        report.append(f"existing test files changed after the red commit ({len(edited)}):")
        report.extend(f"  {c.path!r} [{c.status}]" for c in edited)
        return GateResult(False, "tests-modified-after-red", report)
    return GateResult(True, "tests-first", report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", required=True, help="base ref or sha, e.g. origin/main")
    parser.add_argument("--head", default="HEAD", help="head ref or sha (default HEAD)")
    parser.add_argument("--branch", required=True, help="PR head branch name")
    parser.add_argument("--test-cmd", default=DEFAULT_TEST_CMD, help=f"default: {DEFAULT_TEST_CMD}")
    parser.add_argument("--setup-cmd", help="run once in the clean worktree before the tests")
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT_S, help="seconds per command"
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository (default cwd)")
    args = parser.parse_args(argv)

    try:
        result = evaluate(
            args.repo,
            args.base,
            args.head,
            args.branch,
            args.test_cmd,
            args.setup_cmd,
            args.timeout,
        )
    except GateError as exc:
        emit(GateResult(False, "error", [f"cannot evaluate: {exc}"]), sys.stdout)
        return EXIT_ERROR
    return emit(result, sys.stdout)


if __name__ == "__main__":
    sys.exit(main())
