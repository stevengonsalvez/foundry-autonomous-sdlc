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
import shlex
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sdlc_agents.coder import scope, shell

EXCERPT_CHARS = 6000


def with_json_reporter(test_cmd: str, report_path: str) -> str:
    args = shlex.join(["--reporter=default", "--reporter=json", f"--outputFile.json={report_path}"])
    # npm forwards arguments to the script only after "--"; reuse one the command already has.
    words = test_cmd.split()
    separator = " -- " if words[0] == "npm" and "--" not in words else " "
    return f"{test_cmd}{separator}{args}"


@dataclass(frozen=True)
class FileResult:
    name: str             # absolute path as reported by vitest
    status: str
    message: str
    failed: tuple[str, ...]   # failure messages of failed assertions
    statuses: tuple[str, ...] = ()   # status of every assertion: passed, failed, skipped, pending, todo

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
        if not self.parsed or self.load_errors:
            return False
        suites = [p for p in new_paths if scope.is_suite_path(p)]
        collected = {p: [f for f in self.files if f.is_for(p)] for p in suites}
        if not suites or any(not hits for hits in collected.values()):
            return False
        return any(f.failed for hits in collected.values() for f in hits)

    def suites_passed(self, paths: Iterable[str]) -> bool:
        """Every suite in `paths` was collected and every one of its assertions ran and passed."""
        for path in (p for p in paths if scope.is_suite_path(p)):
            hits = [f for f in self.files if f.is_for(path)]
            if not hits or any(f.status != "passed" or not f.statuses or set(f.statuses) != {"passed"}
                               for f in hits):
                return False
        return True

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
    return FileResult(name=str(raw["name"]), status=str(raw["status"]), message=str(raw.get("message") or ""),
                      failed=failed, statuses=tuple(str(a["status"]) for a in assertions))


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
        text = self._report_path.read_text(errors="replace") if self._report_path.exists() else ""
        return TestOutcome(result.returncode, result.output, parse_vitest_json(text))
