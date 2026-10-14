#!/usr/bin/env bash
# Note: Linux-only test suite (relies on GNU mktemp --suffix and coreutils).
#
# Test suite for scripts/po/lint_roadmap.sh verifying that strict validation
# catches invalid roadmap mutations:
# 1. Path traversal: app/../.github/workflows/ci.yml
# 2. Path without backticks: - app/web/src/App.tsx
# 3. Invalid cost class: XXL
# 4. Incomplete acceptance criteria: '1. TBD'
# 5. Short acceptance criteria under 3 words: '1. Fix bug'
# 6. Malformed header without colon: '### ITEM-001 feat(web): test item'
# 7. Two paths on one Files Touched line: '  - `app/web/a.ts` `app/web/b.ts`'
# 8. Unindented non-app sibling line under Files Touched: '- non/app/file'
# 9. Invalid non-field line inside item block
# 10. TBD anywhere inside acceptance criteria text

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
LINTER="$SCRIPT_DIR/../lint_roadmap.sh"

failures=0
total=0

run_mutation_test() {
  local name="$1"
  local content="$2"
  local expected_err="$3"

  total=$((total + 1))
  echo -n "Test $total: $name ... "

  local tmpfile
  tmpfile="$(mktemp --suffix=.md)"
  echo "$content" > "$tmpfile"

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

  if ! grep -qiE "$expected_err" <<< "$output"; then
    echo "FAIL (expected error regex '$expected_err' not found)"
    echo "  Output: $output"
    failures=$((failures + 1))
    return
  fi

  echo "PASS"
}

BASE_VALID_ITEM='### ITEM-001: feat(web): test item
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: test
- **Gap Anchor**: `app/web/src/App.tsx#L1`.
- **User Value**: Test value.
- **Files Touched**:
  - `app/web/src/App.tsx`
- **Acceptance Criteria**:
  1. This is a valid acceptance criterion with more than three words.'

echo "Running lint_roadmap.sh mutation tests..."

# 1. Path traversal: app/../.github/workflows/ci.yml
TRAVERSAL_CONTENT="${BASE_VALID_ITEM//app\/web\/src\/App.tsx/app\/..\/..github\/workflows\/ci.yml}"
run_mutation_test "Rejects path traversal with '..'" \
  "$TRAVERSAL_CONTENT" \
  "Path traversal forbidden|contains '\.\.'"

# 2. Path without backticks: - app/web/src/App.tsx
NO_BACKTICKS_CONTENT="${BASE_VALID_ITEM/- \`app\/web\/src\/App.tsx\`/- app\/web\/src\/App.tsx}"
run_mutation_test "Rejects path without backticks" \
  "$NO_BACKTICKS_CONTENT" \
  "must match.*with exactly one backtick pair"

# 3. Invalid cost class: XXL
XXL_CONTENT="${BASE_VALID_ITEM/Cost Class\*\*: S/Cost Class\*\*: XXL}"
run_mutation_test "Rejects Cost Class XXL" \
  "$XXL_CONTENT" \
  "Invalid Cost Class 'XXL'"

# 4. Acceptance criterion equal to TBD
TBD_CONTENT="${BASE_VALID_ITEM/This is a valid acceptance criterion with more than three words./TBD}"
run_mutation_test "Rejects acceptance criteria equal to TBD" \
  "$TBD_CONTENT" \
  "cannot contain TBD"

# 5. Acceptance criterion under 3 words
SHORT_CONTENT="${BASE_VALID_ITEM/This is a valid acceptance criterion with more than three words./Fix bug}"
run_mutation_test "Rejects acceptance criteria under 3 words" \
  "$SHORT_CONTENT" \
  "too short \(under 3 words\)"

# 6. Malformed header without colon
NO_COLON_CONTENT="${BASE_VALID_ITEM/ITEM-001:/ITEM-001}"
run_mutation_test "Rejects header without colon" \
  "$NO_COLON_CONTENT" \
  "Invalid ITEM header|Malformed item header"

# 7. Two paths on one Files Touched line
TWO_PATHS_CONTENT="${BASE_VALID_ITEM/- \`app\/web\/src\/App.tsx\`/- \`app\/web\/src\/App.tsx\` \`app\/web\/src\/Other.tsx\`}"
run_mutation_test "Rejects two paths on one Files Touched line" \
  "$TWO_PATHS_CONTENT" \
  "must match.*with exactly one backtick pair"

# 8. Unindented non-app sibling line under Files Touched
UNINDENTED_CONTENT="${BASE_VALID_ITEM/- \`app\/web\/src\/App.tsx\`/- non\/app\/file.ts}"
run_mutation_test "Rejects unindented non-app sibling line" \
  "$UNINDENTED_CONTENT" \
  "must match.*with exactly one backtick pair"

# 9. Invalid non-field line inside item block
NON_FIELD_CONTENT="${BASE_VALID_ITEM/Cost Class\*\*: S/Cost Class**: S
Invalid random non-field text line}"
run_mutation_test "Rejects invalid non-field line inside item block" \
  "$NON_FIELD_CONTENT" \
  "Invalid non-field line inside item block"

# 10. TBD embedded anywhere in acceptance criteria text
EMBEDDED_TBD_CONTENT="${BASE_VALID_ITEM/This is a valid acceptance criterion with more than three words./This implementation is TBD until next sprint}"
run_mutation_test "Rejects TBD anywhere in acceptance criteria" \
  "$EMBEDDED_TBD_CONTENT" \
  "cannot contain TBD"

# B1: Two spaces in header does not bypass validation on Cost Class XXL
B1_CONTENT="${BASE_VALID_ITEM/### ITEM-001:/###  ITEM-001:}"
B1_CONTENT="${B1_CONTENT/Cost Class\*\*: S/Cost Class**: XXL}"
run_mutation_test "B1: Header with two spaces does not bypass validation on Cost Class XXL" \
  "$B1_CONTENT" \
  "Invalid Cost Class 'XXL'"

# B2: Inline value on Files Touched
B2_CONTENT='### ITEM-001: feat(web): test item
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: test
- **Gap Anchor**: `app/web/src/App.tsx#L1`.
- **User Value**: Test value.
- **Files Touched**: `.github/workflows/ci.yml`
- **Acceptance Criteria**:
  1. This is a valid acceptance criterion with more than three words.'
run_mutation_test "B2: Rejects inline value on Files Touched" \
  "$B2_CONTENT" \
  "Inline value forbidden.*Files Touched"

# B3: Inline value on Acceptance Criteria
B3_CONTENT='### ITEM-001: feat(web): test item
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: test
- **Gap Anchor**: `app/web/src/App.tsx#L1`.
- **User Value**: Test value.
- **Files Touched**:
  - `app/web/src/App.tsx`
- **Acceptance Criteria**: TBD'
run_mutation_test "B3: Rejects inline value on Acceptance Criteria" \
  "$B3_CONTENT" \
  "Inline value forbidden.*Acceptance Criteria"

# B4: Header with #### ITEM- in preamble or block
B4_CONTENT='# Product Roadmap
#### ITEM-000: Invalid preamble header

### ITEM-001: feat(web): test item
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: test
- **Gap Anchor**: `app/web/src/App.tsx#L1`.
- **User Value**: Test value.
- **Files Touched**:
  - `app/web/src/App.tsx`
- **Acceptance Criteria**:
  1. This is a valid acceptance criterion with more than three words.'
run_mutation_test "B4: Rejects #### ITEM- header in preamble or block" \
  "$B4_CONTENT" \
  "Invalid ITEM header"

# B8: Combined mutant with .github/workflows/ci.yml + Cost Class XXL + '1. TBD'
B8_CONTENT='### ITEM-001: feat(web): test item
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: XXL
- **Tags**: test
- **Gap Anchor**: `app/web/src/App.tsx#L1`.
- **User Value**: Test value.
- **Files Touched**:
  - `app/web/src/App.tsx`
  - `.github/workflows/ci.yml`
- **Acceptance Criteria**:
  1. TBD'
run_mutation_test "B8: Combined mutant (.github/workflows/ci.yml + XXL + 1. TBD) fails" \
  "$B8_CONTENT" \
  "Scope violation|Invalid Cost Class|cannot contain TBD"

echo "----------------------------------------"
if [ "$failures" -gt 0 ]; then
  echo "FAILED: $failures of $total tests failed."
  exit 1
fi

echo "ALL $total LINT_ROADMAP MUTATION TESTS PASSED."
exit 0
