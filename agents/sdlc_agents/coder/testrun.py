"""
Run the job's test command and decide red or green from the vitest JSON report.

Red means: every new suite was collected and loaded, and at least one assertion in a new
suite failed. A file that fails to import has status "failed" with no failed assertion;
that is a broken test, not red evidence. Green means: the report parsed, has tests, and
nothing failed (assertions or file loads), and the command exited 0.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sdlc_agents.coder import sandbox, scope, shell

EXCERPT_CHARS = 6000
MAX_REPORT_BYTES = 50 * 1024 * 1024


def with_json_reporter(test_cmd: str, report_path: str) -> str:
    args = shlex.join(["--reporter=default", "--reporter=json", f"--outputFile.json={report_path}"])
    # npm forwards arguments to the script only after "--"; reuse one the command already has.
    words = test_cmd.split()
    separator = " -- " if words[0] == "npm" and "--" not in words else " "
    return f"{test_cmd}{separator}{args}"


# A red test must fail because the behaviour is missing, not because the test itself is broken.
_INVALID_FAILURE = re.compile(r"ReferenceError|TypeError|SyntaxError|is not defined|is not a function|"
                              r"Cannot find module|Failed to resolve import|does not provide an export|timed out",
                              re.IGNORECASE)
_VALID_FAILURE = re.compile(r"AssertionError|expected|Unable to find|TestingLibraryElementError", re.IGNORECASE)


def _first_line(message: str) -> str:
    return next((line.strip() for line in message.splitlines() if line.strip()), "")[:300]


def is_valid_red(message: str) -> bool:
    """An assertion failure (incl. Testing Library queries); errors, bad imports and timeouts are not."""
    head = message.split("\n    at ", 1)[0]
    return not _INVALID_FAILURE.search(head) and bool(_VALID_FAILURE.search(head))


@dataclass(frozen=True)
class RedVerdict:
    kind: str                       # "red" | "not-red" | "invalid"
    invalid: tuple[str, ...] = ()   # one line per broken new test: "<path> > <test>: <first error line>"


@dataclass(frozen=True)
class FileResult:
    name: str             # absolute path as reported by vitest
    status: str
    message: str
    failed: tuple[str, ...]   # failure messages of failed assertions
    statuses: tuple[str, ...] = ()   # status of every assertion: passed, failed, skipped, pending, todo
    failed_names: tuple[str, ...] = ()   # full names of the failed assertions, same order as `failed`

    def is_for(self, repo_path: str) -> bool:
        return self.name == repo_path or self.name.endswith("/" + repo_path)

    @property
    def load_error(self) -> bool:
        return self.status == "failed" and not self.failed


@dataclass(frozen=True)
class TestReport:
    __test__ = False  # not a pytest class

    parsed: bool
    total: int = 0
    failed: int = 0
    passed: int = 0
    success: bool = False
    files: tuple[FileResult, ...] = ()

    @property
    def load_errors(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.files if f.load_error)

    @property
    def green(self) -> bool:
        return self.parsed and self.success and self.total > 0 and self.failed == 0 and not self.load_errors

    def is_red_for(self, new_paths: Iterable[str]) -> bool:
        return self.red_verdict(new_paths).kind == "red"

    def red_verdict(self, new_paths: Iterable[str]) -> RedVerdict:
        """Red only when the new suites fail on assertions alone. A new test that errors (not defined,
        bad import, timeout, ...) or a new suite vitest did not collect makes the tests invalid."""
        if not self.parsed:
            return RedVerdict("not-red")
        suites = [p for p in new_paths if scope.is_suite_path(p)]
        invalid: list[str] = []
        valid = 0
        for path in suites:
            hits = [f for f in self.files if f.is_for(path)]
            if not hits:
                invalid.append(f"{path}: not collected by vitest (check the file name and location)")
            for f in hits:
                if f.load_error:
                    invalid.append(f"{path}: {_first_line(f.message) or 'failed to load'}")
                for name, message in zip(f.failed_names, f.failed, strict=False):
                    if is_valid_red(message):
                        valid += 1
                    else:
                        invalid.append(f"{path} > {name}: {_first_line(message)}")
        if invalid:
            return RedVerdict("invalid", tuple(invalid))
        return RedVerdict("red" if suites and valid else "not-red")

    def suites_passed(self, paths: Iterable[str]) -> bool:
        """Every suite in `paths` was collected and every one of its assertions ran and passed."""
        for path in (p for p in paths if scope.is_suite_path(p)):
            hits = [f for f in self.files if f.is_for(path)]
            if not hits or any(f.status != "passed" or not f.statuses or set(f.statuses) != {"passed"}
                               for f in hits):
                return False
        return True

    def failing_tests(self, root: str) -> list[tuple[str, str, str]]:
        """(repo-relative file, test name, first assertion line) for every failure, load errors included."""
        real_root = os.path.realpath(root)
        found: list[tuple[str, str, str]] = []
        for f in self.files:
            path = os.path.relpath(os.path.realpath(f.name), real_root)
            if f.load_error:
                found.append((path, "(file failed to load)", f.message.strip().splitlines()[0] if f.message else ""))
            for name, message in zip(f.failed_names, f.failed, strict=False):
                first = next((line.strip() for line in message.splitlines() if line.strip()), "")
                found.append((path, name, first))
        return found

    def failing_paths(self, root: str) -> list[str]:
        real_root = os.path.realpath(root)
        return [os.path.relpath(os.path.realpath(f.name), real_root) for f in self.files if f.status == "failed"]

    def summary(self) -> str:
        if not self.parsed:
            return "no test report"
        loads = sum(1 for f in self.files if f.load_error)
        return f"{self.total} tests: {self.failed} failed, {self.passed} passed, {loads} files failed to load"

    def failure_excerpt(self, limit: int = EXCERPT_CHARS) -> str:
        parts: list[str] = []
        for f in self.files:
            if f.load_error:
                parts.append(f"{f.name}: failed to load\n{f.message}")
            parts.extend(f"{f.name}\n{msg}" for msg in f.failed)
        return "\n\n".join(parts)[:limit]


def parse_vitest_json(text: str) -> TestReport:
    try:
        data: Any = json.loads(text)
        files = tuple(_file_result(r) for r in data["testResults"])
        return TestReport(
            parsed=True, total=int(data.get("numTotalTests", 0)), failed=int(data.get("numFailedTests", 0)),
            passed=int(data.get("numPassedTests", 0)), success=bool(data.get("success", False)), files=files,
        )
    except (ValueError, KeyError, TypeError, AttributeError):
        return TestReport(parsed=False)


def _file_result(raw: dict[str, Any]) -> FileResult:
    assertions = raw.get("assertionResults", [])
    failed = tuple("\n".join(a.get("failureMessages") or [a.get("fullName", "")])
                   for a in assertions if a["status"] == "failed")
    names = tuple(str(a.get("fullName") or a.get("title") or "") for a in assertions if a["status"] == "failed")
    return FileResult(name=str(raw["name"]), status=str(raw["status"]), message=str(raw.get("message") or ""),
                      failed=failed, statuses=tuple(str(a["status"]) for a in assertions), failed_names=names)


@dataclass(frozen=True)
class TestOutcome:
    __test__ = False  # not a pytest class

    returncode: int
    output: str
    report: TestReport

    @property
    def green(self) -> bool:
        return self.returncode == 0 and self.report.green

    def feedback(self, limit: int = EXCERPT_CHARS) -> str:
        """What the engine sees next iteration: structured failures, else the output tail."""
        excerpt = self.report.failure_excerpt(limit)
        return excerpt or self.output[-limit:]


class TestRunner:
    __test__ = False  # not a pytest class

    def __init__(self, *, test_cmd: str, cwd: Path, report_path: Path, env: dict[str, str] | None,
                 cancel: threading.Event | None = None, run_as: dict[str, int] | None = None):
        self._cmd = with_json_reporter(test_cmd, str(report_path))
        self._cwd = cwd
        self._report_path = report_path
        self._env = env
        self._cancel = cancel
        self._run_as = run_as or {}

    def run(self, *, timeout_s: float) -> TestOutcome:
        self._report_path.unlink(missing_ok=True)
        result = shell.run(self._cmd, cwd=self._cwd, env=self._env, timeout_s=timeout_s, cancel=self._cancel,
                           **self._run_as)
        try:   # the engine user writes the report: no links, no FIFOs, bounded size
            text = sandbox.safe_read(self._report_path, max_bytes=MAX_REPORT_BYTES).decode("utf-8", errors="replace")
        except sandbox.UnsafePathError:
            text = ""
        return TestOutcome(result.returncode, result.output, parse_vitest_json(text))
