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
_EXPORT_LIST_FULL = re.compile(r"\b(export\s+(?:type\s+)?)\{([^}]*)\}")
_DECLARED_TYPE = re.compile(r"\bexport\s+(?:declare\s+)?(?:type|interface)\s+([A-Za-z_$][\w$]*)")
_BRANDED = re.compile(r"\bexport\s+type\s+([A-Za-z_$][\w$]*)\s*=\s*(string|number)\s*&\s*\{[^}]*__brand")
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


def module_files(path: str, read: Reader, known: set[str] | None = None, depth: int = 3) -> list[str] | None:
    """The module and every module it re-exports with `export * from`; None if one cannot be read."""
    text = read(path)
    if text is None:
        return None
    files = [path]
    for spec in _EXPORT_STAR.findall(_COMMENTS.sub("", text)):
        if depth <= 0:
            return None
        target = None
        for candidate in _candidates(path, spec):
            if (known is not None and candidate in known) or (known is None and read(candidate) is not None):
                target = candidate
                break
        inner = module_files(target, read, known, depth - 1) if target else None
        if inner is None:
            return None
        files += [f for f in inner if f not in files]
    return files


def _declared(text: str) -> tuple[set[str], set[str]]:
    """(every exported name, the names that are types only) declared in one module's text."""
    names = set(_DECLARED.findall(text)) | set(_EXPORT_STAR_AS.findall(text))
    types = set(_DECLARED_TYPE.findall(text))
    for whole, group in _EXPORT_LIST_FULL.findall(text):
        for item in group.split(","):
            item = item.strip()
            is_type = whole.startswith("export type") or item.startswith("type ")
            item = item.removeprefix("type ").strip()
            if item:
                name = item.split(" as ")[-1].strip()
                names.add(name)
                if is_type:
                    types.add(name)
    if _EXPORT_DEFAULT.search(text):
        names.add("default")
    return names, types


def exports_with_types(path: str, read: Reader, known: set[str] | None = None) -> tuple[set[str], set[str]] | None:
    files = module_files(path, read, known)
    if files is None:
        return None
    names: set[str] = set()
    types: set[str] = set()
    for file in files:
        file_names, file_types = _declared(_COMMENTS.sub("", read(file) or ""))
        names |= file_names
        types |= file_types
    return names, types


def exports_of(path: str, read: Reader, known: set[str] | None = None) -> set[str] | None:
    """Names a module exports (following `export * from`), or None when the module cannot be read."""
    found = exports_with_types(path, read, known)
    return found[0] if found else None


def branded(path: str, read: Reader, known: set[str] | None = None) -> tuple[dict[str, str], dict[str, str]]:
    """({branded type: its base type}, {field name: branded type}) declared in a module and its re-exports.
    A branded type is `export type X = string & { readonly __brand: ... }` (nominal: a plain string
    literal is not assignable to it)."""
    types: dict[str, str] = {}
    texts = [_COMMENTS.sub("", read(f) or "") for f in module_files(path, read, known) or []]
    for text in texts:
        types.update(dict(_BRANDED.findall(text)))
    fields: dict[str, str] = {}
    if types:
        field_re = re.compile(rf"\b([A-Za-z_$][\w$]*)\??\s*:\s*({'|'.join(map(re.escape, types))})\b")
        for text in texts:
            fields.update(dict(field_re.findall(text)))
    return types, fields


def _named_imports(clause: str) -> list[tuple[str, bool]]:
    """(name, imported as a type) for each name an import clause needs: 'default' for a default
    import, the original name of each named import; nothing for a namespace import."""
    clause = clause.strip()
    all_types = clause.startswith("type ")
    clause = clause.removeprefix("type ").strip()
    names: list[tuple[str, bool]] = []
    named = re.search(r"\{([^}]*)\}", clause)
    head = clause[: named.start()] if named else clause
    head = head.strip().rstrip(",").strip()
    if head and not head.startswith("*"):
        names.append(("default", all_types))
    if named:
        for item in named.group(1).split(","):
            item = item.strip()
            is_type = all_types or item.startswith("type ")
            item = item.removeprefix("type ").strip()
            if item:
                names.append((item.split(" as ")[0].strip(), is_type))
    return names


def _imported_names(clause: str) -> list[str]:
    return [name for name, _ in _named_imports(clause)]


def _import_problems(path: str, clause: str, label: str, found: tuple[set[str], set[str]] | None) -> list[str]:
    if found is None:
        return []
    names, types = found
    errors = []
    for name, as_type in _named_imports(clause):
        if name not in names:
            errors.append(f"{path}: {name} is not exported by {label}")
        elif name in types and not as_type:
            errors.append(f"{path}: {name} is a type: import it with `import type` (verbatimModuleSyntax)")
    return errors


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
            if _imported_names(clause):
                errors += _import_problems(path, clause, target, exports_with_types(target, read, known))
            continue
        package = _package(spec)
        if package not in ALLOWED_PACKAGES and not spec.startswith(ALLOWED_SCOPES):
            errors.append(f"{path}: {package} is not an allowed package (vitest, @testing-library/*, "
                          "@parcel/core, react, react-dom)")
            continue
        if package == "vitest":
            vitest_names |= set(_imported_names(clause))
        elif spec in PACKAGE_ENTRIES:
            errors += _import_problems(path, clause, spec, exports_with_types(PACKAGE_ENTRIES[spec], read, known))
    for name in VITEST_NAMES:
        if name not in vitest_names and _uses(code, name):
            errors.append(f"{path}: uses {name} without importing it from vitest")
    errors += _branded_literals(path, code, known, read)
    return errors


def _branded_literals(path: str, code: str, known: set[str], read: Reader) -> list[str]:
    """A string literal written straight into a field typed with a branded type fails tsc; the cheap
    case (`trackingNumber: "PK..."` with no `as` cast) is caught here."""
    errors = []
    for entry in PACKAGE_ENTRIES.values():
        if entry not in known:
            continue
        _, fields = branded(entry, read, known)
        for field, brand in sorted(fields.items()):
            for match in re.finditer(rf"\b{re.escape(field)}\s*:\s*([\"'`])[^\"'`]*\1(?!\s*as\b)", code):
                errors.append(f"{path}: {field} is a {brand}: write {match.group(0).split(':', 1)[1].strip()} "
                              f"as {brand} (import type {{ {brand} }} from \"@parcel/core\")")
                break
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
