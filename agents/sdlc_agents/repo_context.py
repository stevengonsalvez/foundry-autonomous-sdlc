"""
Repository context the orchestrator hands the test designer, so the model rarely needs a tool call
(each MCP round trip re-sends its output and costs time and rate-limit headroom).

One tree listing gives every path under app/; simple rules pick the 2 to 4 most relevant files:
source files whose path, then text, shares words with the issue, plus the nearest existing test as a
style example. The text is capped at MAX_CONTEXT_CHARS. Everything returned is untrusted data and is
wrapped as such by the caller. Stdlib only.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import PurePosixPath

from sdlc_agents.paths import is_test_path

MAX_CONTEXT_CHARS = 12_000
MAX_LISTED = 400
MAX_SOURCES = 3
MAX_READS = 6
LISTED_SUFFIXES = (".ts", ".tsx", ".json", ".yaml", ".yml", ".md", ".css")
CODE_SUFFIXES = (".ts", ".tsx")
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
    flat = path.lower()
    return sum(word in flat for word in words)


def _nearest_test(source: str, tests: list[str]) -> str | None:
    p = PurePosixPath(source)
    stem = p.name.split(".")[0]
    workspace = "/".join(p.parts[:2])
    same_stem = [t for t in tests if PurePosixPath(t).name.split(".")[0] == stem]
    same_dir = [t for t in tests if str(PurePosixPath(t).parent) == str(p.parent)]
    same_workspace = [t for t in tests if t.startswith(workspace + "/")]
    for group in (same_stem, same_dir, same_workspace):
        if group:
            return min(group, key=len)
    return None


def select(paths: list[str], issue_text: str, read: Reader, cache: dict[str, str] | None = None) -> list[str]:
    """Up to MAX_SOURCES relevant source files, then the nearest existing test as a style example."""
    cache = {} if cache is None else cache
    words = terms(issue_text)
    listed = listable(paths)
    code = [p for p in listed if p.endswith(CODE_SUFFIXES)]
    sources = [p for p in code if not is_test_path(p)]
    tests = [p for p in code if is_test_path(p) and not p.startswith("app/e2e/")]
    shortlist = sorted(sources, key=lambda p: (-_path_score(p, words), len(p), p))[:MAX_READS]
    scored = []
    for path in shortlist:
        text = cache.setdefault(path, read(path) or "")
        score = 3 * _path_score(path, words) + sum(word in text.lower() for word in words)
        if score:
            scored.append((-score, len(path), path))
    chosen = [path for _, _, path in sorted(scored)[:MAX_SOURCES]]
    if chosen and (test := _nearest_test(chosen[0], tests)):
        chosen.append(test)
    return chosen


def build(paths: list[str], issue_text: str, read: Reader) -> tuple[str, str]:
    """(file listing, selected file texts) for the test designer; ("", "") for an empty repository."""
    listed = listable(paths)
    if not listed:
        return "", ""
    listing = "\n".join(listed[:MAX_LISTED])
    if len(listed) > MAX_LISTED:
        listing += f"\n[{len(listed) - MAX_LISTED} more paths not listed]"
    cache: dict[str, str] = {}
    blocks: list[str] = []
    left = MAX_CONTEXT_CHARS
    for path in select(paths, issue_text, read, cache):
        if left <= 0:
            break
        text = cache.get(path)
        if text is None:
            text = read(path) or ""
        if len(text) > left:
            text = text[:left] + "\n[truncated]"
        blocks.append(f"=== FILE {path} ===\n{text}")
        left -= len(text)
    return listing, "\n\n".join(blocks)
