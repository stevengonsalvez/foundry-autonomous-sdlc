"""
Path policy for model-proposed files: everything agents may write lives under app/.

Test globs match docs/architecture.md (and scripts/gates): **/*.test.ts, **/*.test.tsx,
**/*.spec.ts, app/e2e/**, **/tests/**, **/__fixtures__/**. Stdlib only.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

APP_ROOT = "app/"
MAX_PATH_LENGTH = 255
VITEST_SUFFIXES = (".test.ts", ".test.tsx")

# Letters, digits, '.', '_', '-' and '/' only: no control chars, backslash or colon (Windows paths,
# NTFS streams), and nothing that can break out of a markdown code span or mention anyone.
_SAFE_CHARS = re.compile(r"^[A-Za-z0-9._/-]+$")


def is_test_path(path: str) -> bool:
    """True when the repo-relative path matches one of the architecture's test globs."""
    parts = PurePosixPath(path).parts
    if not parts:
        return False
    name, dirs = parts[-1], parts[:-1]
    return (
        name.endswith((".test.ts", ".test.tsx", ".spec.ts"))
        or path.startswith("app/e2e/")
        or "tests" in dirs
        or "__fixtures__" in dirs
    )


def normalise_app_path(path: object) -> str:
    """
    Return the normalised POSIX path if it is a safe file path under app/; raise ValueError otherwise.
    Lexical only: whoever writes the file adds containment checks against the checkout.
    """
    if not isinstance(path, str) or not path:
        raise ValueError(f"path rejected (empty or not a string): {path!r}")
    if len(path) > MAX_PATH_LENGTH:
        raise ValueError(f"path rejected (too long, max {MAX_PATH_LENGTH}): {path[:80]!r}")
    if not _SAFE_CHARS.match(path):
        raise ValueError(f"path rejected (only letters, digits, '.', '_', '-' and '/' are allowed): {path!r}")
    if path.endswith("/"):
        raise ValueError(f"path rejected (directory): {path!r}")
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"path rejected (absolute or '..'): {path!r}")
    for seg in p.parts:
        # casefold + strip trailing dots/spaces defeats ".GITHUB", ".git." and friends.
        if not seg.casefold().rstrip(". ") or seg.startswith(".") or seg == "node_modules":
            raise ValueError(f"path rejected (forbidden segment {seg!r}): {path!r}")
    norm = "/".join(p.parts)
    if not norm.startswith(APP_ROOT):
        raise ValueError(f"path rejected (outside {APP_ROOT}): {path!r}")
    return norm


def normalise_vitest_path(path: object) -> str:
    """A path the test designer may create: a vitest file under app/, outside the Playwright suite."""
    norm = normalise_app_path(path)
    if not norm.endswith(VITEST_SUFFIXES) or norm.startswith("app/e2e/"):
        raise ValueError(f"path rejected (not a vitest *.test.ts(x) file outside app/e2e): {norm!r}")
    return norm


def normalise_test_path(path: object) -> str:
    """A path a test-only repair may touch: any test-glob path under app/."""
    norm = normalise_app_path(path)
    if not is_test_path(norm):
        raise ValueError(f"path rejected (does not match a test glob): {norm!r}")
    return norm
