"""
Path rules for the coder: which files an engine may change.

Test globs match scripts/gates/tdd_order.py so the coder never produces a branch the
tdd-order gate would classify differently.
"""

from __future__ import annotations

import os
import posixpath
import re
import stat
from collections.abc import Iterable
from pathlib import Path

TEST_GLOBS = (
    "**/*.test.ts",
    "**/*.test.tsx",
    "**/*.spec.ts",
    "app/e2e/**",
    "**/tests/**",
    "**/__fixtures__/**",
)

# Test runner configuration decides which tests run and how; no engine may change it.
TEST_RUNNER_CONFIG_GLOBS = ("**/vitest.config.*", "**/vitest.workspace.*", "**/vitest.setup.*")

# Files that make git run or fetch things (filters, diff drivers, submodules): never engine-editable.
GIT_CONTROL_FILES = (".gitattributes", ".gitmodules")

# Suites vitest collects; other test-glob files (helpers, fixtures) need not appear in a report.
SUITE_SUFFIXES = (".test.ts", ".test.tsx", ".spec.ts")


def _glob_to_regex(glob: str) -> re.Pattern[str]:
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


_TEST_PATTERNS = tuple(_glob_to_regex(g) for g in TEST_GLOBS)
_RUNNER_CONFIG_PATTERNS = tuple(_glob_to_regex(g) for g in TEST_RUNNER_CONFIG_GLOBS)


def is_test_path(path: str) -> bool:
    return any(p.fullmatch(path) for p in _TEST_PATTERNS)


def is_test_runner_config(path: str) -> bool:
    return any(p.fullmatch(path) for p in _RUNNER_CONFIG_PATTERNS)


def is_suite_path(path: str) -> bool:
    return path.endswith(SUITE_SUFFIXES)


def is_safe_relative(path: str) -> bool:
    """A canonical repo-relative POSIX path: no absolute paths, no '..', no '.' segments, never inside .git."""
    if not path or path.startswith("/") or "\\" in path or "\x00" in path:
        return False
    if ".git" in path.split("/"):
        return False
    return posixpath.normpath(path) == path and not path.startswith("../") and path != ".."


def contained_path(root: Path, path: str) -> Path | None:
    """The absolute target for `path` under `root`, or None if it could escape.

    Checked before every read or write of an engine- or model-supplied path: the path must be
    safe and relative, and no existing component may be a symlink (a link could point anywhere,
    including into .git or out of the checkout). The resolved target must stay under `root`.
    """
    if not is_safe_relative(path):
        return None
    base = root.resolve()
    current = base
    for part in path.split("/"):
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            break   # the rest does not exist yet, so it cannot be a link
        if stat.S_ISLNK(mode):
            return None
    target = (base / path).resolve()
    return target if base in target.parents else None


def within_allowed(path: str, allowed_paths: Iterable[str]) -> bool:
    if not is_safe_relative(path):
        return False
    for allowed in allowed_paths:
        prefix = allowed.rstrip("/")
        if prefix in ("", ".") or path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def violations(changed: Iterable[str], *, allowed_paths: Iterable[str], protected: Iterable[str],
               tests_only: bool) -> list[str]:
    """Changed paths the engine was not allowed to touch, in input order."""
    allowed = tuple(allowed_paths)
    locked = set(protected)
    bad: list[str] = []
    for path in changed:
        if (not within_allowed(path, allowed) or path in locked or is_test_runner_config(path)
                or posixpath.basename(path) in GIT_CONTROL_FILES
                or (tests_only and not is_test_path(path))):
            bad.append(path)
    return bad
