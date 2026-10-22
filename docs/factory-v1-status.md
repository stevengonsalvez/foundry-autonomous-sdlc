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

## Live GitHub run (2026-10-21 to 22, real agy, real merges)

Stack: `deploy/compose` with `FACTORY_MODE=live`, secrets from Bitwarden, target repo `stevengonsalvez/foundry-autonomous-sdlc`, `humanGates.merge=false` (auto-merge), `main` unprotected.

| Path | Issue or PR | Result | Evidence |
|---|---|---|---|
| a feature (scenario a3) | #124, PR #125 | merged, released | 15 of 15 checks, tag `prod/20261021-180738-6f81608`, issue `stage:released` |
| maintenance (d-maintenance2) | PR #130 | reviewer approved, merged | 15 of 15 checks, files `HomePage.tsx`, `filter-by-status.test.tsx` |
| bug with revision loop (d3) | #133, PR #134 | review sent it back once, then merged | 15 of 15 checks, files `server.ts`, `trailing-slash.test.ts` |
| b vague | #126 | questions asked, simulated PO answered, then stopped at the TDD gate (feature already existed) | `stage:needs-refinement` to `stage:ready` to `tests-not-red` |
| c not suitable | #127 | `escalated:not-agent-suitable`, 3 correct reasons | credentials, vendor, infrastructure |

Scenarios a, a2, d and d-maintenance were built by earlier Foundry runs and already pass on `main`, so the TDD gate rightly stops them. Live runs use a3, d3 and d-maintenance2 (`scenarios/`). One scenario (d2) contradicted tests already on `main`; the factory refused it correctly.

### Bugs the live run found (all fixed test-first, none reachable in fake mode)

| # | Symptom | Cause | Fix commit |
|---|---|---|---|
| 1 | feasibility "ended denied" | agent text asks for a GitHub file tool agy does not have | `424c5ad`, widened in `904a90b` |
| 2 | `npm ci` cannot find the lockfile | coder umask 077 made the job dir 0700, `agyuser` could not enter | `3986564` |
| 3 | `CancelledError` x3 | 10 minute step timeout vs 10 to 30 minute test design | `e20371c` |
| 4 | req-gate and test designer denied | model reaches for a shell command in a toolless run | `f1cd958` (diagnostics), `f9fc286` (one re-ask) |
| 5 | "processes survived SIGKILL" | `esbuild` zombies, coder PID 1 never reaps | `f9b34bf`, `14b73e1` |
| 6 | `git push` "cannot exec askpass" | coder `/tmp` is noexec | `cdf6d95`, `b5be927` |
| 7 | agy killed (-9) at a job start | two coder jobs share one engine user and each start reaps it | `26672f4` (one job at a time, 429 busy) |
| 8 | factory halted itself | 32 USD total surrogate cap spent by one day of runs | `20f2c36` (2000 calls) |

Cost: about 30 surrogate USD per live run (10 agent calls plus minutes per stage). Real cost is the agy plan quota, which was never hit.

## Deviations from the spec (all deliberate)

| Spec said | v1 does | Why |
|---|---|---|
| Move `app/` to `apps/target-app/` | `app/` stays | `agent-scope`, `tdd-order`, CI globs and the coder hard-code `app/`; moving adds risk, no slice value |
| Coder as a heartbeating Temporal activity | Coder is an HTTP service; `run_step` polls it | Reuses the proven start/poll/lease logic in `tick.py` unchanged; native activity is phase 2 |
| All orchestration logic in workflows | One activity wraps `run_tick(only=N)`; workflow owns waiting, gates, quota | Keeps every security gate (verify_merge, owner guard, caps) intact |
| Cost caps in calls and minutes | Calls and minutes map to USD via surrogate rates (`factory.yaml`), billed through the existing caps | Reuses cap and escalation logic; `model_usd` now holds surrogate dollars on this path |
| Prompt agents run in the worker | All agy runs in the coder container as `agyagent` (61001); coder jobs run as `agyuser` (61000) | Security review: plan mode can read any file its uid can; a shared uid also lets a coder job tamper with agent calls |
| Scenarios green under compose | Green through the real Temporal workflow with fakes, compose smoke in fake mode, and live a3, b, c, d3 and d-maintenance2 on real GitHub (section above) | Stevie authorised the live run on 2026-10-21 |

## Not done (explicit)

- Live runs of scenarios d (bug, via d3) and d-maintenance (via d-maintenance2) are done; the per-scenario checks in `scripts/run_scenarios.py` for a2, d and d-maintenance still exist but only prove the gate.
- Native coder activity with heartbeats; CD staging on compose (CD stays on GitHub Pages); webhooks and extra work sources; scorers and benchmarks; second CLI adapter; Azure VM; Azure DevOps variant (SCM port boundary not yet cut).
- Simulated-PO 4-hourly intake: schedule and activity exist, the activity returns `disabled` and raises `NonRetryable` "not implemented" when enabled.
- `humanGates.merge` is `false` (auto-merge, per Stevie). The remaining merge risk is a prompt-injected reviewer verdict; set `true` for untrusted repos.
- Control center `npm test` browser tests were not run here (no Chromium in this shell); the non-browser suite passes (65).

## Known gaps from the live run

- A revision whose engine rounds cancel out ends as `internal-error` ("nothing to commit") instead of a clean failure; the job still escalates.
- The no-tools notice does not stop every model from asking for a command; one re-ask covers most cases, a second denial still escalates.
- Bug and maintenance merges are not tagged as releases; only the feature path produced a `prod/...` tag in the run.
- `main` was unprotected during the run: the factory's own gates were the only protection.
- Escalated issues cannot be retried by removing the label; close and refile (runbook).

## Known risks

| Risk | Status |
|---|---|
| Personal agy OAuth token in automation vs Antigravity Terms §6 | Accepted by Stevie; token path is swappable behind `provision` |
| agy token refresh lost per job; expiry | Per-job copy; AUTH classified; re-login runbook |
| Concurrent agent calls share `agyagent` HOME | Documented residual risk |
| `metrics.json` recovery overwrite resets totals when the file is unreadable | Pre-existing behaviour, an existing test relies on it |
| Per-entry gate counts can drift after a lost publish | Heals on a full tick |
| Temporal frontend unauthenticated | Bound to localhost; coder cannot reach it |
