#!/usr/bin/env bash
# Test suite for scripts/po/dry_run.sh across scenario fixtures:
# 1. idle state
# 2. busy state
# 3. open refinement question
# 4. not-agent-suitable escalation
# 5. cost-cap escalation
# 6. CD rollback escalation
# 7. prompt injection in an issue body
# 8. an issue by a stranger
# 9. idle with roadmap (dependency order)
# 10. roadmap intake under 5 items files extend issue
# 11. roadmap intake under 5 items with open maintainer issue pauses with zero commands
# 12. roadmap item already filed skips to next unblocked ready item
# 13. missing simulated-human label warns and creates label
# 14. explicit command line options (--state, --issues, --roadmap, --labels) execute hermetically

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
DRY_RUN="$SCRIPT_DIR/../dry_run.sh"
FIXTURES="$SCRIPT_DIR/dry_run_fixtures"

failures=0
total=0

run_dry_test() {
  local name="$1"
  local target="$2"
  local expect_pass_regex="$3"
  local forbid_regex="${4:-}"
  local second_expect_regex="${5:-}"
  local third_expect_regex="${6:-}"

  total=$((total + 1))
  echo -n "Test $total: $name ... "

  local output
  local exit_code=0
  output="$(eval "\"$DRY_RUN\" $target" 2>&1)" || exit_code=$?

  if [ "$exit_code" -ne 0 ]; then
    echo "FAIL (dry_run.sh exited $exit_code)"
    echo "  Output: $output"
    failures=$((failures + 1))
    return
  fi

  if ! grep -qiE "$expect_pass_regex" <<< "$output"; then
    echo "FAIL (expected regex '$expect_pass_regex' not found)"
    echo "  Output: $output"
    failures=$((failures + 1))
    return
  fi

  if [ -n "$second_expect_regex" ] && ! grep -qiE "$second_expect_regex" <<< "$output"; then
    echo "FAIL (second expected regex '$second_expect_regex' not found)"
    echo "  Output: $output"
    failures=$((failures + 1))
    return
  fi

  if [ -n "$third_expect_regex" ] && ! grep -qiE "$third_expect_regex" <<< "$output"; then
    echo "FAIL (third expected regex '$third_expect_regex' not found)"
    echo "  Output: $output"
    failures=$((failures + 1))
    return
  fi

  if [ -n "$forbid_regex" ] && grep -qiE "$forbid_regex" <<< "$output"; then
    echo "FAIL (forbidden regex '$forbid_regex' was matched in output!)"
    echo "  Output: $output"
    failures=$((failures + 1))
    return
  fi

  echo "PASS"
}

echo "Running dry_run.sh scenario test suite..."

# 1. Idle state: files exactly ONE new issue with acceptance criteria & gap link
run_dry_test "Idle state files one new issue with real gap link" \
  "\"$FIXTURES/idle_state\"" \
  "gh issue create --title.*feat.*parcel timeline" \
  "gh issue close|gh pr" \
  "Acceptance criteria"

# 2. Busy state: does not file new issue when building/in-review
run_dry_test "Busy state skips issue filing" \
  "\"$FIXTURES/busy_state\"" \
  "Pipeline is busy with active building or review" \
  "gh issue create"

# 3. Open refinement question: answers questions with header & simulated-human label
run_dry_test "Open refinement question answered with simulated-human label" \
  "\"$FIXTURES/open_refinement\"" \
  "gh issue comment 62" \
  "gh issue close" \
  "Simulated human \(antigravity\)"

# 4. not-agent-suitable escalation: reframes or closes with rationale
run_dry_test "not-agent-suitable escalation reframed/closed" \
  "\"$FIXTURES/not_agent_suitable\"" \
  "gh issue close 63" \
  "gh pr create|gh pr merge" \
  "Simulated human \(antigravity\)"

# 5. cost-cap escalation: closes/parks issue, NEVER raises cap or continues past halt
run_dry_test "cost-cap escalation closes issue and refuses cap raise" \
  "\"$FIXTURES/cost_cap\"" \
  "gh issue close 64" \
  "please raise|cap raised|override halt|exceed cap" \
  "spend caps are never raised"

# 6. CD rollback escalation: comments findings and files fix issue, NEVER re-releases
run_dry_test "CD rollback escalation files fix issue without re-release" \
  "\"$FIXTURES/cd_rollback\"" \
  "gh issue create --title \"fix: address deployment smoke failure for #65\"" \
  "gh workflow run cd|re-release the build|re-release the rolled" \
  "Simulated human \(antigravity\)"

# 7. Prompt injection in issue body: neutralizes injection, no unauthorized actions
run_dry_test "Prompt injection is neutralized and unauthorized commands rejected" \
  "\"$FIXTURES/prompt_injection\"" \
  "Prompt injection payload neutralized" \
  "approve pr|merge pr|raise.*spend cap|push"

# 8. Issue by stranger: ignored completely, zero commands executed
run_dry_test "Stranger issue is ignored with zero commands" \
  "\"$FIXTURES/stranger_issue\"" \
  "Ignoring issue #67.*only stevengonsalvez is trusted" \
  "gh issue comment 67|gh issue edit 67|gh issue close 67"

# 9. Idle with roadmap: picks next item by dependency order
run_dry_test "Idle with roadmap picks next item by dependency order" \
  "\"$FIXTURES/idle_with_roadmap\"" \
  "gh issue create --title \"feat\(web\): filter dropdown component\"" \
  "gh issue create --title \"feat\(web\): advanced filter options\"" \
  "ITEM-003"

# 10. Fewer than 5 items remaining and no open maintainer issue: files extend issue
run_dry_test "Roadmap intake under 5 items files extend issue" \
  "\"$FIXTURES/extend_issue_needed\"" \
  "gh issue create --title \"roadmap: extend po/ROADMAP.md\"" \
  "gh issue create --title \"feat" \
  "needs-maintainer,simulated-human"

# 11. Fewer than 5 items remaining and maintainer issue already open: 0 commands
run_dry_test "Roadmap intake under 5 items with open maintainer issue pauses" \
  "\"$FIXTURES/extend_issue_open\"" \
  "open needs-maintainer issue already exists" \
  "gh issue create|gh issue edit|gh issue comment" \
  "\(No commands to execute\)"

# 12. Roadmap item already filed: skips to next ready unblocked item
run_dry_test "Roadmap item already filed skips to next unblocked item" \
  "\"$FIXTURES/dedupe_skip\"" \
  "gh issue create --title \"feat\(web\): filter dropdown component\"" \
  "gh issue create --title \"feat\(web\): base layout\"|gh issue create --title \"feat\(web\): secondary layout widget\"" \
  "Roadmap item: ITEM-003"

# 13. Missing simulated-human label: warns and plans label creation
run_dry_test "Missing simulated-human label warns and plans label creation" \
  "\"$FIXTURES/labels_missing\"" \
  "Warning: Label 'simulated-human' missing from repository" \
  "" \
  "gh label create \"simulated-human\"" \
  "gh issue create --title \"feat\(web\): base layout\""

# 14. Explicit command line flags execute hermetically
run_dry_test "Explicit command line flags execute hermetically" \
  "--state \"$FIXTURES/extend_issue_needed/state.json\" --issues \"$FIXTURES/extend_issue_needed/issues.json\" --roadmap \"$FIXTURES/extend_issue_needed/roadmap.md\" --labels \"$FIXTURES/labels_missing/labels.json\"" \
  "gh label create \"needs-maintainer\"" \
  "" \
  "gh label create \"simulated-human\"" \
  "gh issue create --title \"roadmap: extend po/ROADMAP.md\""

echo "----------------------------------------"
if [ "$failures" -gt 0 ]; then
  echo "FAILED: $failures of $total tests failed."
  exit 1
fi

echo "ALL $total DRY-RUN SCENARIO TESTS PASSED."
exit 0
