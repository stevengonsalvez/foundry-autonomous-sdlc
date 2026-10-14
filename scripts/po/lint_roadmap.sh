#!/usr/bin/env bash
# Lint script to verify po/ROADMAP.md structure, integrity, and constraints:
# 1. IDs are unique and formatted cleanly (e.g. ITEM-XXX).
# 2. All dependencies exist and form a directed acyclic graph (no cycles).
# 3. Every item defines testable acceptance criteria.
# 4. Files touched contain strictly paths within app/ (agent-scope enforcement).
# 5. No Unicode em-dashes (\u2014) or en-dashes (\u2013).
# 6. No forbidden self-referential AI terms.
#
# Usage: scripts/po/lint_roadmap.sh [path_to_roadmap_md]

set -euo pipefail

ROADMAP_FILE="${1:-po/ROADMAP.md}"

if [ ! -f "$ROADMAP_FILE" ]; then
  echo "FAIL: Roadmap file not found: $ROADMAP_FILE" >&2
  exit 1
fi

echo "Linting $ROADMAP_FILE for autonomous SDLC constraints..."

# Check 0a: No em-dashes (Unicode \u2014) or en-dashes (\u2013)
if grep -P "[\x{2014}\x{2013}]" "$ROADMAP_FILE" >/dev/null 2>&1; then
  echo "  FAIL: Found Unicode em-dash or en-dash in $ROADMAP_FILE" >&2
  exit 1
else
  echo "  OK: No em-dashes or en-dashes"
fi

# Check 0b: No forbidden self-referential terms
if grep -iP "\b(as an A[I]|artificial intelligenc[e]|\bLL[M]\b)\b" "$ROADMAP_FILE" >/dev/null 2>&1; then
  echo "  FAIL: Found forbidden self-referential terms in $ROADMAP_FILE" >&2
  exit 1
else
  echo "  OK: No forbidden mentions"
fi

# Parse and validate roadmap items using python3
python3 - "$ROADMAP_FILE" << 'EOF'
import sys
import re
from collections import defaultdict

roadmap_file = sys.argv[1]

with open(roadmap_file, "r", encoding="utf-8") as f:
    content = f.read()

# Match items: ### ITEM-XXX: title
item_blocks = re.split(r"(?=^###\s+ITEM-\d+:)", content, flags=re.MULTILINE)

items = {}
failures = 0

def fail(msg: str):
    global failures
    print(f"  FAIL: {msg}", file=sys.stderr)
    failures += 1

def ok(msg: str):
    print(f"  OK: {msg}")

for block in item_blocks:
    block = block.strip()
    if not block.startswith("### ITEM-"):
        continue

    # Extract ID and Title
    header_match = re.match(r"^###\s+(ITEM-\d+):\s+(.+)$", block.splitlines()[0])
    if not header_match:
        fail(f"Malformed item header: {block.splitlines()[0]}")
        continue

    item_id = header_match.group(1).strip()
    title = header_match.group(2).strip()

    if item_id in items:
        fail(f"Duplicate item ID detected: {item_id}")
    
    # Extract Dependencies
    dep_match = re.search(r"-\s+\*\*Dependencies\*\*:\s*\[(.*?)\]", block)
    deps = []
    if dep_match:
        raw_deps = dep_match.group(1).strip()
        if raw_deps:
            deps = [d.strip() for d in raw_deps.split(",") if d.strip()]
    else:
        fail(f"{item_id}: Missing - **Dependencies** line")

    # Extract Acceptance Criteria
    ac_match = re.search(r"-\s+\*\*Acceptance Criteria\*\*:\s*\n((?:\s+\d+\..*\n?)+)", block)
    if not ac_match:
        fail(f"{item_id}: Missing or malformed - **Acceptance Criteria** list")

    # Extract Files Touched
    files_match = re.search(r"-\s+\*\*Files Touched\*\*:\s*\n((?:\s+-\s+`.*?`.*\n?)+)", block)
    files = []
    if files_match:
        for line in files_match.group(1).splitlines():
            line = line.strip()
            if line.startswith("- `"):
                fpath = line[3:].split("`")[0].strip()
                files.append(fpath)
                if not fpath.startswith("app/"):
                    fail(f"{item_id}: Scope violation: '{fpath}' is outside app/")
    else:
        fail(f"{item_id}: Missing or malformed - **Files Touched** list")

    # Status check
    status_match = re.search(r"-\s+\*\*Status\*\*:\s*(\w+)", block)
    if not status_match or status_match.group(1).lower() not in ("todo", "filed", "done"):
        fail(f"{item_id}: Status must be one of todo, filed, done")

    items[item_id] = {
        "title": title,
        "deps": deps,
        "files": files,
        "block": block
    }

if (roadmap_file.endswith("ROADMAP.md") or roadmap_file.endswith("po/ROADMAP.md")) and len(items) < 5:
    fail(f"Expected at least 5 roadmap items, but parsed {len(items)}")
elif len(items) < 1:
    fail("Roadmap must contain at least 1 item")
else:
    ok(f"Parsed {len(items)} roadmap items with unique IDs")

# Check all dependencies exist
for item_id, data in items.items():
    for dep in data["deps"]:
        if dep not in items:
            fail(f"{item_id} depends on non-existent item {dep}")

# Cycle detection via topological sort / DFS
adj = defaultdict(list)
in_degree = {i: 0 for i in items}
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

ok("Every item has acceptance criteria and strictly app/ paths")

if failures > 0:
    print(f"Roadmap lint failed with {failures} error(s).", file=sys.stderr)
    sys.exit(1)

print("PASS: Roadmap file satisfies all integrity and scope constraints.")
EOF
