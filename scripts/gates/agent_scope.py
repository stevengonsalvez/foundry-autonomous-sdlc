"""agent-scope gate: an `agent/*` branch may only change files under `app/`.

Every path touched between the merge base and the head counts, including
deletions, renames (both the old and the new path), mode changes and symlinks.
Files under `app/` that define the test and build rules (package.json, test runner,
coverage and compiler configuration) are protected and may not change either.

    python -m scripts.gates.agent_scope --base origin/main --head HEAD --branch agent/issue-12
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .common import (
    EXIT_ERROR,
    Change,
    GateError,
    GateResult,
    emit,
    glob_to_regex,
    is_agent_branch,
    merge_base,
    resolve_commit,
    tree_changes,
)

ALLOWED_PREFIX = "app/"

# Files that define what "green" means. Changing them is a human decision, not an agent edit:
# an agent that may edit the test script, coverage config or compiler flags can pass any gate.
PROTECTED_GLOBS = (
    "app/**/package.json",
    "app/package-lock.json",
    "app/**/vitest.config.*",
    "app/**/vite.config.*",
    "app/**/playwright.config.*",
    # The deploy smoke gate: its specs and any Playwright config of its own.
    "app/**/playwright.*.config.*",
    "app/e2e/smoke/**",
    "app/eslint.config.*",
    "app/**/tsconfig*.json",
    "app/coverage/**",
)
_PROTECTED = tuple(glob_to_regex(g) for g in PROTECTED_GLOBS)


def violation(change: Change) -> str | None:
    """Why this change is out of scope, or None when it is allowed."""
    path = change.path
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return "path traversal"
    if "\\" in path:
        return "backslash in path"
    # Exact, case-sensitive prefix: `App/x` or `APP/x` are different directories on Linux.
    if not path.startswith(ALLOWED_PREFIX):
        return "outside app/"
    if any(part.lower() == ".git" for part in parts):
        return "git metadata path"
    if change.is_link:
        return "symlink or submodule"
    if any(pattern.fullmatch(path) for pattern in _PROTECTED):
        return "protected test or build configuration"
    return None


def evaluate(repo: Path, base: str, head: str, branch: str) -> GateResult:
    if not is_agent_branch(branch):
        return GateResult(True, "not-agent-branch", [f"branch {branch!r} is not agent/*"])

    base_sha = resolve_commit(repo, base)
    head_sha = resolve_commit(repo, head)
    fork_point = merge_base(repo, base_sha, head_sha)
    changes = tree_changes(repo, fork_point, head_sha)

    report = [
        f"branch      {branch}",
        f"merge base  {fork_point[:12]}",
        f"head        {head_sha[:12]}",
        f"changed     {len(changes)} path(s)",
    ]
    offenders = [(c, reason) for c in changes if (reason := violation(c))]
    if not offenders:
        return GateResult(True, "in-scope" if changes else "no-changes", report)

    report.append(f"out of scope ({len(offenders)}):")
    report.extend(f"  {c.path!r}: {reason} [{c.status}]" for c, reason in offenders)
    return GateResult(False, "out-of-scope", report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", required=True, help="base ref or sha, e.g. origin/main")
    parser.add_argument("--head", default="HEAD", help="head ref or sha (default HEAD)")
    parser.add_argument("--branch", required=True, help="PR head branch name")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository (default cwd)")
    args = parser.parse_args(argv)

    try:
        result = evaluate(args.repo, args.base, args.head, args.branch)
    except GateError as exc:
        result = GateResult(False, "error", [f"cannot evaluate: {exc}"])
        emit(result, sys.stdout)
        return EXIT_ERROR
    return emit(result, sys.stdout)


if __name__ == "__main__":
    sys.exit(main())
