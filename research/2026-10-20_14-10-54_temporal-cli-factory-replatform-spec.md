# Specification: Temporal + CLI Software Factory (Warp-shaped, docker compose)

**Generated from:** research/2026-10-20_14-10-54_temporal-cli-factory-replatform.md
**Interview date:** 2026-10-20
**Version:** 1.0

## Executive Summary

Re-platform the autonomous SDLC off Azure AI Foundry onto Temporal (orchestration) and CLI coding agents (Antigravity `agy` first). Same stages, gates and mission control as today. Restructure this repo on this branch into a monorepo shaped like Warp Factories, with a version-controlled factory definition. The whole stack runs from one `docker compose up`; an Azure VM runs the same compose later.

## Objectives

### Primary Goals
- Like-for-like port: issue to triage/spec/implement/review to merge to release, on docker compose, no Azure services.
- Warp-shaped repo: `factory.yaml`, `agents/`, `automations/`, `runners/`, `skills/`, `scorers/` as the factory definition.
- Engine-agnostic: one `CliEngine` interface, `agy` first, per-stage engine configurable.
- Keep mission control (control center) unchanged in the UI, fed by a new store.

### Success Metrics
- v1 done = these scenarios pass end to end under `docker compose` against GitHub:
  - a: feature happy path
  - d: bug with failing regression test first
  - b + c: vague requirement refinement and not-agent-suitable escalation
  - d-maintenance: stale-test repair PR
- All existing CI gates still pass on agent PRs (`tdd-order`, `agent-scope`, `evals`, etc.).
- Existing pure-logic tests (`machine`, `gates`, `state`, ledger fold) pass unchanged.

## Scope

### In Scope (v1)
- Temporal server (Postgres) in compose, one `WorkItemWorkflow` per issue/PR, a singleton budget/release-serializer workflow.
- Activities: GitHub, LLM-via-CLI stages, coder (long-running, heartbeating), gates, ledger emit.
- Work source: Temporal Schedule polling GitHub (owner-only guard kept).
- Simulated PO as a factory agent on a Temporal Schedule (intake from `ROADMAP.md`) plus in-loop answerer.
- Ledger on Dolt (events, state, plus work-item/factory tables), `state.json` served same-origin to control center via `?data=state.json`.
- Factory definition tree and loader; `humanGates` toggle in `factory.yaml`.
- Budget by CLI calls and wall-clock minutes, quota as a first-class signal.
- CD unchanged: GitHub Pages workflows as today.

### Out of Scope (v1)
- Compose-hosted staging/smoke/soak (CD stays on GitHub Pages).
- Webhook ingress, Slack/Linear/Jira sources.
- Second CLI adapter, scorers/benchmarks, Azure VM, Azure DevOps.
- Write actions in control center.

### Future Considerations (priority order given)
1. Scorers and dashboard metrics on live runs (Warp measure-and-improve).
2. Azure VM deployment of the same compose (small terraform, secrets).
3. A private variant that plugs into Azure DevOps (ADO): requires an SCM abstraction (see Architecture).
4. Later, unprioritized: second CLI adapter (Claude Code or Copilot), webhooks and more work sources, compose-hosted CD staging.

## Technical Requirements

### Architecture

```
┌────────────┐ Schedule ┌───────────────────────┐ activities ┌──────────────┐
│ GitHub     │◀─poll───▶│ Temporal              │───────────▶│ workers      │
│ issues/PRs │          │ WorkItemWorkflow/issue│            │ llm | coder  │
└────▲───────┘          │ BudgetWorkflow (1)    │            │ github|gates │
     │ PR, labels,      └──────────┬────────────┘            └──────┬───────┘
     │ merge (toggle)              │ events                         │ CLI (agy)
     │                             ▼                                ▼
┌────┴─────────┐ state.json  ┌───────────┐              ┌──────────────────┐
│ control      │◀────────────│ ledger-api│◀── Dolt ─────│ coder container  │
│ center (ro)  │  same-origin│ (fold)    │              │ agyuser, no      │
└──────────────┘             └───────────┘              │ Temporal access  │
                                                        └──────────────────┘
```

Decisions:
- **Workflow shape:** `WorkItemWorkflow(id=issue-N | pr-N)` loops: `load_context` activity, `machine.next_action` (pure, in workflow), then the matching activity. Waits use `wait_condition` on signals (`checks_changed`, `pr_changed`, `human_approved`) plus durable timers. Fixed workflow id replaces the lock ref.
- **Reuse unchanged:** `machine.py`, `gates.py`, `state.py` (as a projection comment on the issue), `release.py`, `designed_tests.py`, ledger events/fold, `sanitise.py`, `schema_check.py`, the fakes.
- **Drop:** `lock.py`, deferral streaks, wall-budget logic, `start-unconfirmed` resend, session-lost counting, `foundry.py`, `keyvault.py`, `hosted/*`, `deploy_agents.py`, Terraform foundry/keyvault/budget/observability/egress modules, `CoderService`.
- **Language:** Python for workers and workflows (core logic is Python). `temporalio` 1.34.x, `temporalio/server` 1.31.4 or 1.32.x after verifying the sample scripts.
- **Engine interface:** extract `CliEngine` (provision, refresh, argv, env, abort_on, classify, tool_hint) from `coder/runner.py`; a shared runner owns retry, keep-edits and reap. Classify from the terminal event (`status` or subtype), never exit code alone (agy soft-deny exits 0).
- **LLM stages:** each agent has `engine`, `model` and `runner` in `factory.yaml` or its `agent.md`. A CLI stage runs read-only in a disposable checkout with no shell. Add JSON fence extraction before `schema_check` and allow up to 2 repair rounds.
- **Human gates:** `humanGates: {spec: bool, merge: bool}` in `factory.yaml`. For this deployment both default to merge=false (auto-merge enabled). When on, the workflow waits for a `human_approved` signal sent from the Temporal UI, a GitHub review/label, or a small API call. `verify_merge` runs in both modes.
- **Budget:** caps are `max_calls` and `max_minutes` per issue and in total, in `factory.yaml`. Quota error parks the workflow on a durable timer until reset; `escalated:agent-quota` after a bound. `BudgetWorkflow` serializes total accounting and release tag reservation.
- **SCM abstraction (for later ADO):** keep `GitHubPort` narrow, rename to an `ScmPort`, and keep GitHub-only assumptions (labels, rulesets, check runs, state comment) behind it. Do not build ADO now.

### Components

| Component | Purpose | Technology |
|---|---|---|
| temporal, temporal-admin-tools, temporal-ui | orchestration | `temporalio/server`, Postgres 16 |
| postgres | Temporal stores | Postgres, localhost-bound |
| dolt | ledger + factory DB | Dolt sql-server (MySQL protocol) |
| ledger-api | ingest events, fold, serve `state.json`, `issues.json` | Python, reuse `ledger/` |
| control-center | mission control, read-only | existing static app via nginx, `?data=state.json` |
| worker-foreman | workflows + gate/GitHub/ledger activities | Python |
| worker-llm | CLI stage activities (triage, gate, review, etc.) | Python + agy |
| worker-coder | long coder activity, own task queue, low concurrency | Python + agy + node + git |
| schedule-init | registers Temporal Schedules (poll, sim PO) | Python one-shot |
| egress-proxy | allow-list egress for coder | proxy container, internal network |

### Integrations
- GitHub REST (PAT, owner-only guard, repo configurable in `factory.yaml`, default this repo's parcel app).
- agy via `agy -p ... --mode accept-edits` with `--output-format stream-json` and an explicit `--print-timeout`.
- Existing GitHub Actions CI and Pages CD unchanged (evals imports to be decoupled from `foundry.py`).

### Performance Requirements
- Coder activity: start-to-close = `deadline_s` + 300 s, heartbeat timeout 120 s, heartbeat every 30 s, `max_concurrent_activities` set low and configurable.
- Keep transcripts and diffs out of Temporal payloads (claim-check via files on a volume or Dolt rows); payload limit 2 MB, history warn at 10 MB.

### Security Requirements
- Owner-only guard, fail-closed spend, `verify_merge` in full, head-sha-bound review marker, scope checks, secret redaction all preserved.
- Coder: separate container, `cap_drop: ALL` plus `CHOWN, DAC_OVERRIDE, FOWNER, KILL, SETUID, SETGID`, unprivileged `agyuser`, env built from nothing, per-call `GIT_ASKPASS`.
- Network: coder on an internal network behind an allow-list proxy; Temporal frontend and Dolt unreachable from agent code; pass proxy and CA env to agy (currently missing).
- Secrets via docker secrets (GitHub PAT, agy token file), never in image or env visible to agyuser. Ports bound to localhost.
- agy auth: **personal OAuth token, chosen by Stevie**, supplied as a docker secret file copied per job into `agyuser` home (mode 600). Refreshed tokens are not persisted (issue #1194), so re-login on a dev machine when it expires. Set `GEMINI_FORCE_FILE_STORAGE=true`, unset `DBUS_SESSION_BUS_ADDRESS`.

## User Experience

### User Flows
1. Operator runs `docker compose up`; Temporal UI and control center come up on localhost.
2. Issue filed on GitHub (or filed by the sim PO schedule); the poll schedule starts or signals its workflow.
3. Stages advance; control center shows the ticket moving across the board; Temporal UI shows workflow detail.
4. With `humanGates.merge=false` the workflow merges after gates; with true it waits for a human signal.

### Edge Cases

| Scenario | Expected Behavior |
|---|---|
| agy quota hit | classify `quota`, durable timer until reset, bounded, then `escalated:agent-quota` |
| agy auth expired or blocked | kill on `authentication required`, escalate with a clear reason, no retry storm |
| agy exits 0 with no edits | treated as soft-deny, not success |
| Worker crash mid-coder | heartbeat timeout, retry resumes from pushed branch and red commit; job id derived from workflow |
| Duplicate issue event | `start_workflow` with fixed id is idempotent |
| Two agent PRs conflict | existing merge-conflict revise flow retained |
| Non-owner issue | ignored, no spend |
| Release tags from parallel workflows | serialized by `BudgetWorkflow`/release activity |

## Constraints & Dependencies

### Technical Constraints
- GitHub remains the work source and PR host in v1; GitHub Actions gates and Pages CD stay.
- Temporal compose from `samples-server` is documented as local-dev; Postgres-only visibility, no Elasticsearch. Keep search attributes within the Postgres limit (10 Keyword).
- Dolt is not a supported Temporal persistence store; Temporal stays on Postgres.
- Control center must keep the `state.json` v1 contract (`schema.js:437-478`). `fold.AGENTS` roster and badge map need the new agent names.

### External Dependencies
- agy install script and its update/storage hosts; Gemini-side quota.
- GitHub API; Temporal and Dolt images.

### Timeline Constraints
- None stated. Spikes first (under an hour each): agy `--print-timeout 15m --output-format stream-json`; one agent through CLI for parse failure rate; boot Temporal compose; Dolt `BranchStore`.

## Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|---|---|---|---|
| Personal OAuth token in automation breaches Antigravity Terms §6, account suspension | High | Med | Accepted by Stevie for v1. Keep the token path swappable for API key/ADC behind `provision`; document it; avoid proxying tokens |
| agy token refresh lost per job, token expires | Med | High | Per-job copy, expiry detection and clear escalation; re-login runbook |
| agy 5 min default timeout cuts calls before our cap | Med | Med | Pass `--print-timeout`, verify in spike |
| CLI output not valid JSON | Med | High | `--json-schema`/stream-json, fence extraction, 2 repair rounds, evals replay for gates |
| Agent code reaches Temporal/Dolt on the network | High | Med | Internal network, separate containers, proxy, uid rules |
| Cost caps blind (no token usage) | Med | High | Calls and minutes caps, quota signal |
| Dolt as ledger store immaturity under concurrent writes | Med | Low | CAS on a head row, same retry loop as today, rebuild from events |
| GitHub-coupling blocks ADO later | Med | High | `ScmPort` boundary now, no ADO code yet |

## Decisions Made

### Key Trade-offs
- **agy auth:** personal OAuth token (over API key/ADC). Rationale: free under subscription and already how the coder works; risk accepted and isolated.
- **Merge gate:** config toggle `humanGates`, auto-merge enabled for this deployment (over forcing Warp's never-merge). Rationale: keeps the proof autonomous while keeping Warp parity switchable.
- **Repo:** restructure this repo on this branch (over new repo/side folder). Rationale: keeps history and Foundry reference code reachable.
- **Stage engine:** configurable per stage in `factory.yaml` (over single CLI or fixed split).
- **Target repo:** configurable, default this repo's parcel app.
- **Work source:** Temporal Schedule polling (over webhook): works behind NAT and on a VM.
- **Ledger store:** Dolt, including work-item/factory tables (over Postgres or GitHub branch). Rationale: git-like versioning and history of the ledger. Temporal remains on Postgres.
- **CD:** unchanged on GitHub Pages in v1.
- **Control center:** read-only; no write UI.
- **Sim PO:** Temporal Schedule + factory agent (over Orca cron).
- **Budget:** calls and wall-clock minutes, quota as first-class signal.

### Deferred Decisions
- Compose-hosted staging and runner reachability: CD stays on Pages.
- Second CLI adapter and per-stage harness beyond `agy`.
- Exact Dolt table design for work items and scorer results: decided during scorers work.
- ADO variant design: after Azure VM.

## Implementation Notes

### Priority Order
1. Spikes (agy flags, CLI JSON parse, Temporal compose boot, Dolt store).
2. Monorepo restructure and factory tree skeleton (no behaviour change; fix CI path globs such as `agent-scope` for `apps/target-app`).
3. Extract `CliEngine`, move coder into a Temporal activity.
4. `WorkItemWorkflow` + activities reusing `machine.py`, running the pure-logic tests plus scenario tests under Temporal time-skipping with the existing fakes.
5. Dolt `BranchStore`, `ledger-api`, control center served same-origin, new agent roster.
6. Compose stack, secrets, network isolation, scenarios a, d, b+c, d-maintenance green.
7. Then extensions in the stated priority order.

### Proposed layout

```
apps/control-center/   apps/target-app/ (from app/)
factory/               factory.yaml agents/ automations/ runners/ skills/ scorers/
services/foreman/      services/workers/   services/ledger/
work-sources/github/   simulated-human/    evals/   ci/gates/
deploy/compose/        deploy/azure-vm/ (later)
```

### Technical Debt Accepted
- Pages CD and GitHub-bound Actions remain: needed for a fast proof.
- GitHub `state` branch no longer the ledger store: PO script `git show origin/state:state.json` must read the ledger API instead.
- Personal-token ToS exposure: accepted for v1.

## Open Questions

- [ ] Does agy return usable `usage` and image input (ui-tester) in `stream-json`? (not verified)
- [ ] Does control center tolerate a missing `environments.source`? (not verified)
- [ ] Who writes the `metrics` branch today, and does anything still need it? (only reconcile read traced)
- [ ] Is the `warp-factory-examples` tree worth cloning to copy exact file formats? (not cloned; needs your OK)
- [ ] Dolt remote (DoltHub or none) for ledger history push?

---

*This specification was generated through systematic interview of the plan author.*
