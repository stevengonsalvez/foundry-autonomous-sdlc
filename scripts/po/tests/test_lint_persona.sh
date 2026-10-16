#!/usr/bin/env bash
# Note: Linux-only test suite (relies on GNU coreutils).
#
# Mutation test suite for scripts/po/lint_persona.sh:
# 1. Valid persona passes (30 USD accepted)
# 2. Rejects gh pr merge in allow-list
# 3. Rejects --admin in allow-list
# 4. Rejects --squash in allow-list
# 5. Rejects unauthorized gh pr command (gh pr close) in allow-list
# 6. Rejects git push in allow-list
# 7. Rejects bare cat in allow-list
# 8. Rejects missing author restriction line (only repo slug present)
# 9. Rejects missing 30 USD threshold
# 10-15. Rejects 18, 21, 22, 25, 32 and 35 USD as filing stop (21, 22 and 25 are the retired caps)
# 16. Rejects missing 32 halt state stop rule
# 17. Rejects missing 32 USD threshold
# 18. Rejects missing 35 USD threshold
# 19. Rejects a stale 22 USD halt line
# 20. Rejects missing 3 USD threshold
# 21. Rejects missing visible surface requirement
# 22. Rejects missing ui-proof screenshot diff rule
# 23. Rejects missing highest-visibility preference rule
# 24. Rejects re-filing on a merge-conflict escalation
# 25. Rejects a missing merge-conflict rule
# 26. Rejects closing or re-filing an agent-quota escalation
# 27. Rejects a missing agent-quota rule
# 28. Rejects an agent-error close without the not planned reason
# 29. Rejects the retired out of roadmap scope wording

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

# 9. Rejects missing 30 USD threshold
M9_CONTENT="${BASE_CONTENT/30.00 USD/19.00 USD}"
M9_CONTENT="${M9_CONTENT/30.00 USD/19.00 USD}"
run_mutation_test "Rejects missing 30 USD threshold" \
  "$M9_CONTENT" \
  "Guardrail \(e\)|30/32/35/3"

# 10-12. Rejects every other value as the filing stop, the old 21, 22 and 25 included
for stop in 18 21 22 25 32 35; do
  M_CONTENT="${BASE_CONTENT/30.00 USD precheck threshold/$stop.00 USD precheck threshold}"
  M_CONTENT="${M_CONTENT/spend is under 30.00 USD/spend is under $stop.00 USD}"
  run_mutation_test "Rejects $stop USD as filing stop" \
    "$M_CONTENT" \
    "Guardrail \(e\)|reject 18/21/22/25/32/35 as filing stop"
done

# 13. Rejects missing 32 halt state stop rule
M13_CONTENT="${BASE_CONTENT/Hard rule: The PO must also stop when the 32.00 USD halt state is flagged./}"
M13_CONTENT="${M13_CONTENT/Hard rule: The 32.00 USD halt state is not flagged./}"
run_mutation_test "Rejects missing 32 halt state stop rule" \
  "$M13_CONTENT" \
  "Guardrail \(e\)|require stopping when 32 halt state is flagged"

# 14. Rejects missing 32 USD threshold
M14_CONTENT="${BASE_CONTENT//32.00 USD/20.00 USD}"
run_mutation_test "Rejects missing 32 USD threshold" \
  "$M14_CONTENT" \
  "Guardrail \(e\)|30/32/35/3"

# 15. Rejects missing 35 USD threshold
M15_CONTENT="${BASE_CONTENT/35.00 USD/40.00 USD}"
run_mutation_test "Rejects missing 35 USD threshold" \
  "$M15_CONTENT" \
  "Guardrail \(e\)|30/32/35/3"

# 15b. Rejects the old 22 USD halt line left in the persona
M15B_CONTENT="${BASE_CONTENT/32.00 USD hard pipeline halt/22.00 USD hard pipeline halt}"
run_mutation_test "Rejects a stale 22 USD halt line" \
  "$M15B_CONTENT" \
  "Guardrail \(e\)|reject 18/21/22/25/32/35 as filing stop"

# 16. Rejects missing 3 USD threshold
M16_CONTENT="${BASE_CONTENT/3.00 USD/5.00 USD}"
run_mutation_test "Rejects missing 3 USD threshold" \
  "$M16_CONTENT" \
  "Guardrail \(e\)|30/32/35/3"

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

# 22. Rejects a persona that closes agent-quota escalations
M22_CONTENT="${BASE_CONTENT//[Dd]o not close or re-file/close it}"
run_mutation_test "Rejects closing or re-filing an agent-quota escalation" \
  "$M22_CONTENT" \
  "Guardrail \(k\)|agent-quota"

# 23. Rejects a persona with no agent-quota rule
M23_CONTENT="${BASE_CONTENT//escalated:agent-quota/escalated:other}"
run_mutation_test "Rejects a missing agent-quota rule" \
  "$M23_CONTENT" \
  "Guardrail \(k\)|agent-quota"

# 24. Rejects an agent-error close without the not planned reason
M24_CONTENT="${BASE_CONTENT//--reason \"not planned\"/}"
run_mutation_test "Rejects an agent-error close without the not planned reason" \
  "$M24_CONTENT" \
  "Guardrail \(l\)|not planned"

# 25. Rejects the retired out of roadmap scope wording
M25_CONTENT="${BASE_CONTENT}
Work is dropped as out of roadmap scope."
run_mutation_test "Rejects the retired out of roadmap scope wording" \
  "$M25_CONTENT" \
  "Guardrail \(l\)|out of roadmap scope"

echo "----------------------------------------"
if [ "$failures" -gt 0 ]; then
  echo "FAILED: $failures of $total tests failed."
  exit 1
fi

echo "ALL $total LINT_PERSONA MUTATION TESTS PASSED."
exit 0
