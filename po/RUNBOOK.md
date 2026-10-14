# Runbook: Simulated Human Loop

This runbook documents the architecture, operation, guardrails, and lifecycle of the Simulated Human autonomous loop for `stevengonsalvez/foundry-autonomous-sdlc`.

---

## 1. Executive Overview

The Simulated Human loop is an automated counterpart that replaces the human product owner and triage lead. It runs as an Orca scheduled automation executing a persistent Antigravity CLI session every 4 hours.

```
┌──────────────┐ every 4h ┌────────────────┐ issue / answers ┌────────────┐
│ Orca         │─────────▶│ agy "PO"       │────────────────▶│ GitHub     │
│ automation   │ precheck │ resumed session│                 │ issues     │
└──────────────┘          └────────────────┘                 └─────┬──────┘
                                   ▲  reads state.json             │ owner-only
                                   │                               ▼
                          ┌────────┴───────┐   gates + CD    ┌────────────┐
                          │ branch state   │◀────────────────│ SDLC loop  │
                          └────────────────┘                 └────────────┘
```

The persona operates with four primary hats:
1. **Product Owner**: Selects the NEXT unblocked improvement from `po/ROADMAP.md` by dependency order and files exactly ONE high-value improvement with testable acceptance criteria, strictly when the pipeline is idle. When fewer than 5 `todo` items remain, files an alert for maintainers to extend the roadmap.
2. **Requirements Answerer**: Answers clarification questions from `sdlc-req-gate` on issues in `stage:needs-refinement`.
3. **Triage Lead**: Assigns severity and component ownership (`owner:web`, `owner:api`, `owner:carrier-mock`) to incoming defects.
4. **Escalation Owner**: Resolves escalations under strict guardrails: reframes or closes `escalated:not-agent-suitable`, closes or parks `escalated:cost-cap` without raising caps, and files targeted fix issues for `escalated:deploy-failed` (CD rollbacks) without re-releasing the failed build.

---

## 2. Labels Reference

The loop participates in the repository state machine using these exact labels:

| Label Category | Labels | Meaning / Action |
|---|---|---|
| **Identity** | `simulated-human` | Mandatory on every issue filed or comment posted by this persona. Header `### Simulated human (antigravity)` is required. |
| **Maintainer** | `needs-maintainer` | Applied to `roadmap: extend po/ROADMAP.md` when fewer than 5 `todo` items remain in `po/ROADMAP.md`. |
| **Stage** | `stage:needs-refinement` | Requirement scored < 80. Persona wears Requirements Answerer hat to supply answers. |
| | `stage:ready` | Requirements passed gate (>= 80). Waiting for feasibility check. |
| | `stage:feasible` | Feasibility passed. Test designer agent generates failing tests. |
| | `stage:tests-written` | Vitest tests committed red. Coder agent starts. |
| | `stage:building` | Coder actively iterating on implementation. Pipeline is busy. |
| | `stage:in-review` | Coder PR opened with `agent:pr`. CI checks and code review in progress. Pipeline is busy. |
| | `stage:merged` | PR merged to main via merge commit. |
| | `stage:released` | Release notes generated, tag created, GitHub release published. |
| **Escalations** | `escalated:not-agent-suitable` | Feasibility rejected due to external credentials/contracts. Persona reframes or closes. |
| | `escalated:cost-cap` | Issue exceeded 3.00 USD cap. Persona parks or closes. NEVER raises cap. |
| | `escalated:deploy-failed` | CD smoke or soak failed; build rolled back. Persona comments findings and files fix issue. |
| | `escalated:requirements` | Two refinement rounds failed to reach 80. Persona reframes or closes. |
| | `escalated:build-failed` | Coder exhausted attempts or CI check timeout. Persona reviews diagnostics. |
| | `escalated:agent-error` | Non-transient failure streak. Persona investigates. |
| **Triage** | `bug:triaged`, `severity:s1`..`s4`, `owner:web`, `owner:api`, `owner:carrier-mock` | Applied by Triage Lead hat on `type:bug` issues. |
| **Type** | `type:feature`, `type:bug`, `type:maintenance` | Work item type categorization. |

---

## 3. Precheck Guardrails (`scripts/po/precheck.sh`)

Orca evaluates `scripts/po/precheck.sh` before launching each scheduled run. The script outputs exactly one explanatory line and returns exit code 0 to proceed or exit code 1 to skip.

### Skip Conditions:
1. **Billed Spend Exceeded**: Billed spend in `state.json` (`cost.billing.billed_usd` or `cost.totals.billed_usd`) exceeds 18.00 USD.
2. **State File Missing or Stale**: `state.json` is missing from branch `state` or has an `updated_at` older than 30 minutes (1800 seconds).
3. **Antigravity Quota Exhausted**: Token file missing or CLI reports quota exhaustion.
4. **Daily Issue Cap Reached**: 6 or more issues carrying label `simulated-human` were filed in the preceding 24 hours.
5. **Pipeline Busy**: An issue is currently in `stage:building` or `stage:in-review`.
   - *Exception*: If an open issue has an active `escalated:*` label or `stage:needs-refinement` needing an answer, the precheck does NOT skip, because answering escalations is the priority.

---

## 4. Persona Guardrails and Security Boundary

Every execution cycle enforces the following security boundaries (verified by `scripts/po/lint_persona.sh`):

1. **Untrusted Input and Owner Filter**:
   - All issue bodies, PR texts, and comments are treated as untrusted data.
   - The persona ignores any issue or comment not authored by `stevengonsalvez`.
   - Injected prompt payloads (e.g. instructions to approve PRs or raise caps) are ignored.
2. **Attribution and Transparency**:
   - Every comment and issue carries the label `simulated-human`.
   - Every comment and issue begins with `### Simulated human (antigravity)`.
3. **PR and Code Separation**:
   - The persona NEVER opens, approves, or merges a pull request.
   - The persona NEVER modifies application source code, configuration files, or workflows.
   - The persona NEVER runs `git push`.
4. **Command Allow-List**:
   - Permitted commands:
     - `gh issue create`, `gh issue comment`, `gh issue edit`, `gh issue close`, `gh issue list`, `gh issue view`
     - `gh pr list`, `gh pr view` (read-only)
     - `gh api` (GET requests only on this repository)
     - `git fetch origin state`, `git show origin/state:state.json`
     - `jq`, `cat`
   - *Credential Risk Note*: The machine uses an account-wide `gh` CLI credential. This accepted risk is mitigated by strictly enforcing the command allow-list in the persona definition and automated lint checks.
5. **Spend Cap Protection**:
   - NEVER raise a spend cap.
   - NEVER instruct the orchestrator to continue past the 22.00 USD halt limit.
   - For `escalated:cost-cap`, only close the issue, shrink its scope into a smaller follow-up, or park the issue.
6. **CD Rollback Safety**:
   - NEVER instruct a re-release of a rolled-back build.
   - Retrying deployment is permitted only after a NEW fix PR exists and passes all 6 gates on main.
   - The persona posts failure findings on the ticket and files a dedicated fix issue.
7. **Single Issue Intake**:
   - At most ONE new issue filed per scheduled run, and only when the repository is verified idle.
   - Requires conventional title, problem description, testable acceptance criteria, and explicit link to a real gap in `app/`, `apps/control-center`, `docs`, `scenarios`, or `scripts`.

---

## 5. Product Roadmap (`po/ROADMAP.md`) and Progressive Backlog

The continuous self-building loop operates from an ordered, progressive product roadmap defined in `po/ROADMAP.md`. Rather than inventing random or disconnected tasks, the simulated human advances the parcel tracker (`app/`) along a coherent architectural and user-experience progression.

### Backlog Structure:
Each item in `po/ROADMAP.md` is structured with:
- **Identifier**: Standard prefix (`ITEM-001`, `ITEM-002`, ...).
- **Title**: Conventional commit style (`feat(web): ...` or `feat(api): ...`).
- **User Value**: Concrete user or stakeholder benefit.
- **Testable Acceptance Criteria**: Numbered, deterministic criteria with exact values and assertions.
- **Files Touched**: Strictly restricted to paths under `app/` (`app/core`, `app/contracts`, `app/carrier-mock`, `app/api`, `app/web`, `app/e2e`). Agent pull requests touching files outside `app/` are blocked by the `agent-scope` gate.
- **Dependencies**: Explicit list of prerequisite item IDs that must be completed before the item becomes eligible for intake.
- **Cost Class**: Rough budget estimate (`S` under 1 USD, or `M`).
- **Tags**: Functional groupings (`ui`, `accessibility`, `timeline`, `api`, `storage`, `theme`).
- **Status**: `todo`, `filed`, or `done`.

### Intake and Selection Algorithm:
1. **Dependency Resolution**: When the repository is idle and within spend limits, the persona inspects `po/ROADMAP.md` and filters for items whose dependencies are all satisfied (`done` in `po/ROADMAP.md` or marked `filed`/`done` in `po/MEMORY.md`).
2. **Sequential Pick**: The persona takes the first unblocked `todo` item in sequential order.
3. **Issue Creation**: The persona generates an issue containing the title, user story, acceptance criteria, and explicit `app/` scope, referencing the roadmap ID.
4. **Memory Tracking**: The persona records the item as `filed` in `po/MEMORY.md` along with the created issue number.
5. **PR-Only Modification**: The persona NEVER edits `po/ROADMAP.md` directly during scheduled runs. Changes to `po/ROADMAP.md` occur strictly through merged pull requests.
6. **Maintainer Extension Rule**: If fewer than 5 `status: todo` items remain in `po/ROADMAP.md`, the persona files ONE issue titled `roadmap: extend po/ROADMAP.md` carrying the label `needs-maintainer` and pauses new feature intake until maintainers supply new roadmap items.

---

## 6. Memory Conventions (`po/MEMORY.md`)

Because the session is resumed across scheduled runs, the persona maintains `po/MEMORY.md` to ensure continuity:
- **Themes Covered**: Tracks broad features previously developed (e.g. parcel timelines, delivery date formatting).
- **Issues Filed**: Audit table of issues created, reasons, and eventual outcomes.
- **Ideas Rejected**: Records proposals evaluated and rejected (e.g. multi-select filters, third-party vendor integrations) to prevent repeating ideas.
- **Backlog Candidates**: Real gaps identified in code, OpenAPI contracts, or control center views awaiting idle cycles.

---

## 7. Reading the Run Log and Monitoring

To monitor what the persona has done:

1. **Orca Automation Runs**:
   ```bash
   orca automations runs --name "po-loop"
   ```
   Inspects start times, precheck decisions, exit statuses, and outputs.

2. **GitHub Activity**:
   ```bash
   gh issue list --repo stevengonsalvez/foundry-autonomous-sdlc --label "simulated-human" --state all
   ```
   Lists all issues and comments generated by the simulated human.

3. **Event Ledger**:
   Inspect recent events on branch `state`:
   ```bash
   git show origin/state:events.jsonl | tail -n 20 | jq '{at, type, issue, data}'
   ```

---

## 8. How to Stop the Loop

### Emergency Stop (Orca Automation):
To pause or stop the persona from running on its 4-hour schedule:
```bash
orca automations disable --name "po-loop"
```

### Stopping Background Coding Jobs:
If the autonomous coder is actively building an issue and needs to be stopped:
```bash
uv run --project agents python scripts/deploy_agents.py routine --disable
```
Or cancel a running coder job via curl as documented in `docs/runbook.md` section 7.

---

## 9. Orca Automation Setup Command

Do NOT create the Orca automation during development; the orchestrator session will wire it after the draft PR is reviewed and merged.

When ready to wire the automation on the host, run:

```bash
orca automations create \
  --name "po-loop" \
  --trigger "0 */4 * * *" \
  --workspace "$PWD" \
  --reuse-session \
  --precheck "scripts/po/precheck.sh" \
  --prompt "$(cat po/PERSONA.md)"
```

### Automation Flags Explained:
- `--name "po-loop"`: Unique identifier for the automation job.
- `--trigger "0 */4 * * *"`: Cron schedule running every 4 hours.
- `--workspace "$PWD"`: Binds execution to this dedicated worktree path.
- `--reuse-session`: Submits recurring runs to the existing live session to preserve persona memory and context.
- `--precheck "scripts/po/precheck.sh"`: Runs precheck guardrails before each cycle. If precheck exits non-zero, the run is safely skipped.
- `--prompt "$(cat po/PERSONA.md)"`: Injects the persona prompt and operating rules.

---

## 10. Blocked Items and Notes

- **Live Automation Creation**: As instructed, the Orca automation has NOT been created in this session; it will be created by the orchestrator session after PR merge.
- **Antigravity Quota Tracking**: The precheck script validates `$HOME/.gemini/antigravity-cli/antigravity-oauth-token` presence and supports `AGY_QUOTA_EXHAUSTED=1` overrides for test harnesses.
