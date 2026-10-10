"""
Checks on the test designer's files before the coder sees them, so an invalid red (a test that fails
on a missing import or an undefined global instead of on an assertion) is caught here and the
designer is asked again with the exact problems.

- Path: app/<workspace>/tests/**/*.test.ts(x): the only files vitest collects (vitest.config.ts
  include) and a test glob for the tdd-order gate.
- Globals: vitest globals are not enabled, so describe, it, test, expect, vi and the hooks must be
  imported from "vitest".
- Imports: relative specifiers must resolve to a file on main or to another designed file, and named
  imports must be exported there; bare specifiers are limited to the packages the tests may use, and
  names imported from @parcel/core must be exported by its index.

Lexical (regex) analysis of TypeScript: good enough for test files written to a template, and every
problem it reports is real. Stdlib only.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from pathlib import PurePosixPath

Reader = Callable[[str], str | None]

ALLOWED_PACKAGES = frozenset({"vitest", "@parcel/core", "react", "react-dom"})
ALLOWED_SCOPES = ("@testing-library/",)
PACKAGE_ENTRIES = {"@parcel/core": "app/core/src/index.ts"}
VITEST_NAMES = ("describe", "it", "test", "expect", "vi", "beforeEach", "afterEach", "beforeAll", "afterAll")
RESOLVE_SUFFIXES = ("", ".ts", ".tsx", ".js", "/index.ts", "/index.tsx")
_TEST_PATH = re.compile(r"^app/[A-Za-z0-9._-]+/tests/(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+\.test\.tsx?$")

_IMPORT_FROM = re.compile(r"""\bimport\s+(?!\()([\s\S]*?)\s+from\s*["']([^"']+)["']""")
_IMPORT_BARE = re.compile(r"""\bimport\s*["']([^"']+)["']""")
_IMPORT_DYNAMIC = re.compile(r"""\bimport\(\s*["']([^"']+)["']\s*\)""")
_DECLARED = re.compile(
    r"\bexport\s+(?:declare\s+)?(?:async\s+)?(?:function\*?|const|let|var|class|abstract\s+class|type|interface|enum)"
    r"\s+([A-Za-z_$][\w$]*)"
)
_EXPORT_LIST = re.compile(r"\bexport\s+(?:type\s+)?\{([^}]*)\}")
_EXPORT_STAR = re.compile(r"""\bexport\s*\*\s*from\s*["']([^"']+)["']""")
_EXPORT_STAR_AS = re.compile(r"""\bexport\s*\*\s*as\s+([A-Za-z_$][\w$]*)\s+from""")
_EXPORT_DEFAULT = re.compile(r"\bexport\s+default\b")
_COMMENTS = re.compile(r"/\*[\s\S]*?\*/|//[^\n]*")


def _package(spec: str) -> str:
    parts = spec.split("/")
    return "/".join(parts[:2]) if spec.startswith("@") else parts[0]


def _candidates(base: str, spec: str) -> list[str]:
    joined = PurePosixPath(base).parent / spec
    normal: list[str] = []
    for part in joined.parts:
        if part == "..":
            if normal:
                normal.pop()
        elif part != ".":
            normal.append(part)
    stem = "/".join(normal)
    return [stem + suffix for suffix in RESOLVE_SUFFIXES]


def _resolve(base: str, spec: str, known: set[str], read: Reader) -> str | None:
    for candidate in _candidates(base, spec):
        if candidate in known:
            return candidate
    return None


def exports_of(path: str, read: Reader, known: set[str] | None = None, depth: int = 3) -> set[str] | None:
    """Names a module exports (following `export * from`), or None when the module cannot be read."""
    text = read(path)
    if text is None:
        return None
    text = _COMMENTS.sub("", text)
    names = set(_DECLARED.findall(text)) | set(_EXPORT_STAR_AS.findall(text))
    for group in _EXPORT_LIST.findall(text):
        for item in group.split(","):
            item = item.strip().removeprefix("type ").strip()
            if item:
                names.add(item.split(" as ")[-1].strip())
    if _EXPORT_DEFAULT.search(text):
        names.add("default")
    for spec in _EXPORT_STAR.findall(text):
        if depth <= 0:
            return None
        target = None
        for candidate in _candidates(path, spec):
            if (known is not None and candidate in known) or (known is None and read(candidate) is not None):
                target = candidate
                break
        inner = exports_of(target, read, known, depth - 1) if target else None
        if inner is None:
            return None
        names |= inner
    return names


def _imported_names(clause: str) -> list[str]:
    """Names an import clause needs from the module: 'default' for a default import, the original
    name of each named import; nothing for a namespace import."""
    clause = clause.strip().removeprefix("type ").strip()
    names: list[str] = []
    named = re.search(r"\{([^}]*)\}", clause)
    head = clause[: named.start()] if named else clause
    head = head.strip().rstrip(",").strip()
    if head and not head.startswith("*"):
        names.append("default")
    if named:
        for item in named.group(1).split(","):
            item = item.strip().removeprefix("type ").strip()
            if item:
                names.append(item.split(" as ")[0].strip())
    return names


def _check_file(path: str, content: str, known: set[str], read: Reader) -> list[str]:
    errors: list[str] = []
    if not _TEST_PATH.match(path):
        errors.append(f"{path}: must be app/<workspace>/tests/**/*.test.ts(x)")
        return errors
    code = _COMMENTS.sub("", content)
    vitest_names: set[str] = set()
    imports = [(clause, spec) for clause, spec in _IMPORT_FROM.findall(code)]
    imports += [("", spec) for spec in _IMPORT_BARE.findall(code)]
    imports += [("", spec) for spec in _IMPORT_DYNAMIC.findall(code)]
    for clause, spec in imports:
        if spec.startswith("."):
            target = _resolve(path, spec, known, read)
            if target is None:
                errors.append(f"{path}: import {spec} does not resolve to a file on main or a designed file")
                continue
            wanted = _imported_names(clause)
            exported = exports_of(target, read, known) if wanted else set()
            if exported is not None:
                errors += [f"{path}: {name} is not exported by {target}" for name in wanted if name not in exported]
            continue
        package = _package(spec)
        if package not in ALLOWED_PACKAGES and not spec.startswith(ALLOWED_SCOPES):
            errors.append(f"{path}: {package} is not an allowed package (vitest, @testing-library/*, "
                          "@parcel/core, react, react-dom)")
            continue
        if package == "vitest":
            vitest_names |= set(_imported_names(clause))
        elif spec in PACKAGE_ENTRIES:
            exported = exports_of(PACKAGE_ENTRIES[spec], read, known)
            if exported is not None:
                errors += [f"{path}: {name} is not exported by {spec}"
                           for name in _imported_names(clause) if name not in exported]
    for name in VITEST_NAMES:
        if name not in vitest_names and _uses(code, name):
            errors.append(f"{path}: uses {name} without importing it from vitest")
    return errors


def _uses(code: str, name: str) -> bool:
    """A call or member access on `name` that is not a property (`x.it`) or an object key (`{ it() {} }`)."""
    for match in re.finditer(rf"(?<![\w$.]){name}\s*[(.]", code):
        before = code[: match.start()].rstrip()
        method = re.match(rf"{name}\s*\([^()]*\)\s*\{{", code[match.start():])
        if not (method and before.endswith(("{", ","))):
            return True
    return False


def lint(tests: Iterable[dict[str, str]], repo_paths: set[str], read: Reader) -> list[str]:
    """Every problem in the designed test files; [] when they are fit to hand to the coder."""
    tests = list(tests)
    designed = {t["path"]: t["content"] for t in tests}
    known = set(repo_paths) | set(designed)

    def read_any(path: str) -> str | None:
        return designed[path] if path in designed else read(path)

    errors: list[str] = []
    for test in tests:
        errors += _check_file(test["path"], test["content"], known, read_any)
    return errors
