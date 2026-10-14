#!/usr/bin/env python3
"""Lint script to verify po/ROADMAP.md structure, integrity, and constraints:
1. IDs are unique and formatted cleanly (e.g. ITEM-XXX).
2. All dependencies exist and form a directed acyclic graph (no cycles).
3. Every item defines testable acceptance criteria (no TBD, minimum 3 words).
4. Files touched contain strictly paths within app/, every line backtick-enclosed, rejecting '..' traversal.
5. Cost Class is strictly 'S' or 'M'.
6. No Unicode em-dashes (\u2014) or en-dashes (\u2013).
7. No forbidden self-referential terms.

Usage: scripts/po/lint_roadmap.sh [path_to_roadmap_md]
"""

import os
import re
import sys
from collections import defaultdict
from pathlib import PurePosixPath

def main() -> int:
    roadmap_file = sys.argv[1] if len(sys.argv) > 1 else "po/ROADMAP.md"

    if not os.path.isfile(roadmap_file):
        print(f"FAIL: Roadmap file not found: {roadmap_file}", file=sys.stderr)
        return 1

    print(f"Linting {roadmap_file} for autonomous SDLC constraints...")

    with open(roadmap_file, "r", encoding="utf-8") as f:
        content = f.read()

    failures = 0

    def fail(msg: str) -> None:
        nonlocal failures
        print(f"  FAIL: {msg}", file=sys.stderr)
        failures += 1

    def ok(msg: str) -> None:
        print(f"  OK: {msg}")

    # Check 1: No Unicode em-dashes or en-dashes
    if "\u2014" in content or "\u2013" in content:
        fail(f"Found Unicode em-dash or en-dash in {roadmap_file}")
    else:
        ok("No em-dashes or en-dashes")

    # Check 2: No forbidden self-referential terms
    ai_pattern = re.compile(r"\b(as an A[I]|artificial intelligenc[e]|\bLL[M]\b)\b", re.IGNORECASE)
    if ai_pattern.search(content):
        fail(f"Found forbidden self-referential terms in {roadmap_file}")
    else:
        ok("No forbidden mentions")

    # Split into items
    item_blocks = re.split(r"(?=^###\s+ITEM-\d+:)", content, flags=re.MULTILINE)
    items: dict[str, dict] = {}

    for block in item_blocks:
        block = block.strip()
        if not block.startswith("### ITEM-"):
            continue

        lines = block.splitlines()
        header_match = re.match(r"^###\s+(ITEM-\d+):\s+(.+)$", lines[0])
        if not header_match:
            fail(f"Malformed item header: {lines[0]}")
            continue

        item_id = header_match.group(1).strip()
        title = header_match.group(2).strip()

        if item_id in items:
            fail(f"Duplicate item ID detected: {item_id}")

        # Cost Class check: strictly S or M
        cost_m = re.search(r"^-\s+\*\*Cost Class\*\*:\s*([^\n]+)$", block, re.MULTILINE)
        if not cost_m:
            fail(f"{item_id}: Missing - **Cost Class** line")
        else:
            cost_val = cost_m.group(1).strip()
            if cost_val not in ("S", "M"):
                fail(f"{item_id}: Invalid Cost Class '{cost_val}'. Must be strictly 'S' or 'M'")

        # Status check
        status_m = re.search(r"^-\s+\*\*Status\*\*:\s*(\w+)", block, re.MULTILINE)
        if not status_m or status_m.group(1).lower() not in ("todo", "filed", "done"):
            fail(f"{item_id}: Status must be one of todo, filed, done")

        # Dependencies
        dep_m = re.search(r"^-\s+\*\*Dependencies\*\*:\s*\[(.*?)\]", block, re.MULTILINE)
        deps = []
        if not dep_m:
            fail(f"{item_id}: Missing - **Dependencies** line")
        else:
            raw_deps = dep_m.group(1).strip()
            if raw_deps:
                deps = [d.strip() for d in raw_deps.split(",") if d.strip()]

        # Files Touched: every line must be backtick-enclosed and within app/
        files_match = re.search(r"^-\s+\*\*Files Touched\*\*:\s*\n((?:[ \t]+-[^\n]+\n?)+)", block, re.MULTILINE)
        files = []
        if not files_match:
            fail(f"{item_id}: Missing or malformed - **Files Touched** list")
        else:
            for raw_line in files_match.group(1).splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                if not (line.startswith("- `") and line.endswith("`")):
                    fail(f"{item_id}: Files Touched entry '{line}' must be enclosed in backticks, e.g. - `app/...`")
                    continue
                path_str = line[3:-1].strip()
                pure_path = PurePosixPath(path_str)
                if ".." in pure_path.parts:
                    fail(f"{item_id}: Path traversal forbidden: '{path_str}' contains '..'")
                    continue
                if not pure_path.parts or pure_path.parts[0] != "app":
                    fail(f"{item_id}: Scope violation: '{path_str}' is outside app/")
                    continue
                files.append(path_str)

        # Acceptance Criteria: no TBD, at least 3 words
        ac_match = re.search(r"^-\s+\*\*Acceptance Criteria\*\*:\s*\n((?:[ \t]+\d+\.[^\n]+\n?)+)", block, re.MULTILINE)
        if not ac_match:
            fail(f"{item_id}: Missing or malformed - **Acceptance Criteria** list")
        else:
            for raw_line in ac_match.group(1).splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                item_m = re.match(r"^\d+\.\s+(.+)$", line)
                if not item_m:
                    continue
                text = item_m.group(1).strip()
                if text.upper() == "TBD":
                    fail(f"{item_id}: Acceptance criterion cannot be TBD: '{line}'")
                elif len(text.split()) < 3:
                    fail(f"{item_id}: Acceptance criterion too short (under 3 words): '{line}'")

        items[item_id] = {
            "title": title,
            "deps": deps,
            "files": files,
        }

    # Verify item count
    if len(items) < 12 and (roadmap_file.endswith("po/ROADMAP.md") or roadmap_file.endswith("ROADMAP.md")):
        fail(f"Expected at least 12 roadmap items, but parsed {len(items)}")
    elif len(items) < 1:
        fail("Roadmap must contain at least 1 item")
    else:
        ok(f"Parsed {len(items)} roadmap items with unique IDs")

    # Check dependencies exist
    for item_id, data in items.items():
        for dep in data["deps"]:
            if dep not in items:
                fail(f"{item_id} depends on non-existent item {dep}")

    # Cycle detection via topological sort
    adj: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {i: 0 for i in items}
    for item_id, data in items.items():
        for dep in data["deps"]:
            if dep in items:
                adj[dep].append(item_id)
                in_degree[item_id] += 1

    queue = [i for i, deg in in_degree.items() if deg == 0]
    visited_count = 0
    while queue:
        curr = queue.pop(0)
        visited_count += 1
        for neighbor in adj[curr]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited_count != len(items):
        fail(f"Cycle detected in roadmap dependencies! Visited {visited_count} of {len(items)} items.")
    else:
        ok("Dependency graph is verified directed acyclic graph (no cycles)")

    if failures > 0:
        print(f"Roadmap lint failed with {failures} error(s).", file=sys.stderr)
        return 1

    print("PASS: Roadmap file satisfies all integrity and scope constraints.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
