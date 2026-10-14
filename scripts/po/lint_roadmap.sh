#!/usr/bin/env python3
# Note: This file retains the .sh extension for compatibility with existing workflow callers
# (.github/workflows/ci.yml), but is executed directly with python3 via the shebang line above.
"""Lint script to verify that po/ROADMAP.md adheres to autonomous SDLC constraints.

Validates:
1. No Unicode em-dashes (\\u2014) or en-dashes (\\u2013).
2. No forbidden self-referential terms.
3. Every header starting with '### ITEM' strictly matches: ^### (ITEM-\\d+): (.+)$
4. Item block fields strictly conform to expected fields:
   - **Status**: todo|filed|done
   - **Dependencies**: [<deps>]
   - **Cost Class**: S|M
   - **Tags**: ...
   - **Gap Anchor**: ...
   - **User Value**: ...
   - **Files Touched**:
     - `app/...` (strictly one backtick pair per line, no '..' traversal, must begin with app/)
   - **Acceptance Criteria**:
     1. ... (at least 3 words, no \\bTBD\\b anywhere)
   No invalid non-field lines allowed inside item blocks.
5. Unique item IDs.
6. Acyclic dependency graph (all dependencies exist and no cycles).
7. At least 12 valid items.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import PurePosixPath

ALLOWED_FIELDS = {
    "Status",
    "Dependencies",
    "Cost Class",
    "Tags",
    "Gap Anchor",
    "User Value",
    "Files Touched",
    "Acceptance Criteria",
}


def lint_roadmap(roadmap_file: str) -> int:
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

    # Check 2b: No forbidden verbs or spend wording across the whole file (including preamble, titles, comments)
    forbidden_patterns = [
        (r"\bgh\s+pr\s+merge\b", "Forbidden command 'gh pr merge'"),
        (r"--admin\b", "Forbidden flag '--admin'"),
        (r"\bpush\s+to\s+main\b", "Forbidden action 'push to main'"),
        (r"\bgit\s+push\b", "Forbidden command 'git push'"),
        (r"\b(raise|increase)\s+(the\s+)?(cap|budget)\b", "Forbidden spend action 'raise/increase the cap or budget'"),
        (r"\bmerge\b", "Forbidden verb/term 'merge'"),
    ]
    for pattern, desc in forbidden_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            fail(f"Found forbidden wording in {roadmap_file}: {desc}")

    # Check 3: Strict header regex on all lines starting with # and containing ITEM-
    for line_idx, line in enumerate(content.splitlines(), 1):
        if re.search(r"^\s*#+\s*ITEM-", line):
            if not re.match(r"^###\s+ITEM-\d+:\s+.+$", line):
                fail(f"Line {line_idx}: Invalid ITEM header '{line}'. Header must match '### ITEM-0NN: Title' with a colon")

    # Split into item blocks
    item_blocks = re.split(r"(?=^###\s+ITEM-\d+:)", content, flags=re.MULTILINE)
    items: dict[str, dict] = {}

    for block in item_blocks:
        block = block.strip()
        if not re.match(r"^###\s+ITEM-\d+:", block):
            continue

        lines = block.splitlines()
        header_match = re.match(r"^###\s+(ITEM-\d+):\s+(.+)$", lines[0])
        if not header_match:
            continue

        item_id = header_match.group(1).strip()
        title = header_match.group(2).strip()

        if item_id in items:
            fail(f"Duplicate item ID detected: {item_id}")

        fields_seen: list[str] = []
        status_count = 0
        current_field: str | None = None
        status_val: str = ""
        cost_val: str = ""
        deps: list[str] = []
        files: list[str] = []
        ac_items: list[str] = []

        for line_num_in_block, raw_line in enumerate(lines[1:], 2):
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped == "---":
                current_field = None
                continue

            field_m = re.match(r"^-\s+\*\*([A-Za-z ]+)\*\*:(.*)$", stripped)
            if field_m:
                field_name = field_m.group(1).strip()
                field_value = field_m.group(2).strip()
                if field_name not in ALLOWED_FIELDS:
                    fail(f"{item_id}: Unknown field '- **{field_name}**:'")
                fields_seen.append(field_name)
                current_field = field_name

                if field_name == "Status":
                    status_count += 1
                    status_val = field_value.lower()
                    if status_count > 1:
                        fail(f"{item_id}: Duplicate '- **Status**:' line detected; exactly one Status field allowed per item")
                elif field_name in ("Files Touched", "Acceptance Criteria"):
                    if field_value:
                        fail(f"{item_id}: Inline value forbidden on '- **{field_name}**: {field_value}'. Items must be listed on indented child lines.")
                    continue
                elif field_name == "Cost Class":
                    cost_val = field_value
                elif field_name == "Dependencies":
                    dep_m = re.match(r"^\[(.*?)\]$", field_value)
                    if dep_m:
                        raw_deps = dep_m.group(1).strip()
                        deps = [d.strip() for d in raw_deps.split(",") if d.strip()]
                    else:
                        fail(f"{item_id}: Malformed Dependencies field '{field_value}'. Expected '[...]'")
                continue

            # Child lines under current field
            if current_field == "Files Touched":
                file_m = re.match(r"^-\s+`([^`]+)`$", stripped)
                if not file_m:
                    fail(f"{item_id}: Files Touched entry '{stripped}' must match '  - `app/...`' with exactly one backtick pair")
                else:
                    path_str = file_m.group(1).strip()
                    pure_path = PurePosixPath(path_str)
                    if ".." in pure_path.parts:
                        fail(f"{item_id}: Path traversal forbidden: '{path_str}' contains '..'")
                    elif not pure_path.parts or pure_path.parts[0] != "app":
                        fail(f"{item_id}: Scope violation: '{path_str}' is outside app/")
                    else:
                        files.append(path_str)
            elif current_field == "Acceptance Criteria":
                ac_m = re.match(r"^\d+\.\s+(.+)$", stripped)
                if not ac_m:
                    fail(f"{item_id}: Acceptance criterion entry '{stripped}' must match '  1. ...'")
                else:
                    text = ac_m.group(1).strip()
                    if re.search(r"\bTBD\b", text, re.IGNORECASE):
                        fail(f"{item_id}: Acceptance criterion cannot contain TBD: '{stripped}'")
                    if len(text.split()) < 3:
                        fail(f"{item_id}: Acceptance criterion too short (under 3 words): '{stripped}'")
                    ac_items.append(text)
            else:
                fail(f"{item_id}: Invalid non-field line inside item block: '{stripped}'")

        # Validate exact fixed field order
        ORDERED_FIELDS = [
            "Status",
            "Dependencies",
            "Cost Class",
            "Tags",
            "Gap Anchor",
            "User Value",
            "Files Touched",
            "Acceptance Criteria",
        ]
        if fields_seen != ORDERED_FIELDS:
            fail(f"{item_id}: Fields must appear in exact fixed order {ORDERED_FIELDS}. Found: {fields_seen}")

        if status_count != 1:
            fail(f"{item_id}: Exactly one Status field required per item. Found: {status_count}")

        # Validate status
        if status_val not in ("todo", "filed", "done"):
            fail(f"{item_id}: Invalid status '{status_val}'. Must be todo, filed, or done")

        # Validate cost class
        if cost_val not in ("S", "M"):
            fail(f"{item_id}: Invalid Cost Class '{cost_val}'. Must be strictly 'S' or 'M'")

        # Validate files count
        if not files:
            fail(f"{item_id}: No valid files listed under Files Touched")

        # Validate acceptance criteria count
        if not ac_items:
            fail(f"{item_id}: No valid acceptance criteria listed")

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

    # Check for cycles using DFS
    visited: set[str] = set()
    rec_stack: set[str] = set()

    def check_cycle(node: str, path: list[str]) -> bool:
        visited.add(node)
        rec_stack.add(node)
        for neighbor in items.get(node, {}).get("deps", []):
            if neighbor not in items:
                continue
            if neighbor not in visited:
                if check_cycle(neighbor, path + [neighbor]):
                    return True
            elif neighbor in rec_stack:
                cycle_str = " -> ".join(path + [neighbor])
                fail(f"Circular dependency detected: {cycle_str}")
                return True
        rec_stack.remove(node)
        return False

    has_cycle = False
    for node in items:
        if node not in visited:
            if check_cycle(node, [node]):
                has_cycle = True
                break

    if not has_cycle and items:
        ok("Dependency graph is verified directed acyclic graph (no cycles)")

    if failures > 0:
        print(f"FAIL: Roadmap file failed {failures} constraint check(s)", file=sys.stderr)
        return 1

    print("PASS: Roadmap file satisfies all integrity and scope constraints.")
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "po/ROADMAP.md"
    sys.exit(lint_roadmap(target))
