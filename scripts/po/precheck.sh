#!/usr/bin/env bash
# Precheck script for the Simulated Human loop.
# Executed by Orca before each scheduled 4-hour run.
#
# Exit codes:
#   0 = Continue: run the persona session
#   1 = Skip: do not run this scheduled cycle
#
# Outputs exactly one line explaining the decision to stdout.

set -euo pipefail

REPO="${REPO:-stevengonsalvez/foundry-autonomous-sdlc}"
STATE_FILE="${STATE_FILE:-}"
ISSUES_FILE="${ISSUES_FILE:-}"
CURRENT_TIME_OVERRIDE="${CURRENT_TIME_OVERRIDE:-}"
AGY_QUOTA_EXHAUSTED="${AGY_QUOTA_EXHAUSTED:-0}"
AGY_TOKEN_FILE="${AGY_TOKEN_FILE:-$HOME/.gemini/antigravity-cli/antigravity-oauth-token}"

# Verify jq is available
if ! command -v jq >/dev/null 2>&1; then
  echo "SKIP: jq is required but not installed"
  exit 1
fi

# 1. Check agy quota
if [ "$AGY_QUOTA_EXHAUSTED" = "1" ]; then
  echo "SKIP: agy quota is exhausted"
  exit 1
fi

# In live mode (no mock state/issues provided), ensure agy token file exists
if [ -z "$STATE_FILE" ] && [ -z "$ISSUES_FILE" ]; then
  if [ ! -s "$AGY_TOKEN_FILE" ]; then
    echo "SKIP: agy quota is exhausted or token file is missing"
    exit 1
  fi
fi

# 2. Retrieve state.json
state_json=""
if [ -n "$STATE_FILE" ]; then
  if [ -f "$STATE_FILE" ]; then
    state_json="$(cat "$STATE_FILE")"
  else
    echo "SKIP: state.json is missing (file not found: $STATE_FILE)"
    exit 1
  fi
else
  # Retrieve via gh api or git show on branch state
  if command -v gh >/dev/null 2>&1; then
    state_json="$(gh api "repos/$REPO/contents/state.json?ref=state" --jq '.content' 2>/dev/null | base64 -d 2>/dev/null || true)"
  fi
  if [ -z "$state_json" ]; then
    state_json="$(git show origin/state:state.json 2>/dev/null || true)"
  fi
fi

if [ -z "$state_json" ] || ! jq -e 'type == "object"' <<< "$state_json" >/dev/null 2>&1; then
  echo "SKIP: state.json is missing or invalid on branch state"
  exit 1
fi

# 3. Check staleness (over 45 minutes / 2700 seconds)
updated_at="$(jq -r '.updated_at // .generated_at // empty' <<< "$state_json")"
if [ -z "$updated_at" ]; then
  echo "SKIP: state.json is missing updated_at timestamp"
  exit 1
fi

state_epoch="$(date -d "$updated_at" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$updated_at" +%s 2>/dev/null || echo 0)"
if [ "$state_epoch" -eq 0 ]; then
  echo "SKIP: unable to parse updated_at timestamp: $updated_at"
  exit 1
fi

if [ -n "$CURRENT_TIME_OVERRIDE" ]; then
  now_epoch="$(date -d "$CURRENT_TIME_OVERRIDE" +%s 2>/dev/null || echo "$CURRENT_TIME_OVERRIDE")"
else
  now_epoch="$(date +%s)"
fi

age_s=$((now_epoch - state_epoch))
if [ "$age_s" -gt 2700 ]; then
  echo "SKIP: state.json is stale (${age_s}s old, exceeds 45 min limit)"
  exit 1
fi

# 4. Check billed spend (over 18 USD)
billed_usd="$(jq -r '.cost.billing.billed_usd // .cost.totals.billed_usd // 0' <<< "$state_json")"
is_over_spend="$(jq -n --arg b "$billed_usd" '($b | tonumber) > 18.0')"
if [ "$is_over_spend" = "true" ]; then
  echo "SKIP: billed spend ($billed_usd USD) exceeds 18.00 USD cap"
  exit 1
fi

# 5. Retrieve open issues
issues_json=""
if [ -n "$ISSUES_FILE" ]; then
  if [ -f "$ISSUES_FILE" ]; then
    issues_json="$(cat "$ISSUES_FILE")"
  else
    issues_json="[]"
  fi
else
  if command -v gh >/dev/null 2>&1; then
    issues_json="$(gh issue list --repo "$REPO" --state open --json number,title,author,labels,createdAt 2>/dev/null || echo "[]")"
  else
    issues_json="[]"
  fi
fi

if ! jq -e 'type == "array"' <<< "$issues_json" >/dev/null 2>&1; then
  issues_json="[]"
fi

# Inspect open issues: look for busy stages, open escalations, or refinement requests
# Filter to issues authored by stevengonsalvez (guardrail)
has_building="$(jq '[.[] | select(.author.login == "stevengonsalvez") | select(.labels[]?.name == "stage:building")] | length' <<< "$issues_json")"
has_in_review="$(jq '[.[] | select(.author.login == "stevengonsalvez") | select(.labels[]?.name == "stage:in-review")] | length' <<< "$issues_json")"

open_escalations="$(jq -r '[.[] | select(.author.login == "stevengonsalvez") | {number: .number, label: (.labels[]?.name | select(startswith("escalated:")))}] | first // empty | "\(.number) \(.label)"' <<< "$issues_json")"
open_refinements="$(jq -r '[.[] | select(.author.login == "stevengonsalvez") | select(.labels[]?.name == "stage:needs-refinement")] | first // empty | .number' <<< "$issues_json")"

# 6. Check daily issue cap (6 issues with label simulated-human filed in last 24 hours)
daily_count=0
if [ -n "$ISSUES_FILE" ]; then
  daily_count="$(jq --argjson now "$now_epoch" '
    [
      .[]
      | select(.labels[]?.name == "simulated-human")
      | select(.createdAt != null)
      | .createdAt as $ca
      | ($ca | fromdateiso8601? // 0) as $t
      | select(($now - $t) <= 86400 and ($now - $t) >= 0)
    ] | length
  ' <<< "$issues_json")"
else
  if command -v gh >/dev/null 2>&1; then
    recent_sim_issues="$(gh issue list --repo "$REPO" --label "simulated-human" --state all --limit 20 --json number,createdAt 2>/dev/null || echo "[]")"
    daily_count="$(jq --argjson now "$now_epoch" '
      [
        .[]
        | .createdAt as $ca
        | ($ca | fromdateiso8601? // 0) as $t
        | select(($now - $t) <= 86400 and ($now - $t) >= 0)
      ] | length
    ' <<< "$recent_sim_issues")"
  fi
fi

# 7. Decision logic
# If an open escalation or refinement question needs an answer, that is NOT a skip (answering is the point)
if [ -n "$open_escalations" ]; then
  echo "RUN: open escalation needs response (#$open_escalations), spend within budget (${billed_usd} USD <= 18.00 USD)"
  exit 0
fi

if [ -n "$open_refinements" ]; then
  echo "RUN: requirements question needs response (#$open_refinements), spend within budget (${billed_usd} USD <= 18.00 USD)"
  exit 0
fi

# If any issue is in stage:building or stage:in-review and no escalations/refinements exist -> SKIP
if [ "$has_building" -gt 0 ] || [ "$has_in_review" -gt 0 ]; then
  echo "SKIP: pipeline is busy (building: $has_building, in-review: $has_in_review) and no open escalations to answer"
  exit 1
fi

# If pipeline is idle, check daily issue cap of 6 before filing a new issue
if [ "$daily_count" -ge 6 ]; then
  echo "SKIP: daily issue cap reached ($daily_count simulated-human issues filed in last 24h)"
  exit 1
fi

# All checks passed, pipeline is idle and ready for new intake
echo "RUN: pipeline idle, spend within budget (${billed_usd} USD <= 18.00 USD), daily issues ${daily_count}/6"
exit 0
