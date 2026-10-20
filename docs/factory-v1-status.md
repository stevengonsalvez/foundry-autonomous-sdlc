# Temporal + CLI factory: v1 status

Branch `stevengonsalvez/temporal-cli-workflow`. Spec: `research/2026-10-20_14-10-54_temporal-cli-factory-replatform-spec.md`. Plan: `tdd-development-plan.md`. Run it: `docs/factory-runbook.md`.

## What exists

```
GitHub ──poll (Schedule, 60s)──▶ PollWorkflow ──▶ WorkItemWorkflow(issue-N | pr-N)
                                                   │ loop: run_step (activity, 1 at a time)
                                                   │   = run_tick(only=N, use_lock=False)
                                                   │ holds on human_approved when humanGates on
                                                   ▼
          foreman worker ──/agent-run, /invoke──▶ coder container (agy as uid 61001 / 61000)
               │ events                              ▲ internal network, egress via allow-list proxy
               ▼
          ledger-api ──▶ Dolt (files + meta, 1 Dolt commit per write) ──▶ nginx ──▶ control center
```

| Area | Where | Tests |
|---|---|---|
| factory definition (Warp-shaped tree, generated agents) | `factory/`, `services/sdlc_factory/config.py` | 32 |
| CliEngine, agy classify from terminal event, JSON repair | `services/sdlc_factory/engines.py` | 74 |
| CliFoundry (FoundryPort over the CLI, remote sandbox runner) | `cli_foundry.py`, `agent_run.py` | 50 + agent_run, remote_runner |
| single-object tick seam (`only`, `use_lock`, `hold`, `meter`) | `agents/sdlc_agents/tick.py` | agents suite 942 |
| coder as HTTP service (no Foundry) | `coder_service.py`, `agents/.../coder/local_wiring.py` | 21 |
| Dolt ledger store + ledger-api | `ledger_store.py`, `ledger_api.py` | with services suite |
| Temporal workflows, activities, worker, schedules | `workflows.py`, `activities.py`, `worker.py`, `schedule_init.py` | with services suite |
| scenarios a, d, b+c, d-maintenance via workflow | `services/tests/e2e/` | 7 |
| compose stack + smoke | `deploy/compose/` | smoke: 35 checks |

Live agy 1.4.3 check (`deploy/compose/live-agy-check.sh`, 3 model calls, about 33k tokens): a call through the sandbox and proxy returns OK in about 12 s once four Google hosts are allowed (all measured in the squid log); an expired or garbage token is classified AUTH in under 0.3 s; headless plan mode refuses `read_file` outside the cwd, so the uid boundary is covered only by smoke.sh (rerun the script after every agy upgrade). The check exposed a parser bug (agy printed the answer and then a wrapper line), fixed in `extract_json`.

Last independent run: services 344 passed / 6 skipped, ruff clean; agents 942 passed (agent-reported full run, subset rerun by orchestrator); `deploy/compose/smoke.sh` 35 of 35 in fake mode.

## Deviations from the spec (all deliberate)

| Spec said | v1 does | Why |
|---|---|---|
| Move `app/` to `apps/target-app/` | `app/` stays | `agent-scope`, `tdd-order`, CI globs and the coder hard-code `app/`; moving adds risk, no slice value |
| Coder as a heartbeating Temporal activity | Coder is an HTTP service; `run_step` polls it | Reuses the proven start/poll/lease logic in `tick.py` unchanged; native activity is phase 2 |
| All orchestration logic in workflows | One activity wraps `run_tick(only=N)`; workflow owns waiting, gates, quota | Keeps every security gate (verify_merge, owner guard, caps) intact |
| Cost caps in calls and minutes | Calls and minutes map to USD via surrogate rates (`factory.yaml`), billed through the existing caps | Reuses cap and escalation logic; `model_usd` now holds surrogate dollars on this path |
| Prompt agents run in the worker | All agy runs in the coder container as `agyagent` (61001); coder jobs run as `agyuser` (61000) | Security review: plan mode can read any file its uid can; a shared uid also lets a coder job tamper with agent calls |
| Scenarios green under compose | Green through the real Temporal workflow with fakes, plus compose smoke in fake mode | A live run merges PRs into the real repo; not done without Stevie |

## Not done (explicit)

- Live end-to-end run against real GitHub (real agy through the sandbox is verified, GitHub side is not): needs a PAT and merges PRs into the target repo. Checklist in the runbook.
- Native coder activity with heartbeats; CD staging on compose (CD stays on GitHub Pages); webhooks and extra work sources; scorers and benchmarks; second CLI adapter; Azure VM; Azure DevOps variant (SCM port boundary not yet cut).
- Simulated-PO 4-hourly intake: schedule and activity exist, the activity returns `disabled` and raises `NonRetryable` "not implemented" when enabled.
- `humanGates.merge` is `false` (auto-merge, per Stevie). The remaining merge risk is a prompt-injected reviewer verdict; set `true` for untrusted repos.
- Control center `npm test` browser tests were not run here (no Chromium in this shell); the non-browser suite passes (65).

## Known risks

| Risk | Status |
|---|---|
| Personal agy OAuth token in automation vs Antigravity Terms §6 | Accepted by Stevie; token path is swappable behind `provision` |
| agy token refresh lost per job; expiry | Per-job copy; AUTH classified; re-login runbook |
| Concurrent agent calls share `agyagent` HOME | Documented residual risk |
| `metrics.json` recovery overwrite resets totals when the file is unreadable | Pre-existing behaviour, an existing test relies on it |
| Per-entry gate counts can drift after a lost publish | Heals on a full tick |
| Temporal frontend unauthenticated | Bound to localhost; coder cannot reach it |
