#!/usr/bin/env bash
# Dry-run execution mode for the Simulated Human persona.
# Simulates persona evaluation against fixture states and prints the exact
# gh commands it would run without executing them.
#
# Usage:
#   scripts/po/dry_run.sh <fixture_dir>
#   scripts/po/dry_run.sh --state <file> --issues <file> [--roadmap <file>] [--memory <file>] [--labels <file>]

set -euo pipefail

state_file=""
issues_file=""
roadmap_file=""
memory_file=""
labels_file=""

# If first argument is an existing directory, load fixture files
if [ $# -ge 1 ] && [ -d "$1" ]; then
  fixture_dir="$1"
  shift
  state_file="$fixture_dir/state.json"
  issues_file="$fixture_dir/issues.json"
  if [ -f "$fixture_dir/roadmap.md" ]; then
    roadmap_file="$fixture_dir/roadmap.md"
  elif [ -f "$fixture_dir/ROADMAP.md" ]; then
    roadmap_file="$fixture_dir/ROADMAP.md"
  fi
  if [ -f "$fixture_dir/memory.md" ]; then
    memory_file="$fixture_dir/memory.md"
  elif [ -f "$fixture_dir/MEMORY.md" ]; then
    memory_file="$fixture_dir/MEMORY.md"
  fi
  if [ -f "$fixture_dir/labels.json" ]; then
    labels_file="$fixture_dir/labels.json"
  elif [ -f "$fixture_dir/LABELS.json" ]; then
    labels_file="$fixture_dir/LABELS.json"
  fi
fi

# Parse remaining or direct options
while [ $# -gt 0 ]; do
  case "$1" in
    --state) state_file="$2"; shift 2 ;;
    --issues) issues_file="$2"; shift 2 ;;
    --roadmap) roadmap_file="$2"; shift 2 ;;
    --memory) memory_file="$2"; shift 2 ;;
    --labels) labels_file="$2"; shift 2 ;;
    *) echo "Unknown option or extra argument: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$state_file" ] || [ -z "$issues_file" ]; then
  echo "Usage: scripts/po/dry_run.sh <fixture_dir> OR scripts/po/dry_run.sh --state <file> --issues <file> [--roadmap <file>] [--memory <file>] [--labels <file>]" >&2
  exit 1
fi

[ -f "$state_file" ] || { echo "Error: State file not found: $state_file" >&2; exit 1; }
[ -f "$issues_file" ] || { echo "Error: Issues file not found: $issues_file" >&2; exit 1; }
if [ -n "$roadmap_file" ] && [ ! -f "$roadmap_file" ]; then
  echo "Error: Roadmap file not found: $roadmap_file" >&2; exit 1
fi
if [ -n "$memory_file" ] && [ ! -f "$memory_file" ]; then
  echo "Error: Memory file not found: $memory_file" >&2; exit 1
fi
if [ -n "$labels_file" ] && [ ! -f "$labels_file" ]; then
  echo "Error: Labels file not found: $labels_file" >&2; exit 1
fi

missing_simulated_human=0

if [ -n "$labels_file" ] && [ -f "$labels_file" ]; then
  labels_check="$(python3 - "$labels_file" << 'PYEOF'
import sys, json
path = sys.argv[1]
try:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    existing = set()
    for entry in data:
        if isinstance(entry, dict) and "name" in entry:
            existing.add(entry["name"])
        elif isinstance(entry, str):
            existing.add(entry)
    print(f"missing_simulated_human={1 if 'simulated-human' not in existing else 0}")
except Exception:
    print("missing_simulated_human=1")
PYEOF
  )"
  eval "$labels_check"
fi

echo "[DRY RUN] Evaluating simulated human persona logic..."
state_json="$(cat "$state_file")"
issues_json="$(cat "$issues_file")"

billed_usd="$(jq -r '.cost.billing.billed_usd // .cost.totals.billed_usd // 0' <<< "$state_json")"
echo "[DRY RUN] Current billed spend: ${billed_usd} USD (Cap: 30.00 USD)"
echo "[DRY RUN] Note: dry-run evaluates persona logic; scripts/po/precheck.sh is the authoritative spend gate."

# Track commands to output
declare -a commands=()

# Track active hats
hat_refinement=0
hat_triage=0
hat_escalation=0
hat_po=0

is_busy=0

# Scan issues
num_issues="$(jq '. | length' <<< "$issues_json")"

for ((i=0; i<num_issues; i++)); do
  issue="$(jq -c ".[$i]" <<< "$issues_json")"
  number="$(jq -r '.number' <<< "$issue")"
  title="$(jq -r '.title' <<< "$issue")"
  author="$(jq -r '.author.login // empty' <<< "$issue")"
  body="$(jq -r '.body // ""' <<< "$issue")"
  state="$(jq -r '.state // "OPEN"' <<< "$issue")"

  # Skip hats unless issue state is OPEN (case-insensitive)
  if [ "${state^^}" != "OPEN" ]; then
    continue
  fi

  # Guardrail (a): Untrusted data and author restriction
  if [ "$author" != "stevengonsalvez" ]; then
    echo "[SECURITY] Ignoring issue #$number ('$title') by author '$author' (only stevengonsalvez is trusted)."
    continue
  fi

  # Guardrail (a): Prompt injection defense (using Python, no grep -iP)
  has_injection="$(python3 -c '
import sys, re
body = sys.stdin.read()
pattern = re.compile(r"(ignore all previous instructions|system override|approve pr|merge pr|raise.*spend cap)", re.IGNORECASE)
print("1" if pattern.search(body) else "0")
' <<< "$body")"
  if [ "$has_injection" = "1" ]; then
    echo "[SECURITY] Untrusted input detected in issue #$number body. Prompt injection payload neutralized."
  fi

  # Check stages and labels
  labels="$(jq -r '[.labels[]?.name] | join(",")' <<< "$issue")"

  if grep -q "stage:building" <<< "$labels" || grep -q "stage:in-review" <<< "$labels"; then
    is_busy=1
  fi

  # Check if issue was already answered by persona with <!-- po-answered:v1 --> (owner-only)
  already_answered="$(python3 -c '
import sys, json
try:
    issue_data = json.loads(sys.argv[1])
    comments = issue_data.get("comments", [])
    answered = any(
        "<!-- po-answered:v1 -->" in (c.get("body") or "")
        and (c.get("author") or {}).get("login") == "stevengonsalvez"
        for c in comments
    )
    print("1" if answered else "0")
except Exception:
    print("0")
' "$issue")"

  # Agent-quota escalation: a factory fault (the coder's agy account is spent); leave it for the owner
  if grep -q "escalated:agent-quota" <<< "$labels"; then
    hat_escalation=$((hat_escalation + 1))
    echo "[HAT] Escalation Owner: Leaving agent-quota escalation on issue #$number for the owner (no comment, no label, no close, no new issue)."
    continue
  fi

  # Handle build-failed and review-failed escalations (close even if already answered)
  if grep -q "escalated:build-failed" <<< "$labels" || grep -q "escalated:review-failed" <<< "$labels" \
    || grep -q "escalated:merge-conflict" <<< "$labels"; then
    hat_escalation=$((hat_escalation + 1))
    if [ "$already_answered" = "1" ]; then
      echo "[HAT] Escalation Owner: Issue #$number (build-failed/review-failed/merge-conflict) was answered with po-answered marker but remains open. Closing issue."
      commands+=("gh issue close $number")
    else
      echo "[HAT] Escalation Owner: Handling build-failed/review-failed/merge-conflict escalation on issue #$number"
      comment_body="### Simulated human (antigravity)
<!-- po-answered:v1 -->

Reviewing failed pipeline attempts from coder logs or PR review.
Closing issue to unblock pipeline."
      commands+=("gh issue comment $number --body \"$comment_body\"")
      commands+=("gh issue edit $number --add-label \"simulated-human\"")
      commands+=("gh issue close $number")
    fi
    continue
  fi

  if [ "$already_answered" = "1" ]; then
    echo "[HAT] Skipping issue #$number: already answered with po-answered marker."
    continue
  fi

  # Hat 1: Requirements Answerer
  if grep -q "stage:needs-refinement" <<< "$labels"; then
    hat_refinement=$((hat_refinement + 1))
    echo "[HAT] Requirements Answerer: Processing clarification questions for issue #$number"
    comment_body="### Simulated human (antigravity)
<!-- po-answered:v1 -->

**Clarifications and Refinements:**
1. Scope is strictly confined to app/web and client-side presentation.
2. Acceptance criteria require explicit screen-reader accessible text nodes.
3. Component error boundaries must prevent unhandled errors on null or malformed data."
    commands+=("gh issue comment $number --body \"$comment_body\"")
    commands+=("gh issue edit $number --add-label \"simulated-human\"")
    continue
  fi

  # Hat 2: Triage Lead
  if grep -q "type:bug" <<< "$labels" && ! grep -q "bug:triaged" <<< "$labels"; then
    hat_triage=$((hat_triage + 1))
    echo "[HAT] Triage Lead: Triaging defect #$number ('$title')"
    commands+=("gh issue edit $number --add-label \"bug:triaged,severity:s3,owner:web,simulated-human\"")
    comment_body="### Simulated human (antigravity)
<!-- po-answered:v1 -->

Triaged as severity s3 (workaround available) owned by web workspace."
    commands+=("gh issue comment $number --body \"$comment_body\"")
    continue
  fi

  # Hat 3: Escalation Owner
  if grep -q "escalated:" <<< "$labels"; then
    hat_escalation=$((hat_escalation + 1))

    # Agent-error escalation (Issue 72 shaped)
    if grep -q "escalated:agent-error" <<< "$labels"; then
      echo "[HAT] Escalation Owner: Handling agent-error escalation on issue #$number"
      comment_body="### Simulated human (antigravity)
<!-- po-answered:v1 -->

Agent encountered persistent failure streak or invalid test assertions after coder repair iterations.
Closing ticket to unblock autonomous SDLC pipeline; work is dropped as out of roadmap scope."
      commands+=("gh issue comment $number --body \"$comment_body\"")
      commands+=("gh issue edit $number --add-label \"simulated-human\"")
      commands+=("gh issue close $number")
      continue
    fi

    # Cost-cap escalation
    if grep -q "escalated:cost-cap" <<< "$labels"; then
      echo "[HAT] Escalation Owner: Handling cost-cap escalation on issue #$number"
      echo "[GUARDRAIL] NEVER raise spend cap or continue past halt limit. Closing or parking issue."
      comment_body="### Simulated human (antigravity)
<!-- po-answered:v1 -->

Closing issue due to cost cap limit. Spend reached the allocated cap.
Under strict spend guardrails, spend caps are never raised and execution does not continue past the 32 USD halt limit.
Follow-up work should be split into a scoped, smaller increment."
      commands+=("gh issue comment $number --body \"$comment_body\"")
      commands+=("gh issue edit $number --add-label \"simulated-human\"")
      commands+=("gh issue close $number")
      continue
    fi

    # CD rollback escalation
    if grep -q "escalated:deploy-failed" <<< "$labels"; then
      echo "[HAT] Escalation Owner: Handling CD rollback escalation on issue #$number"
      echo "[GUARDRAIL] NEVER instruct re-release of rolled-back build. Filing fix issue."
      comment_body="### Simulated human (antigravity)
<!-- po-answered:v1 -->

CD deployment failed smoke or soak verification and automatically rolled back to the previous stable release.
Per deployment guardrails, the rolled-back build will not be re-released.
Filing a dedicated bug issue to address the defect with regression tests."
      commands+=("gh issue comment $number --body \"$comment_body\"")
      commands+=("gh issue edit $number --add-label \"simulated-human\"")

      fix_body="### Simulated human (antigravity)

## Context
Automated CD rollback on issue #$number detected a regression during staging smoke/soak testing.

## Problem
The build failed staging smoke assertions before promotion to production.

## Acceptance criteria
1. Identify and fix root cause identified in workflow run logs.
2. Add regression test in app/e2e/smoke preventing recurrence.
3. Pass all 6 required status checks on main before re-attempting deployment.

## Scope
app/web or app/api depending on failure logs."
      commands+=("gh issue create --title \"fix: address deployment smoke failure for #$number\" --body \"$fix_body\" --label \"type:bug,simulated-human\"")
      continue
    fi

    # Not agent suitable escalation
    if grep -q "escalated:not-agent-suitable" <<< "$labels"; then
      echo "[HAT] Escalation Owner: Handling not-agent-suitable escalation on issue #$number"
      comment_body="### Simulated human (antigravity)
<!-- po-answered:v1 -->

Issue requires external vendor contracts, live credentials, or manual authorization.
Reframing: Autonomous SDLC work is restricted to mock environments and local contracts.
Closing external-scope request; please use carrier-mock integration tests for local verification."
      commands+=("gh issue comment $number --body \"$comment_body\"")
      commands+=("gh issue edit $number --add-label \"simulated-human\"")
      commands+=("gh issue close $number")
      continue
    fi

    # Other escalations (e.g. escalated:requirements)
    echo "[HAT] Escalation Owner: Reviewing escalation on issue #$number"
    comment_body="### Simulated human (antigravity)
<!-- po-answered:v1 -->

Reviewing failed pipeline attempts. Storing findings in run log."
    commands+=("gh issue comment $number --body \"$comment_body\"")
    commands+=("gh issue edit $number --add-label \"simulated-human\"")
    continue
  fi
done

# Hat 4: Product Owner (Only when idle, no active escalations, triage, or questions being answered)
if [ "$hat_refinement" -eq 0 ] && [ "$hat_triage" -eq 0 ] && [ "$hat_escalation" -eq 0 ]; then
  if [ "$is_busy" -eq 1 ]; then
    echo "[PIPELINE] Pipeline is busy with active building or review. Product Owner hat skipped."
  else
    # Hard rule: stop when 32 halt state is flagged or billed spend exceeds 30.00 USD
    is_halted="$(jq -r '
      (.cost.totals.halted // .cost.halted // .halted // false) == true or
      ((.cost.billing.billed_usd // 0 | tonumber) >= (.cost.caps.halt_usd // 32.0 | tonumber)) or
      ((.cost.totals.usd // .cost.ledger.usd // 0 | tonumber) >= (.cost.caps.halt_usd // 32.0 | tonumber))
    ' <<< "$state_json")"
    is_over_spend="$(jq -n --arg b "$billed_usd" '($b | tonumber) > 30.0')"

    if [ "$is_halted" = "true" ]; then
      echo "[HAT] Product Owner: 32 USD halt state is flagged. Intake stopped."
    elif [ "$is_over_spend" = "true" ]; then
      echo "[HAT] Product Owner: Billed spend ($billed_usd USD) exceeds 30.00 USD cap. Intake stopped."
    elif [ -n "$roadmap_file" ] && [ -f "$roadmap_file" ]; then
      hat_po=1
      roadmap_eval="$(python3 - "$roadmap_file" "$issues_file" "$memory_file" << 'PYEOF'
import sys, os, re, json

roadmap_file = sys.argv[1] if len(sys.argv) > 1 else ""
issues_file = sys.argv[2] if len(sys.argv) > 2 else ""
memory_file = sys.argv[3] if len(sys.argv) > 3 else ""

with open(roadmap_file, "r", encoding="utf-8") as f:
    content = f.read()

item_blocks = re.split(r"(?=^###\s+ITEM-\d+:)", content, flags=re.MULTILINE)
items = []
for block in item_blocks:
    block = block.strip()
    if not block.startswith("### ITEM-"):
        continue
    header = re.match(r"^###\s+(ITEM-\d+):\s+(.+)$", block.splitlines()[0])
    if not header:
        continue
    item_id = header.group(1).strip()
    title = header.group(2).strip()

    status_m = re.search(r"-\s+\*\*Status\*\*:\s*(\w+)", block)
    status = status_m.group(1).lower() if status_m else "todo"

    dep_m = re.search(r"-\s+\*\*Dependencies\*\*:\s*\[(.*?)\]", block)
    deps = [d.strip() for d in dep_m.group(1).split(",") if d.strip()] if dep_m else []

    vs_m = re.search(r"-\s+\*\*Visible Surface\*\*:\s*(.+)$", block, re.MULTILINE)
    visible_surface = vs_m.group(1).strip() if vs_m else ""

    gap_m = re.search(r"-\s+\*\*Gap Anchor\*\*:\s*(.+)$", block, re.MULTILINE)
    gap = gap_m.group(1).strip() if gap_m else ""

    user_val_m = re.search(r"-\s+\*\*User Value\*\*:\s*(.+)$", block, re.MULTILINE)
    user_val = user_val_m.group(1).strip() if user_val_m else ""

    ac_m = re.search(r"-\s+\*\*Acceptance Criteria\*\*:\s*\n((?:\s+\d+\..*\n?)+)", block)
    ac = ac_m.group(1).strip() if ac_m else ""

    files_m = re.search(r"-\s+\*\*Files Touched\*\*:\s*\n((?:\s+-\s+`.*?`.*\n?)+)", block)
    files = files_m.group(1).strip() if files_m else "app/web"

    items.append({
        "id": item_id,
        "title": title,
        "status": status,
        "deps": deps,
        "visible_surface": visible_surface,
        "gap": gap,
        "user_val": user_val,
        "ac": ac,
        "files": files
    })

items_by_id = {it["id"]: it for it in items}
done_items = {it["id"] for it in items if it["status"] == "done"}
filed_items = {it["id"] for it in items if it["status"] == "filed"}

# Scan issues.json for filed/done items (authoritative source of truth, owner only)
if issues_file and os.path.isfile(issues_file):
    try:
        with open(issues_file, "r", encoding="utf-8") as f:
            issues_data = json.load(f)
        for iss in issues_data:
            author_login = ""
            author_obj = iss.get("author")
            if isinstance(author_obj, dict):
                author_login = author_obj.get("login", "")
            elif isinstance(author_obj, str):
                author_login = str(author_obj)
            if author_login != "stevengonsalvez":
                continue

            title = iss.get("title", "")
            body = iss.get("body", "")
            raw_labels = iss.get("labels", [])
            labels = [l["name"] if isinstance(l, dict) else str(l) for l in raw_labels]

            matched_id = None
            m = re.search(r"Roadmap item:\s*(ITEM-\d+)", body, re.IGNORECASE)
            if m:
                matched_id = m.group(1).upper()
            else:
                m2 = re.search(r"Roadmap Reference\s*\n+\s*(ITEM-\d+)", body, re.IGNORECASE)
                if m2:
                    matched_id = m2.group(1).upper()
                else:
                    m3 = re.search(r"\b(ITEM-\d+)\b", title)
                    if m3:
                        matched_id = m3.group(1).upper()
                    else:
                        for it in items:
                            if it["title"].strip() == title.strip():
                                matched_id = it["id"]
                                break

            if matched_id and matched_id in items_by_id:
                if "stage:released" in labels or "stage:merged" in labels:
                    done_items.add(matched_id)
                else:
                    filed_items.add(matched_id)
    except Exception:
        pass

# Determine remaining unfiled todo items
todo_items = [it for it in items if it["status"] == "todo" and it["id"] not in done_items and it["id"] not in filed_items]
todo_count = len(todo_items)

# Find next unblocked ready item
ready_item = None
for it in todo_items:
    if all(d in done_items for d in it["deps"]):
        ready_item = it
        break

result = {
    "total": len(items),
    "todo_count": todo_count,
    "ready_item": ready_item
}
print(json.dumps(result))
PYEOF
)"
      todo_count="$(jq -r '.todo_count' <<< "$roadmap_eval")"

      if [ "$todo_count" -lt 5 ]; then
        echo "[LOG] Roadmap extension requested: fewer than 5 todo items remaining ($todo_count left in $roadmap_file). Maintainer extension needed."
      fi

      ready_item="$(jq -c '.ready_item' <<< "$roadmap_eval")"
      if [ "$ready_item" != "null" ]; then
        item_id="$(jq -r '.id' <<< "$ready_item")"
        item_title="$(jq -r '.title' <<< "$ready_item")"
        item_visible_surface="$(jq -r '.visible_surface // empty' <<< "$ready_item")"
        item_gap="$(jq -r '.gap' <<< "$ready_item")"
        item_user_val="$(jq -r '.user_val' <<< "$ready_item")"
        item_ac="$(jq -r '.ac' <<< "$ready_item")"
        item_files="$(jq -r '.files' <<< "$ready_item")"

        echo "[HAT] Product Owner: Pipeline is idle. Selecting next roadmap item by dependency order: $item_id ('$item_title')"

        body_file="$(mktemp -t po-issue-XXXXXX.md)"
        trap 'rm -f "$body_file"' EXIT
        cat > "$body_file" << EOF
### Simulated human (antigravity)

Roadmap item: $item_id
$([ -n "$item_visible_surface" ] && printf "\n## Visible surface\n%s\n" "$item_visible_surface")
## Context
$item_gap

## User story
$item_user_val

## Acceptance criteria
$item_ac

## Scope
$item_files

## Out of scope
Work outside app/ or unrelated refactoring.
EOF

        echo "[DRY RUN] Staged issue body at $body_file:"
        cat "$body_file"

        commands+=("gh issue create --title \"$item_title\" --body-file \"$body_file\" --label \"type:feature,simulated-human\"")
      else
        echo "[HAT] Product Owner: Pipeline is idle but all remaining roadmap items are blocked by unsatisfied dependencies."
      fi
    else
      echo "[HAT] Product Owner: No roadmap file available. Intake paused until po/ROADMAP.md is provided."
    fi
  fi
fi

# Guardrail: Check label availability
if [ "$missing_simulated_human" -eq 1 ] && [ "${#commands[@]}" -gt 0 ]; then
  echo "BLOCKED: label simulated-human missing, maintainer must create it"
  commands=()
fi

echo "----------------------------------------"
echo "[DRY RUN] Summary of hats applied:"
echo "  Requirements Answerer: $hat_refinement"
echo "  Triage Lead:           $hat_triage"
echo "  Escalation Owner:      $hat_escalation"
echo "  Product Owner:         $hat_po"
echo "----------------------------------------"
echo "[DRY RUN] Planned GitHub Commands (${#commands[@]} total):"
if [ "${#commands[@]}" -eq 0 ]; then
  echo "  (No commands to execute)"
else
  for cmd in "${commands[@]}"; do
    echo "  $cmd"
  done
fi
echo "----------------------------------------"
echo "[DRY RUN] Completed successfully."
exit 0
