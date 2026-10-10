"""
Repository context the orchestrator hands the test designer, so the model rarely needs a tool call
(each MCP round trip re-sends its output and costs time and rate-limit headroom) and writes tests
that import what really exists.

One tree listing gives every path under app/. Simple rules then pick:
- up to MAX_SOURCES source files whose path, then text, shares words with the issue;
- the template: the existing test in that workspace's tests/ folder that best matches the issue,
  given in full as the style to copy;
- the workspace's tests/helpers module, and the exported names of it and of @parcel/core.
The text is capped at about MAX_CONTEXT_CHARS, template first. Everything returned is untrusted data
and is wrapped as such by the caller. Stdlib only.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from sdlc_agents.designed_tests import PACKAGE_ENTRIES, branded, exports_of
from sdlc_agents.paths import is_test_path

MAX_CONTEXT_CHARS = 12_000
MAX_LISTED = 400
MAX_SOURCES = 3
MAX_READS = 6
LISTED_SUFFIXES = (".ts", ".tsx", ".json", ".yaml", ".yml", ".md", ".css")
CODE_SUFFIXES = (".ts", ".tsx")
HELPER_NAMES = ("helpers.tsx", "helpers.ts")
DEFAULT_WORKSPACE = "app/web"
SKIP_SEGMENTS = frozenset({"node_modules", "dist", "dist-pages", "build", "coverage", "playwright-report",
                           "test-results"})
SKIP_NAMES = frozenset({"package-lock.json"})
STOPWORDS = frozenset({
    "that", "this", "with", "from", "have", "should", "would", "when", "what", "which", "their", "there",
    "they", "them", "then", "than", "into", "only", "also", "show", "shows", "shown", "must", "will",
    "does", "even", "same", "such", "some", "more", "many", "most", "very", "just", "each", "every",
    "about", "after", "before", "while", "where", "like", "make", "made", "need", "needs", "want",
    "user", "users", "people", "summary", "acceptance", "criteria", "scenario", "story", "context",
})

Reader = Callable[[str], str | None]


@dataclass(frozen=True)
class Selection:
    sources: list[str] = field(default_factory=list)
    template: str | None = None       # an existing test to copy the style of
    helpers: str | None = None        # the workspace's tests/helpers module


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 4 and word.endswith("s") else word


def terms(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z][a-z0-9]{3,}", text.lower()) if w not in STOPWORDS}


def listable(paths: list[str]) -> list[str]:
    """Paths under app/ worth showing: sources, tests, configs; no dependencies or build output."""
    keep = []
    for path in paths:
        parts = PurePosixPath(path).parts
        if not path.startswith("app/") or SKIP_SEGMENTS.intersection(parts) or parts[-1] in SKIP_NAMES:
            continue
        if path.endswith(LISTED_SUFFIXES):
            keep.append(path)
    return sorted(keep)


def _path_score(path: str, words: set[str]) -> int:
    flat = re.sub(r"[^a-z0-9]", "", path.lower())
    return sum(word in flat for word in words)


def _workspace(path: str) -> str:
    return "/".join(PurePosixPath(path).parts[:2])


def select(paths: list[str], issue_text: str, read: Reader, cache: dict[str, str] | None = None) -> Selection:
    cache = {} if cache is None else cache
    words = terms(issue_text)
    listed = listable(paths)
    code = [p for p in listed if p.endswith(CODE_SUFFIXES)]
    sources = [p for p in code if not is_test_path(p)]
    shortlist = sorted(sources, key=lambda p: (-_path_score(p, words), len(p), p))[:MAX_READS]
    scored = []
    for path in shortlist:
        text = cache.setdefault(path, read(path) or "")
        score = 3 * _path_score(path, words) + sum(word in text.lower() for word in words)
        if score:
            scored.append((-score, len(path), path))
    chosen = [path for _, _, path in sorted(scored)[:MAX_SOURCES]]
    workspace = _workspace(chosen[0]) if chosen else DEFAULT_WORKSPACE
    folder = f"{workspace}/tests/"
    tests = [p for p in code if p.startswith(folder) and p.endswith((".test.ts", ".test.tsx"))]
    template = min(tests, key=lambda p: (-_path_score(p, words), len(p), p)) if tests else None
    helpers = next((folder + name for name in HELPER_NAMES if folder + name in listed), None)
    return Selection(chosen, template, helpers)


def _exports_line(label: str, path: str, read: Reader, known: set[str]) -> str | None:
    names = exports_of(path, read, known)
    if not names:
        return None
    return f"Exports of {label}: " + ", ".join(sorted(n for n in names if n != "default"))


# A valid value per branded type the designer is likely to need; any other brand gets a placeholder.
BRAND_EXAMPLES = {"TrackingNumber": '"PK1000000001"'}   # app/core/src/tracking-number.ts: /^PK\d{10}$/


def _branded_line(label: str, path: str, read: Reader, known: set[str]) -> str | None:
    """How to build each branded (nominal) type: a plain literal does not type-check."""
    types, _ = branded(path, read, known)
    if not types:
        return None
    return f"Branded types in {label}: " + "; ".join(
        f"{name} ({base}): write {BRAND_EXAMPLES.get(name, '1' if base == 'number' else '"..."')} as {name}"
        for name, base in sorted(types.items()))


def build(paths: list[str], issue_text: str, read: Reader) -> tuple[str, str]:
    """(file listing, context text) for the test designer; ("", "") for an empty repository."""
    listed = listable(paths)
    if not listed:
        return "", ""
    listing = "\n".join(listed[:MAX_LISTED])
    if len(listed) > MAX_LISTED:
        listing += f"\n[{len(listed) - MAX_LISTED} more paths not listed]"
    cache: dict[str, str] = {}

    def cached(path: str) -> str | None:
        if path not in cache:
            text = read(path)
            if text is None:
                return None
            cache[path] = text
        return cache[path]

    chosen = select(paths, issue_text, cached, cache)
    known = set(paths)
    header = []
    if chosen.helpers:
        name = PurePosixPath(chosen.helpers).stem
        header.append(_exports_line(f'{chosen.helpers} (import from "./{name}")', chosen.helpers, cached, known))
    for package, entry in PACKAGE_ENTRIES.items():
        if entry in known:
            header.append(_exports_line(package, entry, cached, known))
            header.append(_branded_line(package, entry, cached, known))
    blocks = [line for line in header if line]
    left = MAX_CONTEXT_CHARS
    files = [p for p in (chosen.template, chosen.helpers, *chosen.sources) if p]
    for path in dict.fromkeys(files):
        if left <= 0:
            break
        text = cached(path) or ""
        if len(text) > left:
            text = text[:left] + "\n[truncated]"
        blocks.append(f"=== FILE {path} ===\n{text}")
        left -= len(text)
    return listing, "\n\n".join(blocks)
