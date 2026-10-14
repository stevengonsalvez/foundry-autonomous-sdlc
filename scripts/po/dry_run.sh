#!/usr/bin/env bash
# Dry-run execution mode for the Simulated Human persona.
# Simulates persona evaluation against fixture states and prints the exact
# gh commands it would run without executing them.
#
# Usage:
#   scripts/po/dry_run.sh <fixture_dir>
#   scripts/po/dry_run.sh --state <state.json> --issues <issues.json>

set -euo pipefail

state_file=""
issues_file=""
roadmap_file=""

if [ $# -eq 1 ] && [ -d "$1" ]; then
  state_file="$1/state.json"
  issues_file="$1/issues.json"
  if [ -f "$1/roadmap.md" ]; then
    roadmap_file="$1/roadmap.md"
  elif [ -f "$1/ROADMAP.md" ]; then
    roadmap_file="$1/ROADMAP.md"
  fi
elif [ $# -ge 2 ]; then
  while [ $# -gt 0 ]; do
    case "$1" in
      --state) state_file="$2"; shift 2 ;;
      --issues) issues_file="$2"; shift 2 ;;
      --roadmap) roadmap_file="$2"; shift 2 ;;
      *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
  done
else
  echo "Usage: scripts/po/dry_run.sh <fixture_dir> OR --state <file> --issues <file> [--roadmap <file>]" >&2
  exit 1
fi

if [ -z "$roadmap_file" ] && [ -f "po/ROADMAP.md" ]; then
  roadmap_file="po/ROADMAP.md"
fi

[ -f "$state_file" ] || { echo "Error: State file not found: $state_file" >&2; exit 1; }
[ -f "$issues_file" ] || { echo "Error: Issues file not found: $issues_file" >&2; exit 1; }

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
      roadmap_eval="$(python3 - "$roadmap_file" << 'PYEOF'
import sys, re, json

roadmap_file = sys.argv[1]
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

todo_items = [it for it in items if it["status"] == "todo"]
done_or_filed = {it["id"] for it in items if it["status"] in ("done", "filed")}

ready_item = None
for it in todo_items:
    if all(d in done_or_filed for d in it["deps"]):
        ready_item = it
        break

result = {
    "total": len(items),
    "todo_count": len(todo_items),
    "ready_item": ready_item
}
print(json.dumps(result))
PYEOF
)"
      todo_count="$(jq -r '.todo_count' <<< "$roadmap_eval")"

      if [ "$todo_count" -lt 5 ]; then
        echo "[HAT] Product Owner: Fewer than 5 todo items remaining in roadmap ($todo_count left). Requesting maintainer extension."
        extend_body="### Simulated human (antigravity)

## Context
The product roadmap ($roadmap_file) has fewer than 5 todo items remaining. To sustain continuous progressive improvement of the parcel tracker (app/), the backlog needs maintainer extension.

## Request
Please extend po/ROADMAP.md with the next batch of independently shippable improvements to app/.

## Scope
po/ROADMAP.md"
        commands+=("gh issue create --title \"roadmap: extend po/ROADMAP.md\" --body \"$extend_body\" --label \"needs-maintainer,simulated-human\"")
      else
        ready_item="$(jq -c '.ready_item' <<< "$roadmap_eval")"
        if [ "$ready_item" != "null" ]; then
          item_id="$(jq -r '.id' <<< "$ready_item")"
          item_title="$(jq -r '.title' <<< "$ready_item")"
          item_gap="$(jq -r '.gap' <<< "$ready_item")"
          item_user_val="$(jq -r '.user_val' <<< "$ready_item")"
          item_ac="$(jq -r '.ac' <<< "$ready_item")"
          item_files="$(jq -r '.files' <<< "$ready_item")"

          echo "[HAT] Product Owner: Pipeline is idle. Selecting next roadmap item by dependency order: $item_id ('$item_title')"

          new_issue_body="### Simulated human (antigravity)

## Roadmap Reference
$item_id

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
        fi
      fi
    else
      echo "[HAT] Product Owner: Pipeline is idle. Preparing ONE improvement issue tied to a real gap."

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
