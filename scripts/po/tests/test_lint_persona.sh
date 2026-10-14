#!/usr/bin/env bash
# Note: Linux-only test suite (relies on GNU coreutils).
#
# Mutation test suite for scripts/po/lint_persona.sh:
# 1. Valid persona passes
# 2. Rejects gh pr merge in allow-list
# 3. Rejects --admin in allow-list
# 4. Rejects --squash in allow-list
# 5. Rejects unauthorized gh pr command (gh pr close) in allow-list
# 6. Rejects git push in allow-list
# 7. Rejects bare cat in allow-list
# 8. Rejects missing author restriction line (only repo slug present)
# 9. Rejects missing 18 USD threshold
# 10. Rejects missing 22 USD threshold
# 11. Rejects missing 25 USD threshold
# 12. Rejects missing 3 USD threshold

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

# 9. Rejects missing 18 USD threshold
M9_CONTENT="${BASE_CONTENT/18.00 USD/19.00 USD}"
M9_CONTENT="${M9_CONTENT/18.00 USD/19.00 USD}"
run_mutation_test "Rejects missing 18 USD threshold" \
  "$M9_CONTENT" \
  "Guardrail \(e\)|18/22/25/3"

# 10. Rejects missing 22 USD threshold
M10_CONTENT="${BASE_CONTENT//22.00 USD/20.00 USD}"
run_mutation_test "Rejects missing 22 USD threshold" \
  "$M10_CONTENT" \
  "Guardrail \(e\)|18/22/25/3"

# 11. Rejects missing 25 USD threshold
M11_CONTENT="${BASE_CONTENT/25.00 USD/30.00 USD}"
run_mutation_test "Rejects missing 25 USD threshold" \
  "$M11_CONTENT" \
  "Guardrail \(e\)|18/22/25/3"

# 12. Rejects missing 3 USD threshold
M12_CONTENT="${BASE_CONTENT/3.00 USD/5.00 USD}"
run_mutation_test "Rejects missing 3 USD threshold" \
  "$M12_CONTENT" \
  "Guardrail \(e\)|18/22/25/3"

echo "----------------------------------------"
if [ "$failures" -gt 0 ]; then
  echo "FAILED: $failures of $total tests failed."
  exit 1
fi

echo "ALL $total LINT_PERSONA MUTATION TESTS PASSED."
exit 0
