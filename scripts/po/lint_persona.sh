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
if grep -qi "untrusted data" "$PERSONA_FILE" && grep -qiE "authored by [^.]*stevengonsalvez" "$PERSONA_FILE"; then
  check_pass "Guardrail (a): Untrusted data and author restriction (stevengonsalvez)"
else
  check_fail "Guardrail (a)" "Must specify untrusted data and explicitly restrict actions to author stevengonsalvez"
fi

# Guardrail (b): Label simulated-human and header 'Simulated human (antigravity)'
if grep -q "simulated-human" "$PERSONA_FILE" && grep -qi "Simulated human (antigravity)" "$PERSONA_FILE"; then
  check_pass "Guardrail (b): Label simulated-human and header 'Simulated human (antigravity)'"
else
  check_fail "Guardrail (b)" "Must require label simulated-human and header 'Simulated human (antigravity)'"
fi

# Guardrail (c): PR and safety restrictions (never open, approve, merge PR; never comment approval; never push; never modify git refs; never run arbitrary commands)
if grep -qi "never open.*pr" "$PERSONA_FILE" && \
   grep -qi "never.*approve.*pr" "$PERSONA_FILE" && \
   grep -qi "never comment approval on a pr" "$PERSONA_FILE" && \
   grep -qi "never merge" "$PERSONA_FILE" && \
   grep -qi "never.*push" "$PERSONA_FILE" && \
   grep -qi "never modify git refs" "$PERSONA_FILE" && \
   grep -qi "never run arbitrary shell commands" "$PERSONA_FILE"; then
  check_pass "Guardrail (c): Never open, approve, or merge PR; never comment approval; never modify git refs; never run arbitrary commands"
else
  check_fail "Guardrail (c)" "Must forbid opening, approving, commenting approval, merging PRs, editing code, pushing, modifying git refs, and arbitrary commands"
fi

# Guardrail (d): Allowed commands only, deny-list on allow-list block, account-wide credentials
allow_list_check="$(python3 - "$PERSONA_FILE" 2>&1 << 'PYEOF'
import sys, re

with open(sys.argv[1], "r", encoding="utf-8") as f:
    text = f.read()

m = re.search(r"4\.\s+\*\*Command Allow-List\*\*:(.*?)(?=\n\d+\.|\n##|\Z)", text, re.DOTALL)
if not m:
    print("Missing Command Allow-List section")
    sys.exit(1)

block = m.group(1)

# Deny-list checks on allow-list block
if re.search(r"\bgh\s+pr\s+merge\b", block, re.IGNORECASE):
    print("Deny-list violation: 'gh pr merge' found in allow-list block")
    sys.exit(1)
if re.search(r"(--squash|--admin)\b", block, re.IGNORECASE):
    print("Deny-list violation: '--squash' or '--admin' found in allow-list block")
    sys.exit(1)
if re.search(r"\bgit\s+push\b", block, re.IGNORECASE):
    print("Deny-list violation: 'git push' found in allow-list block")
    sys.exit(1)
for pr_m in re.finditer(r"`gh\s+pr\s+([^`]+)`", block):
    cmd_verb = pr_m.group(1).strip().split()[0]
    if cmd_verb not in ("list", "view"):
        print(f"Deny-list violation: disallowed PR command 'gh pr {cmd_verb}' in allow-list block")
        sys.exit(1)
for line in block.splitlines():
    if re.search(r"^\s*-\s+`cat`", line):
        print("Deny-list violation: bare 'cat' found in allow-list block")
        sys.exit(1)

# Assert required commands in allow-list block
required = [
    (r"gh\s+issue", "gh issue commands"),
    (r"gh\s+pr\s+list", "gh pr list (read-only)"),
    (r"gh\s+pr\s+view", "gh pr view (read-only)"),
    (r"gh\s+api\s+--method\s+GET", "gh api --method GET"),
    (r"git\s+fetch\s+origin\s+main\s+state", "git fetch origin main state"),
    (r"git\s+show\s+origin/main:po/ROADMAP\.md", "git show origin/main:po/ROADMAP.md"),
    (r"git\s+show\s+origin/state:state\.json", "git show origin/state:state.json"),
    (r"jq`?\s*\(stdin\s+filter\s+only", "jq (stdin filter only)"),
]
for pattern, desc in required:
    if not re.search(pattern, block, re.IGNORECASE):
        print(f"Allow-list missing required entry: {desc}")
        sys.exit(1)

print("OK")
PYEOF
)" || true

if [ "$allow_list_check" = "OK" ] && grep -qi "account-wide" "$PERSONA_FILE"; then
  check_pass "Guardrail (d): Strict command allow-list, deny-list on allow block, and account-wide credential documentation"
else
  check_fail "Guardrail (d)" "Allow-list failed validation: $allow_list_check"
fi

# Guardrail (e): Spend cap protection with exact thresholds 30, 32, 35, 3 USD and second hard rule on 32 halt state
if grep -qi "never raise.*spend cap" "$PERSONA_FILE" && \
   grep -qE "\b30(\.00)?\s*USD\b" "$PERSONA_FILE" && \
   grep -qE "\b32(\.00)?\s*USD\b" "$PERSONA_FILE" && \
   grep -qE "\b35(\.00)?\s*USD\b" "$PERSONA_FILE" && \
   grep -qE "\b3(\.00)?\s*USD\b" "$PERSONA_FILE" && \
   grep -qi "close.*shrink.*park" "$PERSONA_FILE" && \
   grep -qiE "(stop.*32.*halt|halt state.*flagged|32(\.00)?\s*USD halt state)" "$PERSONA_FILE" && \
   ! grep -qE "\b(18|21|22|25)(\.00)?\s*USD\b" "$PERSONA_FILE" && \
   ! grep -qiE "\b(18|21|22|25|32|35)(\.00)?\s*USD\s*(precheck threshold|filing stop)" "$PERSONA_FILE" && \
   ! grep -qiE "spend (is )?under\s*(18|21|22|25|32|35)(\.00)?\s*USD" "$PERSONA_FILE"; then
  check_pass "Guardrail (e): Spend cap protection with exact thresholds 30/32/35/3 USD (never raise, 32 USD halt stop rule, close/shrink/park, filing stop 30 USD)"
else
  check_fail "Guardrail (e)" "Must forbid raising caps, enforce exact spend thresholds 30/32/35/3 USD, require stopping when 32 halt state is flagged, reject 18/21/22/25/32/35 as filing stop, and restrict cost-cap to close/shrink/park"
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

# Guardrail (i): Visible surface (home or parcel page), ui-proof screenshot diff criterion, highest-visibility preference
if grep -qi "visible surface" "$PERSONA_FILE" && \
   grep -qiE '(`?home`?\s+or\s+`?parcel page`?|home\s*,\s*parcel page)' "$PERSONA_FILE" && \
   grep -qi "ui-proof" "$PERSONA_FILE" && \
   grep -qiE '(screenshot.*differ|differ.*screenshot)' "$PERSONA_FILE" && \
   grep -qi "highest-visibility" "$PERSONA_FILE"; then
  check_pass "Guardrail (i): Visible surface (home or parcel page), ui-proof screenshot diff criterion, highest-visibility preference"
else
  check_fail "Guardrail (i)" "Must require naming visible surface (home or parcel page), ui-proof screenshot diff criterion, and preferring highest-visibility ready item first"
fi

# Guardrail (j): a merge-conflict escalation is close only; re-filing would bypass the one new issue per run rule
if grep -q "escalated:merge-conflict" "$PERSONA_FILE" && grep -qi "close only" "$PERSONA_FILE" && grep -qi "never re-file" "$PERSONA_FILE"; then
  check_pass "Guardrail (j): merge-conflict escalation is close only, never re-filed"
else
  check_fail "Guardrail (j)" "Must handle escalated:merge-conflict as close only and forbid re-filing it"
fi

# Guardrail (k): an agent-quota escalation is a factory fault left for the owner, never closed or re-filed
if grep -q "escalated:agent-quota" "$PERSONA_FILE" && grep -qi "leave for the owner" "$PERSONA_FILE" && grep -qi "do not close or re-file" "$PERSONA_FILE"; then
  check_pass "Guardrail (k): agent-quota escalation is left for the owner, never closed or re-filed"
else
  check_fail "Guardrail (k)" "Must leave escalated:agent-quota for the owner and forbid closing or re-filing it"
fi

# Guardrail (l): an agent-error close is "not planned", never "completed", and never claims the item was out of roadmap scope
if grep -q 'gh issue close <number> --reason "not planned"' "$PERSONA_FILE" && ! grep -qi "out of roadmap scope" "$PERSONA_FILE"; then
  check_pass "Guardrail (l): agent-error close uses --reason \"not planned\", no out of roadmap scope claim"
else
  check_fail "Guardrail (l)" "Must close escalated:agent-error with gh issue close <number> --reason \"not planned\" and must not say the work is out of roadmap scope"
fi

# Guardrail (m): the requirements answerer must not invent acceptance criteria
if grep -qi "never add acceptance criteria" "$PERSONA_FILE"; then
  check_pass "Guardrail (m): requirements answers never add acceptance criteria"
else
  check_fail "Guardrail (m)" "Must forbid the requirements answerer from adding acceptance criteria absent from the roadmap item"
fi

if [ "$failures" -gt 0 ]; then
  echo "FAIL: po/PERSONA.md failed $failures guardrail check(s)" >&2
  exit 1
fi

echo "PASS: po/PERSONA.md satisfies all guardrail requirements."
exit 0
