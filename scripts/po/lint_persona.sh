#!/usr/bin/env bash
# Lint script to verify that po/PERSONA.md enforces all mandatory guardrails
# and adheres to style constraints (no em-dashes, no forbidden mentions).
#
# Usage: scripts/po/lint_persona.sh [path_to_persona_md]

set -euo pipefail

PERSONA_FILE="${1:-po/PERSONA.md}"

if [ ! -f "$PERSONA_FILE" ]; then
  echo "FAIL: Persona file not found: $PERSONA_FILE" >&2
  exit 1
fi

failures=0

check_pass() {
  local name="$1"
  echo "  OK: $name"
}

check_fail() {
  local name="$1"
  local reason="$2"
  echo "  FAIL: $name - $reason" >&2
  failures=$((failures + 1))
}

echo "Linting $PERSONA_FILE for autonomous SDLC guardrails..."

# Check 0a: No em-dashes (Unicode \u2014) or en-dashes (\u2013)
if python3 -c '
import sys
with open(sys.argv[1], "r", encoding="utf-8") as f:
    text = f.read()
if "\u2014" in text or "\u2013" in text:
    sys.exit(1)
' "$PERSONA_FILE" >/dev/null 2>&1; then
  check_pass "No em-dashes or en-dashes"
else
  check_fail "No em-dashes" "Found Unicode em-dash or en-dash in file"
fi

# Check 0b: No forbidden self-referential terms
if python3 -c '
import sys, re
with open(sys.argv[1], "r", encoding="utf-8") as f:
    text = f.read()
if re.search(r"\b(as an A[I]|artificial intelligenc[e]|\bLL[M]\b)\b", text, re.IGNORECASE):
    sys.exit(1)
' "$PERSONA_FILE" >/dev/null 2>&1; then
  check_pass "No forbidden mentions"
else
  check_fail "No forbidden mentions" "Found forbidden self-referential terms"
fi

# Guardrail (a): Untrusted data and author restriction (stevengonsalvez)
if grep -qi "untrusted data" "$PERSONA_FILE" && grep -q "stevengonsalvez" "$PERSONA_FILE"; then
  check_pass "Guardrail (a): Untrusted data and author restriction (stevengonsalvez)"
else
  check_fail "Guardrail (a)" "Must specify untrusted data and restrict actions to author stevengonsalvez"
fi

# Guardrail (b): Label simulated-human and header 'Simulated human (antigravity)'
if grep -q "simulated-human" "$PERSONA_FILE" && grep -qi "Simulated human (antigravity)" "$PERSONA_FILE"; then
  check_pass "Guardrail (b): Label simulated-human and header 'Simulated human (antigravity)'"
else
  check_fail "Guardrail (b)" "Must require label simulated-human and header 'Simulated human (antigravity)'"
fi

# Guardrail (c): PR restrictions (never open, approve, merge PR; never edit code/workflows; never push)
if grep -qi "never open.*pr" "$PERSONA_FILE" && grep -qi "never.*approve.*pr" "$PERSONA_FILE" && grep -qi "never merge" "$PERSONA_FILE" && grep -qi "never.*push" "$PERSONA_FILE"; then
  check_pass "Guardrail (c): Never open, approve, or merge PR; never edit code/workflows; never push"
else
  check_fail "Guardrail (c)" "Must forbid opening, approving, merging PRs, editing code, and pushing"
fi

# Guardrail (d): Allowed commands only, gh account-wide login credential risk documented
if grep -qi "gh issue" "$PERSONA_FILE" && grep -qi "gh pr list" "$PERSONA_FILE" && grep -qi "gh api" "$PERSONA_FILE" && grep -qi "account-wide" "$PERSONA_FILE"; then
  check_pass "Guardrail (d): Strict command allow-list and account-wide credential documentation"
else
  check_fail "Guardrail (d)" "Must define command allow-list and document account-wide gh credential risk"
fi

# Guardrail (e): Never raise spend cap, never continue past 22 USD halt, close/shrink/park cost-cap escalations
if grep -qi "never raise.*spend cap" "$PERSONA_FILE" && grep -qi "22.*usd.*halt" "$PERSONA_FILE" && grep -qi "close.*shrink.*park" "$PERSONA_FILE"; then
  check_pass "Guardrail (e): Spend cap protection (never raise, 22 USD halt, close/shrink/park)"
else
  check_fail "Guardrail (e)" "Must forbid raising caps, enforce 22 USD halt, and restrict cost-cap to close/shrink/park"
fi

# Guardrail (f): CD rollback escalations (never re-release rolled back build, retry only after new fix PR exists)
if grep -qi "never.*re-release.*rolled-back" "$PERSONA_FILE" && grep -qi "new fix pr" "$PERSONA_FILE"; then
  check_pass "Guardrail (f): CD rollback guardrail (no re-release without new passing fix PR)"
else
  check_fail "Guardrail (f)" "Must forbid re-release of rolled-back build and require new fix PR"
fi

# Guardrail (g): One new issue per run, idle requirement, conventional title, testable acceptance criteria, real gap link, no duplicates, scope bounds
if grep -qi "one new issue" "$PERSONA_FILE" && grep -qi "idle" "$PERSONA_FILE" && grep -qi "acceptance criteria" "$PERSONA_FILE" && grep -qi "gap" "$PERSONA_FILE"; then
  check_pass "Guardrail (g): One issue per idle run, testable criteria, gap link, scope bounds"
else
  check_fail "Guardrail (g)" "Must enforce one issue per idle run, testable criteria, and real gap reference"
fi

# Guardrail (h): Progressive product roadmap (po/ROADMAP.md, dependencies, run log request when < 5)
if grep -qi "po/ROADMAP.md" "$PERSONA_FILE" && grep -qi "dependencies" "$PERSONA_FILE" && grep -qi "fewer than 5" "$PERSONA_FILE" && grep -qi "run log" "$PERSONA_FILE"; then
  if grep -qi "needs-maintainer" "$PERSONA_FILE"; then
    check_fail "Guardrail (h)" "Must not reference needs-maintainer; request maintainer extension in run log without filing an issue"
  else
    check_pass "Guardrail (h): Progressive product roadmap (ROADMAP.md, dependencies, run log request under 5)"
  fi
else
  check_fail "Guardrail (h)" "Must require sequential roadmap intake, dependency resolution, and run log maintainer request under 5 items"
fi

if [ "$failures" -gt 0 ]; then
  echo "FAIL: po/PERSONA.md failed $failures guardrail check(s)" >&2
  exit 1
fi

echo "PASS: po/PERSONA.md satisfies all guardrail requirements."
exit 0
