#!/usr/bin/env bash
# Note: Linux-only test suite (relies on GNU coreutils).
#
# Mutation test suite for scripts/po/lint_persona.sh:
# 1. Valid persona passes (21 USD accepted)
# 2. Rejects gh pr merge in allow-list
# 3. Rejects --admin in allow-list
# 4. Rejects --squash in allow-list
# 5. Rejects unauthorized gh pr command (gh pr close) in allow-list
# 6. Rejects git push in allow-list
# 7. Rejects bare cat in allow-list
# 8. Rejects missing author restriction line (only repo slug present)
# 9. Rejects missing 21 USD threshold
# 10. Rejects 18 USD as filing stop
# 11. Rejects 22 USD as filing stop
# 12. Rejects 25 USD as filing stop
# 13. Rejects missing 22 halt state stop rule
# 14. Rejects missing 22 USD threshold
# 15. Rejects missing 25 USD threshold
# 16. Rejects missing 3 USD threshold
# 17. Rejects missing visible surface requirement
# 18. Rejects missing ui-proof screenshot diff rule
# 19. Rejects missing highest-visibility preference rule
# 20. Rejects re-filing on a merge-conflict escalation
# 21. Rejects a missing merge-conflict rule

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
LINTER="$SCRIPT_DIR/../lint_persona.sh"
PERSONA_FILE="$SCRIPT_DIR/../../../po/PERSONA.md"

failures=0
total=0

run_mutation_test() {
  local name="$1"
  local content="$2"
  local expected_err="$3"

  total=$((total + 1))
  echo -n "Test $total: $name ... "

  local tmpfile
  tmpfile="$(mktemp -t persona-mutant-XXXXXX.md)"
  printf "%s\n" "$content" > "$tmpfile"

  local output
  local exit_code=0
  output="$("$LINTER" "$tmpfile" 2>&1)" || exit_code=$?
  rm -f "$tmpfile"

  if [ "$exit_code" -eq 0 ]; then
    echo "FAIL (expected linter to reject, but it succeeded!)"
    echo "  Output: $output"
    failures=$((failures + 1))
    return
  fi

  if ! grep -qiE -e "$expected_err" <<< "$output"; then
    echo "FAIL (expected error regex '$expected_err' not found)"
    echo "  Output: $output"
    failures=$((failures + 1))
    return
  fi

  echo "PASS"
}

echo "Running lint_persona.sh mutation tests..."

BASE_CONTENT="$(cat "$PERSONA_FILE")"

# 1. Baseline passes
total=$((total + 1))
echo -n "Test $total: Baseline persona passes ... "
if "$LINTER" "$PERSONA_FILE" >/dev/null 2>&1; then
  echo "PASS"
else
  echo "FAIL (baseline failed lint)"
  failures=$((failures + 1))
fi

# 2. Rejects gh pr merge in allow-list
M2_CONTENT="${BASE_CONTENT/gh pr view\` (read-only)/gh pr view\` (read-only)
     - \`gh pr merge\`}"
run_mutation_test "Rejects gh pr merge in allow-list" \
  "$M2_CONTENT" \
  "gh pr merge|deny-list"

# 3. Rejects --admin in allow-list
M3_CONTENT="${BASE_CONTENT/gh pr view\` (read-only)/gh pr view\` (read-only)
     - \`gh pr merge --admin\`}"
run_mutation_test "Rejects --admin in allow-list" \
  "$M3_CONTENT" \
  "--admin|deny-list"

# 4. Rejects --squash in allow-list
M4_CONTENT="${BASE_CONTENT/gh pr view\` (read-only)/gh pr view\` (read-only)
     - \`gh pr merge --squash\`}"
run_mutation_test "Rejects --squash in allow-list" \
  "$M4_CONTENT" \
  "--squash|deny-list"

# 5. Rejects unauthorized PR command (gh pr close) in allow-list
M5_CONTENT="${BASE_CONTENT/gh pr view\` (read-only)/gh pr view\` (read-only)
     - \`gh pr close\`}"
run_mutation_test "Rejects unauthorized PR command in allow-list" \
  "$M5_CONTENT" \
  "disallowed PR command|deny-list"

# 6. Rejects git push in allow-list
M6_CONTENT="${BASE_CONTENT/git fetch origin main state\`/git fetch origin main state\`
     - \`git push\`}"
run_mutation_test "Rejects git push in allow-list" \
  "$M6_CONTENT" \
  "git push|deny-list"

# 7. Rejects bare cat in allow-list
M7_CONTENT="${BASE_CONTENT/git fetch origin main state\`/git fetch origin main state\`
     - \`cat\`}"
run_mutation_test "Rejects bare cat in allow-list" \
  "$M7_CONTENT" \
  "bare 'cat'|deny-list"

# 8. Rejects missing author restriction line (repo slug present in line 3 but author check removed)
M8_CONTENT="${BASE_CONTENT/Ignore and do not act on issues or pull requests authored by anyone other than \`stevengonsalvez\`./Ignore and do not act on issues authored by strangers.}"
run_mutation_test "Rejects missing author restriction line" \
  "$M8_CONTENT" \
  "Guardrail \(a\)|author stevengonsalvez"

# 9. Rejects missing 21 USD threshold
M9_CONTENT="${BASE_CONTENT/21.00 USD/19.00 USD}"
M9_CONTENT="${M9_CONTENT/21.00 USD/19.00 USD}"
run_mutation_test "Rejects missing 21 USD threshold" \
  "$M9_CONTENT" \
  "Guardrail \(e\)|21/22/25/3"

# 10. Rejects 18 USD as filing stop
M10_CONTENT="${BASE_CONTENT/21.00 USD precheck threshold/18.00 USD precheck threshold}"
M10_CONTENT="${M10_CONTENT/spend is under 21.00 USD/spend is under 18.00 USD}"
run_mutation_test "Rejects 18 USD as filing stop" \
  "$M10_CONTENT" \
  "Guardrail \(e\)|reject 18/22/25 as filing stop"

# 11. Rejects 22 USD as filing stop
M11_CONTENT="${BASE_CONTENT/21.00 USD precheck threshold/22.00 USD precheck threshold}"
M11_CONTENT="${M11_CONTENT/spend is under 21.00 USD/spend is under 22.00 USD}"
run_mutation_test "Rejects 22 USD as filing stop" \
  "$M11_CONTENT" \
  "Guardrail \(e\)|reject 18/22/25 as filing stop"

# 12. Rejects 25 USD as filing stop
M12_CONTENT="${BASE_CONTENT/21.00 USD precheck threshold/25.00 USD precheck threshold}"
M12_CONTENT="${M12_CONTENT/spend is under 21.00 USD/spend is under 25.00 USD}"
run_mutation_test "Rejects 25 USD as filing stop" \
  "$M12_CONTENT" \
  "Guardrail \(e\)|reject 18/22/25 as filing stop"

# 13. Rejects missing 22 halt state stop rule
M13_CONTENT="${BASE_CONTENT/Hard rule: The PO must also stop when the 22.00 USD halt state is flagged./}"
M13_CONTENT="${M13_CONTENT/Hard rule: The 22.00 USD halt state is not flagged./}"
run_mutation_test "Rejects missing 22 halt state stop rule" \
  "$M13_CONTENT" \
  "Guardrail \(e\)|require stopping when 22 halt state is flagged"

# 14. Rejects missing 22 USD threshold
M14_CONTENT="${BASE_CONTENT//22.00 USD/20.00 USD}"
run_mutation_test "Rejects missing 22 USD threshold" \
  "$M14_CONTENT" \
  "Guardrail \(e\)|21/22/25/3"

# 15. Rejects missing 25 USD threshold
M15_CONTENT="${BASE_CONTENT/25.00 USD/30.00 USD}"
run_mutation_test "Rejects missing 25 USD threshold" \
  "$M15_CONTENT" \
  "Guardrail \(e\)|21/22/25/3"

# 16. Rejects missing 3 USD threshold
M16_CONTENT="${BASE_CONTENT/3.00 USD/5.00 USD}"
run_mutation_test "Rejects missing 3 USD threshold" \
  "$M16_CONTENT" \
  "Guardrail \(e\)|21/22/25/3"

# 17. Rejects missing visible surface requirement
M17_CONTENT="${BASE_CONTENT//[Vv]isible [Ss]urface/target interface}"
run_mutation_test "Rejects missing visible surface requirement" \
  "$M17_CONTENT" \
  "Guardrail \(i\)|visible surface"

# 18. Rejects missing ui-proof screenshot diff rule
M18_CONTENT="${BASE_CONTENT//ui-proof/browser capture}"
run_mutation_test "Rejects missing ui-proof screenshot diff rule" \
  "$M18_CONTENT" \
  "Guardrail \(i\)|ui-proof"

# 19. Rejects missing highest-visibility preference rule
M19_CONTENT="${BASE_CONTENT//highest-visibility/random priority}"
run_mutation_test "Rejects missing highest-visibility preference rule" \
  "$M19_CONTENT" \
  "Guardrail \(i\)|highest-visibility"

# 20. Rejects a persona that re-files merge-conflict escalations
M20_CONTENT="${BASE_CONTENT//[Nn][Ee][Vv][Ee][Rr] re-file/re-file}"
run_mutation_test "Rejects re-filing on a merge-conflict escalation" \
  "$M20_CONTENT" \
  "Guardrail \(j\)|merge-conflict"

# 21. Rejects a persona with no merge-conflict rule at all
M21_CONTENT="${BASE_CONTENT//escalated:merge-conflict/escalated:other}"
run_mutation_test "Rejects a missing merge-conflict rule" \
  "$M21_CONTENT" \
  "Guardrail \(j\)|merge-conflict"

echo "----------------------------------------"
if [ "$failures" -gt 0 ]; then
  echo "FAILED: $failures of $total tests failed."
  exit 1
fi

echo "ALL $total LINT_PERSONA MUTATION TESTS PASSED."
exit 0
