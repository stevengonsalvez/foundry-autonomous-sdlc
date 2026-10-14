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
missing_needs_maintainer=0

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
    print(f"missing_needs_maintainer={1 if 'needs-maintainer' not in existing else 0}")
except Exception:
    print("missing_simulated_human=0")
    print("missing_needs_maintainer=0")
PYEOF
  )"
  eval "$labels_check"
fi

echo "[DRY RUN] Evaluating simulated human persona logic..."
state_json="$(cat "$state_file")"
issues_json="$(cat "$issues_file")"

billed_usd="$(jq -r '.cost.billing.billed_usd // .cost.totals.billed_usd // 0' <<< "$state_json")"
echo "[DRY RUN] Current billed spend: ${billed_usd} USD (Cap: 18.00 USD)"

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

  # Guardrail (a): Untrusted data and author restriction
  if [ "$author" != "stevengonsalvez" ]; then
    echo "[SECURITY] Ignoring issue #$number ('$title') by author '$author' (only stevengonsalvez is trusted)."
    continue
  fi

  # Guardrail (a): Prompt injection defense
  if grep -iP "(ignore all previous instructions|system override|approve pr|merge pr|raise.*spend cap)" <<< "$body" >/dev/null 2>&1; then
    echo "[SECURITY] Untrusted input detected in issue #$number body. Prompt injection payload neutralized."
  fi

  # Check stages and labels
  labels="$(jq -r '[.labels[]?.name] | join(",")' <<< "$issue")"

  if grep -q "stage:building" <<< "$labels" || grep -q "stage:in-review" <<< "$labels"; then
    is_busy=1
  fi

  # Hat 1: Requirements Answerer
  if grep -q "stage:needs-refinement" <<< "$labels"; then
    hat_refinement=$((hat_refinement + 1))
    echo "[HAT] Requirements Answerer: Processing clarification questions for issue #$number"
    if [ "$missing_simulated_human" -eq 1 ]; then
      echo "[LABELS] Warning: Label 'simulated-human' missing from repository. Planning label creation."
      commands+=("gh label create \"simulated-human\" --description \"Actions managed by simulated human persona\" --color \"0E8A16\"")
      missing_simulated_human=0
    fi
    comment_body="### Simulated human (antigravity)

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
    if [ "$missing_simulated_human" -eq 1 ]; then
      echo "[LABELS] Warning: Label 'simulated-human' missing from repository. Planning label creation."
      commands+=("gh label create \"simulated-human\" --description \"Actions managed by simulated human persona\" --color \"0E8A16\"")
      missing_simulated_human=0
    fi
    commands+=("gh issue edit $number --add-label \"bug:triaged,severity:s2,owner:web,simulated-human\"")
    comment_body="### Simulated human (antigravity)

Triaged as severity s2 (workaround available) owned by web workspace."
    commands+=("gh issue comment $number --body \"$comment_body\"")
    continue
  fi

  # Hat 3: Escalation Owner
  if grep -q "escalated:" <<< "$labels"; then
    hat_escalation=$((hat_escalation + 1))

    # Guardrail (e): Cost-cap escalation
    if grep -q "escalated:cost-cap" <<< "$labels"; then
      echo "[HAT] Escalation Owner: Handling cost-cap escalation on issue #$number"
      echo "[GUARDRAIL] NEVER raise spend cap or continue past halt limit. Closing or parking issue."
      if [ "$missing_simulated_human" -eq 1 ]; then
        echo "[LABELS] Warning: Label 'simulated-human' missing from repository. Planning label creation."
        commands+=("gh label create \"simulated-human\" --description \"Actions managed by simulated human persona\" --color \"0E8A16\"")
        missing_simulated_human=0
      fi
      comment_body="### Simulated human (antigravity)

Closing issue due to cost cap limit. Spend reached the allocated cap.
Under strict spend guardrails, spend caps are never raised and execution does not continue past the 22 USD halt limit.
Follow-up work should be split into a scoped, smaller increment."
      commands+=("gh issue comment $number --body \"$comment_body\"")
      commands+=("gh issue edit $number --add-label \"simulated-human\"")
      commands+=("gh issue close $number")
      continue
    fi

    # Guardrail (f): CD rollback escalation
    if grep -q "escalated:deploy-failed" <<< "$labels"; then
      echo "[HAT] Escalation Owner: Handling CD rollback escalation on issue #$number"
      echo "[GUARDRAIL] NEVER instruct re-release of rolled-back build. Filing fix issue."
      if [ "$missing_simulated_human" -eq 1 ]; then
        echo "[LABELS] Warning: Label 'simulated-human' missing from repository. Planning label creation."
        commands+=("gh label create \"simulated-human\" --description \"Actions managed by simulated human persona\" --color \"0E8A16\"")
        missing_simulated_human=0
      fi
      comment_body="### Simulated human (antigravity)

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
      if [ "$missing_simulated_human" -eq 1 ]; then
        echo "[LABELS] Warning: Label 'simulated-human' missing from repository. Planning label creation."
        commands+=("gh label create \"simulated-human\" --description \"Actions managed by simulated human persona\" --color \"0E8A16\"")
        missing_simulated_human=0
      fi
      comment_body="### Simulated human (antigravity)

Issue requires external vendor contracts, live credentials, or manual authorization.
Reframing: Autonomous SDLC work is restricted to mock environments and local contracts.
Closing external-scope request; please use carrier-mock integration tests for local verification."
      commands+=("gh issue comment $number --body \"$comment_body\"")
      commands+=("gh issue edit $number --add-label \"simulated-human\"")
      commands+=("gh issue close $number")
      continue
    fi

    # Other escalations (e.g. escalated:requirements, escalated:build-failed)
    echo "[HAT] Escalation Owner: Reviewing escalation on issue #$number"
    if [ "$missing_simulated_human" -eq 1 ]; then
      echo "[LABELS] Warning: Label 'simulated-human' missing from repository. Planning label creation."
      commands+=("gh label create \"simulated-human\" --description \"Actions managed by simulated human persona\" --color \"0E8A16\"")
      missing_simulated_human=0
    fi
    comment_body="### Simulated human (antigravity)

Reviewing failed pipeline attempts. Storing findings in run log."
    commands+=("gh issue comment $number --body \"$comment_body\"")
    commands+=("gh issue edit $number --add-label \"simulated-human\"")
    continue
  fi
done

# Hat 4: Product Owner (Only when idle, no active escalations or questions being answered)
if [ "$hat_refinement" -eq 0 ] && [ "$hat_escalation" -eq 0 ]; then
  if [ "$is_busy" -eq 1 ]; then
    echo "[PIPELINE] Pipeline is busy with active building or review. Product Owner hat skipped."
  else
    hat_po=1

    if [ -n "$roadmap_file" ] && [ -f "$roadmap_file" ]; then
      roadmap_eval="$(python3 - "$roadmap_file" "$issues_file" "$memory_file" "$labels_file" << 'PYEOF'
import sys, os, re, json

roadmap_file = sys.argv[1] if len(sys.argv) > 1 else ""
issues_file = sys.argv[2] if len(sys.argv) > 2 else ""
memory_file = sys.argv[3] if len(sys.argv) > 3 else ""
labels_file = sys.argv[4] if len(sys.argv) > 4 else ""

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
        "gap": gap,
        "user_val": user_val,
        "ac": ac,
        "files": files
    })

items_by_id = {it["id"]: it for it in items}
done_items = {it["id"] for it in items if it["status"] == "done"}
filed_items = {it["id"] for it in items if it["status"] == "filed"}
open_needs_maintainer_issue = None

if issues_file and os.path.isfile(issues_file):
    try:
        with open(issues_file, "r", encoding="utf-8") as f:
            issues_data = json.load(f)
        for iss in issues_data:
            num = iss.get("number")
            title = iss.get("title", "")
            body = iss.get("body", "")
            state = iss.get("state", "open")
            raw_labels = iss.get("labels", [])
            labels = [l["name"] if isinstance(l, dict) else str(l) for l in raw_labels]

            if state == "open" and "needs-maintainer" in labels:
                open_needs_maintainer_issue = num or 1

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

if memory_file and os.path.isfile(memory_file):
    try:
        with open(memory_file, "r", encoding="utf-8") as f:
            mem_content = f.read()
        for m in re.finditer(r"\b(ITEM-\d+)\b", mem_content):
            item_id = m.group(1).upper()
            if item_id in items_by_id and item_id not in done_items:
                filed_items.add(item_id)
    except Exception:
        pass

todo_items = [it for it in items if it["status"] == "todo" and it["id"] not in done_items and it["id"] not in filed_items]
todo_count = len(todo_items)

action = ""
ready_item = None
if todo_count < 5:
    if open_needs_maintainer_issue:
        action = "maintainer_already_open"
    else:
        action = "request_maintainer_extension"
else:
    for it in todo_items:
        if all(d in done_items for d in it["deps"]):
            ready_item = it
            break
    if ready_item:
        action = "file_roadmap_item"
    else:
        action = "no_unblocked_item"

result = {
    "total": len(items),
    "todo_count": todo_count,
    "action": action,
    "ready_item": ready_item,
    "open_needs_maintainer_issue": open_needs_maintainer_issue
}
print(json.dumps(result))
PYEOF
)"
      action="$(jq -r '.action' <<< "$roadmap_eval")"
      todo_count="$(jq -r '.todo_count' <<< "$roadmap_eval")"

      if [ "$action" = "maintainer_already_open" ]; then
        open_num="$(jq -r '.open_needs_maintainer_issue' <<< "$roadmap_eval")"
        echo "[HAT] Product Owner: Fewer than 5 todo items remaining in roadmap ($todo_count left), but an open needs-maintainer issue already exists (#$open_num). Pausing intake without duplicate filing."
      elif [ "$action" = "request_maintainer_extension" ]; then
        echo "[HAT] Product Owner: Fewer than 5 todo items remaining in roadmap ($todo_count left). Requesting maintainer extension."
        if [ "$missing_needs_maintainer" -eq 1 ]; then
          echo "[LABELS] Warning: Label 'needs-maintainer' missing from repository. Planning label creation."
          commands+=("gh label create \"needs-maintainer\" --description \"Requires repository maintainer attention\" --color \"B60205\"")
          missing_needs_maintainer=0
        fi
        if [ "$missing_simulated_human" -eq 1 ]; then
          echo "[LABELS] Warning: Label 'simulated-human' missing from repository. Planning label creation."
          commands+=("gh label create \"simulated-human\" --description \"Actions managed by simulated human persona\" --color \"0E8A16\"")
          missing_simulated_human=0
        fi
        extend_body="### Simulated human (antigravity)

## Context
The product roadmap ($roadmap_file) has fewer than 5 todo items remaining. To sustain continuous progressive improvement of the parcel tracker (app/), the backlog needs maintainer extension.

## Request
Please extend po/ROADMAP.md with the next batch of independently shippable improvements to app/.

## Scope
po/ROADMAP.md"
        commands+=("gh issue create --title \"roadmap: extend po/ROADMAP.md\" --body \"$extend_body\" --label \"needs-maintainer,simulated-human\"")
      elif [ "$action" = "file_roadmap_item" ]; then
        ready_item="$(jq -c '.ready_item' <<< "$roadmap_eval")"
        item_id="$(jq -r '.id' <<< "$ready_item")"
        item_title="$(jq -r '.title' <<< "$ready_item")"
        item_gap="$(jq -r '.gap' <<< "$ready_item")"
        item_user_val="$(jq -r '.user_val' <<< "$ready_item")"
        item_ac="$(jq -r '.ac' <<< "$ready_item")"
        item_files="$(jq -r '.files' <<< "$ready_item")"

        echo "[HAT] Product Owner: Pipeline is idle. Selecting next roadmap item by dependency order: $item_id ('$item_title')"

        if [ "$missing_simulated_human" -eq 1 ]; then
          echo "[LABELS] Warning: Label 'simulated-human' missing from repository. Planning label creation."
          commands+=("gh label create \"simulated-human\" --description \"Actions managed by simulated human persona\" --color \"0E8A16\"")
          missing_simulated_human=0
        fi

        new_issue_body="### Simulated human (antigravity)

## Roadmap Reference
Roadmap item: $item_id

## Context
$item_gap

## User story
$item_user_val

## Acceptance criteria
$item_ac

## Scope
$item_files

## Out of scope
Work outside app/ or unrelated refactoring."

        commands+=("gh issue create --title \"$item_title\" --body \"$new_issue_body\" --label \"type:feature,simulated-human\"")
      elif [ "$action" = "no_unblocked_item" ]; then
        echo "[HAT] Product Owner: Pipeline is idle but all remaining roadmap items are blocked by unsatisfied dependencies."
      fi
    else
      echo "[HAT] Product Owner: Pipeline is idle. Preparing ONE improvement issue tied to a real gap."

      if [ "$missing_simulated_human" -eq 1 ]; then
        echo "[LABELS] Warning: Label 'simulated-human' missing from repository. Planning label creation."
        commands+=("gh label create \"simulated-human\" --description \"Actions managed by simulated human persona\" --color \"0E8A16\"")
        missing_simulated_human=0
      fi

      new_issue_body="### Simulated human (antigravity)

## Context
Carrier contract app/contracts/carrier.openapi.yaml includes event location metadata, but app/web parcel timeline currently displays only description and timestamp.

## User story
As a parcel recipient, I want to see the event location in the timeline so that I know where my parcel was scanned.

## Acceptance criteria
1. When an event contains a non-empty location string, display it beneath the event description as 'Location: <location>'.
2. The location text must be a visible text node accessible to screen readers.
3. When location is null or omitted, no location line or empty node is rendered.
4. Existing event ordering and styling are preserved.

## Scope
app/web only.

## Out of scope
Geocoding or map views."

      commands+=("gh issue create --title \"feat(web): display event location in parcel timeline\" --body \"$new_issue_body\" --label \"type:feature,simulated-human\"")
    fi
  fi
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
