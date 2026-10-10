"""
Typecheck and lint, the rest of CI's `test` job (vitest does not typecheck).

Output is parsed into one line per error, `<path>(line,col): error <code>: <message>`, from tsc
(paths relative to the workspace `npm run typecheck --workspaces` ran in) and eslint's stylish
format (absolute path headers, made relative to the checkout). Warnings never fail a check.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass

from sdlc_agents.coder.testrun import _repo_relative

CHECK_COMMANDS = ("npm run typecheck", "npm run lint")   # CI's `test` job runs these besides npm test (and build)
MAX_CHECK_LINES = 40
_TSC = re.compile(r"^(?P<path>\S[^(]*)\((?P<line>\d+),(?P<col>\d+)\): error (?P<code>TS\d+): (?P<message>.*)$")
_ESLINT_FILE = re.compile(r"^/\S.*$")
_ESLINT_ERROR = re.compile(r"^\s+(?P<line>\d+):(?P<col>\d+)\s+error\s+(?P<message>.+?)(?:\s{2,}(?P<rule>\S+))?\s*$")


@dataclass(frozen=True)
class CheckError:
    path: str      # as printed by tsc, or repo-relative for eslint
    line: int
    col: int
    code: str      # TS2322, or the eslint rule
    message: str

    def render(self, path: str | None = None) -> str:
        code = f"{self.code}: " if self.code else ""
        return f"{path or self.path}({self.line},{self.col}): error {code}{self.message}"


@dataclass(frozen=True)
class CheckResult:
    command: str
    returncode: int
    output: str
    errors: tuple[CheckError, ...]

    @property
    def passed(self) -> bool:
        return self.returncode == 0

    def lines(self, limit: int = MAX_CHECK_LINES) -> list[str]:
        """The errors, or (a failure nothing could be parsed from: missing script, crash) the output tail."""
        if self.passed:
            return []
        if self.errors:
            return [e.render() for e in self.errors[:limit]]
        return [line for line in self.output.strip().splitlines() if line.strip()][-limit:]

    def summary(self) -> str:
        if self.passed:
            return f"`{self.command}`: passed"
        return f"`{self.command}`: failed ({len(self.errors)} errors)"


def parse(command: str, returncode: int, output: str, root: str) -> CheckResult:
    errors: list[CheckError] = []
    current = ""   # eslint: the file the following problem lines belong to
    for line in output.splitlines():
        if m := _TSC.match(line):
            errors.append(CheckError(m["path"].strip(), int(m["line"]), int(m["col"]), m["code"], m["message"]))
        elif _ESLINT_FILE.match(line):
            current = _repo_relative(line.strip(), root)
        elif current and (m := _ESLINT_ERROR.match(line)):
            errors.append(CheckError(current, int(m["line"]), int(m["col"]), m["rule"] or "", m["message"]))
    return CheckResult(command, returncode, output, tuple(errors))


def errors_in(results: Iterable[CheckResult], repo_paths: Iterable[str], *, workdir: str) -> list[str]:
    """Errors reported against any of `repo_paths`, rendered with the repo path."""
    wanted = list(repo_paths)
    found: list[str] = []
    for result in results:
        for error in result.errors:
            hit = next((p for p in wanted if _same_file(error.path, p, workdir)), None)
            if hit:
                found.append(error.render(hit))
    return found


def _same_file(printed: str, repo_path: str, workdir: str) -> bool:
    # ponytail: tsc prints paths relative to its workspace, which npm does not name as a directory, so a
    # suffix match decides; two workspaces with the same relative test path would both match.
    clean = os.path.normpath(printed)
    parts = [p for p in clean.split(os.sep) if p != ".."]
    suffix = "/".join(parts)
    return repo_path in (clean, os.path.normpath(os.path.join(workdir, clean))) or repo_path.endswith("/" + suffix)
