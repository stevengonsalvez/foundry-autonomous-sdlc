"""Git plumbing and result reporting shared by the gate scripts."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

AGENT_BRANCH_PREFIX = "agent/"
SYMLINK_MODE = "120000"
GITLINK_MODE = "160000"

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2


class GateError(Exception):
    """The gate could not be evaluated (bad ref, git failure). Treated as a failure."""


@dataclass
class GateResult:
    passed: bool
    note: str
    report: list[str] = field(default_factory=list)

    def render(self) -> str:
        verdict = "pass" if self.passed else "fail"
        return "\n".join([*self.report, f"NOTE={self.note}", f"RESULT={verdict}"]) + "\n"


@dataclass(frozen=True)
class Change:
    """One path touched between two trees. Renames are reported as delete plus add."""

    status: str
    old_mode: str
    new_mode: str
    path: str

    @property
    def is_link(self) -> bool:
        return bool({self.old_mode, self.new_mode} & {SYMLINK_MODE, GITLINK_MODE})


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
        env=_git_env(),
    )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise GateError(f"git {' '.join(args)} failed: {detail}")
    return proc.stdout.decode("utf-8", "surrogateescape")


def _git_env() -> dict[str, str]:
    # Parsing relies on plain output; user config must not reshape it.
    return {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}


def resolve_commit(repo: Path, ref: str) -> str:
    try:
        return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()
    except GateError as exc:
        raise GateError(f"cannot resolve {ref!r} to a commit") from exc


def merge_base(repo: Path, base: str, head: str) -> str:
    try:
        return git(repo, "merge-base", base, head).strip()
    except GateError as exc:
        raise GateError(f"no merge base between {base} and {head}") from exc


def glob_to_regex(glob: str) -> re.Pattern[str]:
    """Compile a path glob: `*` stays inside a directory, `**/` spans zero or more."""
    out: list[str] = []
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("".join(out))


def is_agent_branch(branch: str) -> bool:
    name = branch.removeprefix("refs/heads/")
    # Case-insensitive on purpose: a case variant must not dodge the gates.
    return name.lower().startswith(AGENT_BRANCH_PREFIX)


def parse_raw_diff(raw: str) -> list[Change]:
    """Parse ``git diff --raw -z --no-renames`` output."""
    tokens = raw.split("\0")
    changes: list[Change] = []
    i = 0
    while i < len(tokens) and tokens[i]:
        meta = tokens[i].lstrip(":").split(" ")
        old_mode, new_mode, status = meta[0], meta[1], meta[4]
        changes.append(Change(status[0], old_mode, new_mode, tokens[i + 1]))
        i += 2
    return changes


def tree_changes(repo: Path, old: str, new: str) -> list[Change]:
    raw = git(repo, "diff", "--raw", "-z", "--no-renames", "--no-abbrev", old, new)
    return parse_raw_diff(raw)


def commit_changes(repo: Path, sha: str) -> list[Change]:
    raw = git(
        repo,
        *("diff-tree", "-r", "--raw", "-z", "--no-renames", "--no-abbrev"),
        *("--root", "--no-commit-id", sha),
    )
    return parse_raw_diff(raw)


def emit(result: GateResult, out: TextIO) -> int:
    out.write(result.render())
    return EXIT_PASS if result.passed else EXIT_FAIL
