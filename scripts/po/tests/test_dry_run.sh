#!/usr/bin/env bash
# Note: Linux-only test suite (relies on GNU coreutils).
#
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
# 10. fewer than 5 items remaining: logs request, files next item, no roadmap issue
# 11. issue 72 shaped real: handles agent-error, comments findings, closes issue
# 12. issue 72 already answered: detects marker, skips with zero commands
# 13. real gh JSON with uppercase CLOSED state ignores closed issues
# 14. roadmap item already filed skips to next unblocked ready item
# 15. missing simulated-human label logs BLOCKED and plans no commands
# 16. memory mentions under rejected or themes are ignored; filed state comes from GitHub
# 17. explicit command line options execute hermetically
# 18. answered build-failed issue plans close only without second comment
# 19. stranger marker comment does not silence persona and plans answer and close
# 20. stranger roadmap issue is ignored and does not skip roadmap item

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
  "po-answered:v1"

# 4. not-agent-suitable escalation: reframes or closes with rationale
run_dry_test "not-agent-suitable escalation reframed/closed" \
  "\"$FIXTURES/not_agent_suitable\"" \
  "gh issue close 63" \
  "gh pr create|gh pr merge" \
  "po-answered:v1"

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
  "po-answered:v1"

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

# 10. Fewer than 5 items remaining: logs request, files next item, no roadmap issue
run_dry_test "Fewer than 5 items remaining logs request and files next item" \
  "\"$FIXTURES/fewer_than_5\"" \
  "Roadmap extension requested: fewer than 5 todo items remaining" \
  "roadmap: extend" \
  "gh issue create --title \"feat\(web\): base layout\""

# 11. Issue 72 shaped real: handles agent-error, comments findings, closes issue
run_dry_test "Issue 72 shaped real is handled and closed with agent-error finding" \
  "\"$FIXTURES/issue_72_real\"" \
  "Handling agent-error escalation on issue #72" \
  "" \
  "gh issue close 72" \
  "po-answered:v1"

# 12. Issue 72 already answered: detects marker, skips with zero commands
run_dry_test "Issue 72 already answered is skipped with zero commands" \
  "\"$FIXTURES/issue_72_answered\"" \
  "Skipping issue #72: already answered with po-answered marker" \
  "gh issue comment 72|gh issue close 72" \
  "\(No commands to execute\)"

# 13. Real gh JSON with uppercase CLOSED state ignores closed issues
run_dry_test "Real gh JSON casing ignores closed issues and picks unblocked item" \
  "\"$FIXTURES/real_gh_json\"" \
  "gh issue create --title \"feat\(web\): secondary widget\"" \
  "gh issue close 51|gh issue close 52" \
  "ITEM-002"

# 14. Roadmap item already filed: skips to next ready unblocked item
run_dry_test "Roadmap item already filed skips to next unblocked item" \
  "\"$FIXTURES/dedupe_skip\"" \
  "gh issue create --title \"feat\(web\): filter dropdown component\"" \
  "gh issue create --title \"feat\(web\): base layout\"|gh issue create --title \"feat\(web\): secondary layout widget\"" \
  "Roadmap item: ITEM-003"

# 15. Missing simulated-human label logs BLOCKED and plans no commands
run_dry_test "Missing simulated-human label logs BLOCKED and plans no commands" \
  "\"$FIXTURES/labels_missing\"" \
  "BLOCKED: label simulated-human missing, maintainer must create it" \
  "gh label create" \
  "\(No commands to execute\)"

# 16. Memory mentions under rejected are ignored; filed state comes from GitHub
run_dry_test "Memory mentions under rejected are ignored and filed state comes from GitHub" \
  "--state \"$FIXTURES/memory_rejected/state.json\" --issues \"$FIXTURES/memory_rejected/issues.json\" --roadmap \"$FIXTURES/memory_rejected/roadmap.md\" --memory \"$FIXTURES/memory_rejected/memory.md\"" \
  "gh issue create --title \"feat\(web\): base layout\"" \
  "" \
  "Roadmap item: ITEM-001"

# 17. Explicit command line flags execute hermetically
run_dry_test "Explicit command line flags execute hermetically" \
  "--state \"$FIXTURES/fewer_than_5/state.json\" --issues \"$FIXTURES/fewer_than_5/issues.json\" --roadmap \"$FIXTURES/fewer_than_5/roadmap.md\"" \
  "Roadmap extension requested" \
  "roadmap: extend" \
  "gh issue create --title \"feat\(web\): base layout\""

# 18. Answered build-failed issue plans close only without second comment
run_dry_test "Answered build-failed issue plans close only without second comment" \
  "\"$FIXTURES/build_failed_answered\"" \
  "gh issue close 70" \
  "gh issue comment" \
  "was answered with po-answered marker but remains open"

# 19. Stranger marker comment on issue 72 does not silence persona
run_dry_test "Stranger marker comment does not silence persona and plans answer and close" \
  "\"$FIXTURES/stranger_marker\"" \
  "gh issue comment 72" \
  "" \
  "gh issue close 72"

# 20. Stranger roadmap issue is ignored and does not skip item
run_dry_test "Stranger roadmap issue is ignored and does not skip item" \
  "\"$FIXTURES/stranger_roadmap_issue\"" \
  "gh issue create --title \"feat\(web\): base layout\"" \
  "gh issue create --title \"feat\(web\): clear search query button\"" \
  "Roadmap item: ITEM-001"

# 21. Roadmap item with Visible Surface generates ## Visible surface in issue body
tmp_visible_dir="$(mktemp -d "${TMPDIR:-/tmp}/dry_vis.XXXXXX")"
cp "$FIXTURES/idle_with_roadmap/state.json" "$tmp_visible_dir/state.json"
cp "$FIXTURES/idle_with_roadmap/issues.json" "$tmp_visible_dir/issues.json"
cat > "$tmp_visible_dir/roadmap.md" << 'EOF'
# Roadmap
### ITEM-001: feat(web): hero banner
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, high-visibility
- **Visible Surface**: home
- **Gap Anchor**: `app/web/src/pages/HomePage.tsx#L29`. Hero banner gap.
- **User Value**: Engaging hero banner.
- **Files Touched**:
  - `app/web/src/pages/HomePage.tsx`
- **Acceptance Criteria**:
  1. The home hero renders an official brand badge.
  2. The ui-proof screenshot for home surface differs from previous release with test id brand-badge.
EOF
run_dry_test "Roadmap item with Visible Surface generates visible surface section" \
  "\"$tmp_visible_dir\"" \
  "## Visible surface" \
  "" \
  "Roadmap item: ITEM-001"
rm -rf "$tmp_visible_dir"

# 22. Halt state flagged stops Hat 4 intake with zero commands
tmp_halt_dir="$(mktemp -d -t dry-run-halt-XXXXXX)"
cp "$FIXTURES/idle_with_roadmap/roadmap.md" "$tmp_halt_dir/roadmap.md"
cp "$FIXTURES/idle_with_roadmap/issues.json" "$tmp_halt_dir/issues.json"
cat > "$tmp_halt_dir/state.json" << 'EOF'
{
  "version": 1,
  "cost": {
    "billing": { "billed_usd": 15.00 },
    "caps": { "halt_usd": 22.0, "issue_usd": 3.0, "total_usd": 25.0 },
    "totals": { "halted": true }
  }
}
EOF
run_dry_test "22 USD halt state flagged stops Hat 4 intake" \
  "\"$tmp_halt_dir\"" \
  "22 USD halt state is flagged. Intake stopped." \
  "gh issue create"
rm -rf "$tmp_halt_dir"

# 23. Billed spend over 21 USD stops Hat 4 intake with zero commands
tmp_spend_dir="$(mktemp -d -t dry-run-spend-XXXXXX)"
cp "$FIXTURES/idle_with_roadmap/roadmap.md" "$tmp_spend_dir/roadmap.md"
cp "$FIXTURES/idle_with_roadmap/issues.json" "$tmp_spend_dir/issues.json"
cat > "$tmp_spend_dir/state.json" << 'EOF'
{
  "version": 1,
  "cost": {
    "billing": { "billed_usd": 21.50 },
    "caps": { "halt_usd": 22.0, "issue_usd": 3.0, "total_usd": 25.0 },
    "totals": { "halted": false }
  }
}
EOF
run_dry_test "Billed spend over 21 USD stops Hat 4 intake" \
  "\"$tmp_spend_dir\"" \
  "exceeds 21.00 USD cap. Intake stopped." \
  "gh issue create"
rm -rf "$tmp_spend_dir"

echo "----------------------------------------"
if [ "$failures" -gt 0 ]; then
  echo "FAILED: $failures of $total tests failed."
  exit 1
fi

echo "ALL $total DRY-RUN SCENARIO TESTS PASSED."
exit 0
