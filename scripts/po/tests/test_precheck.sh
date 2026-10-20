#!/usr/bin/env bash
# Test suite for scripts/po/precheck.sh using fixtures.
# Tests each skip reason and the run conditions.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PRECHECK="$SCRIPT_DIR/../precheck.sh"
FIXTURES="$SCRIPT_DIR/fixtures"

failures=0
total=0

run_test() {
  local name="$1"
  local expected_exit="$2"
  local expected_substr="$3"
  shift 3

  total=$((total + 1))
  echo -n "Test $total: $name ... "

  local output
  local exit_code=0
  output="$("$@" 2>&1)" || exit_code=$?

  if [ "$exit_code" -ne "$expected_exit" ]; then
    echo "FAIL (expected exit $expected_exit, got $exit_code)"
    echo "  Output: $output"
    failures=$((failures + 1))
    return
  fi

  if ! grep -qi "$expected_substr" <<< "$output"; then
    echo "FAIL (expected substring '$expected_substr' not found in output)"
    echo "  Output: $output"
    failures=$((failures + 1))
    return
  fi

  echo "PASS"
}

echo "Running precheck.sh test suite..."

# 1. Idle state -> Exit 0 (RUN)
run_test "Idle state runs successfully" 0 "RUN: pipeline idle" \
  env STATE_FILE="$FIXTURES/state_idle.json" \
      ISSUES_FILE="$FIXTURES/issues_idle.json" \
      CURRENT_TIME_OVERRIDE="2026-10-13T17:35:00Z" \
      "$PRECHECK"

# 2. Spend exceeded (> 30 USD) -> Exit 1 (SKIP)
run_test "Billed spend over 30 USD skips" 1 "exceeds 30.00 USD cap" \
  env STATE_FILE="$FIXTURES/state_spend_exceeded.json" \
      ISSUES_FILE="$FIXTURES/issues_idle.json" \
      CURRENT_TIME_OVERRIDE="2026-10-13T17:35:00Z" \
      "$PRECHECK"

# 2b. 32 USD halt state flagged -> Exit 1 (SKIP)
run_test "32 USD halt state flagged skips" 1 "32 USD halt state is flagged" \
  env STATE_FILE="$FIXTURES/state_halted.json" \
      ISSUES_FILE="$FIXTURES/issues_idle.json" \
      CURRENT_TIME_OVERRIDE="2026-10-13T17:35:00Z" \
      "$PRECHECK"

# 2c. The filing stop is 30.00 USD: 29.99 and 30.00 run, 30.01 skips, and the old 21 USD line is gone
spend_state() {
  local billed="$1" file
  file="$(mktemp -t precheck-spend-XXXXXX.json)"
  jq --argjson b "$billed" '.cost.billing.billed_usd = $b' "$FIXTURES/state_idle.json" > "$file"
  echo "$file"
}
for billed in 21.50 29.99 30.00; do
  spend_file="$(spend_state "$billed")"
  run_test "Billed spend $billed USD runs" 0 "RUN: pipeline idle" \
    env STATE_FILE="$spend_file" \
        ISSUES_FILE="$FIXTURES/issues_idle.json" \
        CURRENT_TIME_OVERRIDE="2026-10-13T17:35:00Z" \
        "$PRECHECK"
  rm -f "$spend_file"
done
spend_file="$(spend_state 30.01)"
run_test "Billed spend 30.01 USD skips" 1 "exceeds 30.00 USD cap" \
  env STATE_FILE="$spend_file" \
      ISSUES_FILE="$FIXTURES/issues_idle.json" \
      CURRENT_TIME_OVERRIDE="2026-10-13T17:35:00Z" \
      "$PRECHECK"
rm -f "$spend_file"
# Ledger spend at the 32 USD halt line also stops it, whatever the bill says
halt_file="$(mktemp -t precheck-halt-XXXXXX.json)"
jq '.cost.totals = {"usd": 32.0}' "$FIXTURES/state_idle.json" > "$halt_file"
run_test "Ledger spend at the 32 USD halt line skips" 1 "32 USD halt state is flagged" \
  env STATE_FILE="$halt_file" \
      ISSUES_FILE="$FIXTURES/issues_idle.json" \
      CURRENT_TIME_OVERRIDE="2026-10-13T17:35:00Z" \
      "$PRECHECK"
rm -f "$halt_file"

# 2d. A bill that is missing, null or not a plain number is unknown, never 0 USD: the run is skipped
billed_state() {
  local filter="$1" file
  file="$(mktemp -t precheck-billed-XXXXXX.json)"
  jq "$filter" "$FIXTURES/state_idle.json" > "$file"
  echo "$file"
}
for filter in \
  'del(.cost.billing) | del(.cost.totals.billed_usd)' \
  '.cost.billing = null' \
  '.cost.billing.billed_usd = null' \
  '.cost.billing.billed_usd = "n/a"' \
  '.cost.billing.billed_usd = -1'; do
  unknown_file="$(billed_state "$filter")"
  run_test "Unknown billed spend skips: $filter" 1 "SKIP: billed spend unknown" \
    env STATE_FILE="$unknown_file" \
        ISSUES_FILE="$FIXTURES/issues_idle.json" \
        CURRENT_TIME_OVERRIDE="2026-10-13T17:35:00Z" \
        "$PRECHECK"
  rm -f "$unknown_file"
done
# The older totals field still counts when the billing block is absent
fallback_file="$(billed_state 'del(.cost.billing) | .cost.totals.billed_usd = 13.02')"
run_test "Billed spend read from totals when billing is absent runs" 0 "RUN: pipeline idle" \
  env STATE_FILE="$fallback_file" \
      ISSUES_FILE="$FIXTURES/issues_idle.json" \
      CURRENT_TIME_OVERRIDE="2026-10-13T17:35:00Z" \
      "$PRECHECK"
rm -f "$fallback_file"

# 3. State file missing -> Exit 1 (SKIP)
run_test "Missing state.json skips" 1 "state.json is missing" \
  env STATE_FILE="$FIXTURES/non_existent_state.json" \
      ISSUES_FILE="$FIXTURES/issues_idle.json" \
      CURRENT_TIME_OVERRIDE="2026-10-13T17:35:00Z" \
      "$PRECHECK"

# 4. State stale limit checks
# State at 35 min old should run successfully under 45 min limit (exceeds old 30 min limit)
run_test "State 35 min old (under 45 min limit) runs successfully" 0 "RUN: pipeline idle" \
  env STATE_FILE="$FIXTURES/state_stale.json" \
      ISSUES_FILE="$FIXTURES/issues_idle.json" \
      CURRENT_TIME_OVERRIDE="2026-10-13T16:35:00Z" \
      "$PRECHECK"

run_test "Stale state.json over 45 min skips" 1 "exceeds 45 min limit" \
  env STATE_FILE="$FIXTURES/state_stale.json" \
      ISSUES_FILE="$FIXTURES/issues_idle.json" \
      CURRENT_TIME_OVERRIDE="2026-10-13T16:50:00Z" \
      "$PRECHECK"

# 5. Busy state with building issue and no escalations -> Exit 1 (SKIP)
run_test "Busy stage:building with no escalations skips" 1 "pipeline is busy" \
  env STATE_FILE="$FIXTURES/state_idle.json" \
      ISSUES_FILE="$FIXTURES/issues_busy.json" \
      CURRENT_TIME_OVERRIDE="2026-10-13T17:35:00Z" \
      "$PRECHECK"

# 6. Busy state BUT open escalation exists -> Exit 0 (RUN)
run_test "Busy state with open escalation runs (answering is the point)" 0 "RUN: open escalation needs response" \
  env STATE_FILE="$FIXTURES/state_idle.json" \
      ISSUES_FILE="$FIXTURES/issues_busy_with_escalation.json" \
      CURRENT_TIME_OVERRIDE="2026-10-13T17:35:00Z" \
      "$PRECHECK"

# 7. Open refinement question exists -> Exit 0 (RUN)
run_test "Open refinement question runs" 0 "RUN: requirements question needs response" \
  env STATE_FILE="$FIXTURES/state_idle.json" \
      ISSUES_FILE="$FIXTURES/issues_refinement.json" \
      CURRENT_TIME_OVERRIDE="2026-10-13T17:35:00Z" \
      "$PRECHECK"

# 8. Daily issue cap reached (6 in last 24h) -> Exit 1 (SKIP)
run_test "Daily issue cap of 6 reached skips" 1 "daily issue cap reached" \
  env STATE_FILE="$FIXTURES/state_idle.json" \
      ISSUES_FILE="$FIXTURES/issues_daily_cap.json" \
      CURRENT_TIME_OVERRIDE="2026-10-13T17:35:00Z" \
      "$PRECHECK"

# 9. agy quota exhausted -> Exit 1 (SKIP)
run_test "agy quota exhausted skips" 1 "agy quota is exhausted" \
  env AGY_QUOTA_EXHAUSTED=1 \
      STATE_FILE="$FIXTURES/state_idle.json" \
      ISSUES_FILE="$FIXTURES/issues_idle.json" \
      CURRENT_TIME_OVERRIDE="2026-10-13T17:35:00Z" \
      "$PRECHECK"

echo "----------------------------------------"
if [ "$failures" -gt 0 ]; then
  echo "FAILED: $failures of $total tests failed."
  exit 1
fi

echo "ALL $total TESTS PASSED."
exit 0
