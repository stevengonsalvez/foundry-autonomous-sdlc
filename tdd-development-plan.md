# TDD development plan: Temporal + CLI factory, vertical slice

Spec: `research/2026-10-20_14-10-54_temporal-cli-factory-replatform-spec.md`. Spikes: `...-spikes.md`.
Mode: fully autonomous (Stevie, 2026-10-20). Decisions below are final unless a test disproves them.

## Architecture decisions (autonomous, with rationale)

| # | Decision | Why |
|---|---|---|
| D1 | Strangler, not rewrite. Add `only`/`use_lock` params to `agents/sdlc_agents/tick.run_tick` so ONE Temporal activity runs the existing logic for ONE issue. | `_Tick` is 1600 lines of proven gates, escalations, release. Rewriting risks the security gates. Existing ~290 tests stay green. |
| D2 | New Python project `services/` (package `sdlc_factory`) depends on `../agents` by path. `agents/` stays; Foundry adapters are simply not used. | Zero churn to CI globs and tests. |
| D3 | `app/` stays at `app/` in v1. Spec said move to `apps/target-app`. Deferred. | `agent-scope`, `tdd-order`, CI globs and the coder all hard-code `app/`. Moving buys nothing for the slice. |
| D4 | `CliFoundry` implements `FoundryPort`: prompt agents run through `CliEngine` (agy, plan mode, no tools); coder `invoke_hosted` goes to an HTTP coder service speaking the existing start/status/cancel protocol. | Lets `tick.py` coder logic (poll, lease, adopt) run untouched. Native heartbeat-activity coder is phase 2. |
| D5 | One `WorkItemWorkflow(id=issue-N)` loops `run_step` activity, waits on durable timer or signal. `human_approved` signal gates spec and merge when `humanGates.*` is true (merge=false by default here). | Spec. |
| D6 | The foreman task queue has `max_concurrent_activities=1`. | Serializes `metrics.json` and release tag reservation (the cross-issue state), replacing the lock ref. |
| D7 | Budget: factory.yaml `budget.call_usd`/`budget.minute_usd` surrogate rates map calls and wall minutes onto the existing USD caps. | Reuses `_guard`, caps, escalation with no logic change. |
| D8 | Ledger: `DoltBranchStore` behind the existing CAS protocol; `ledger-api` (stdlib HTTP) serves `/state.json` to the unchanged control center. | Spike 4 proved CAS. |
| D9 | Proof of scenarios a, d, b+c, d-maintenance is hermetic: existing `FakeGitHub`/`FakeCoder` driven through the real Temporal workflow with time skipping. Compose smoke test runs in `FACTORY_MODE=fake`. A live GitHub+agy run is a documented runbook step, NOT performed autonomously. | A live run merges PRs into the real repo. |

## Chunks (each = one red, green, refactor cycle; later chunks keep earlier tests green)

| # | Chunk | Level | Dir | Depends |
|---|---|---|---|---|
| C0 | `services/` scaffold: pyproject, uv, pytest-asyncio, ruff | build | services/ | none |
| C1 | factory.yaml schema + loader + `factory/` tree (9 agents as `agent.md` + `schema.json` generated from `definitions.py`, automations, runners) | unit | services/sdlc_factory/config.py, factory/ | C0 |
| C2 | `CliEngine` protocol, `AgyEngine` argv/env/classify from terminal event, `extract_json`, `run_json_agent` with 2 repair rounds | unit | services/sdlc_factory/engines.py | C0 |
| C3 | `CliFoundry` (FoundryPort over C2; usage to AgentResult; coder HTTP client) | unit+integ | services/sdlc_factory/cli_foundry.py | C1,C2 |
| C4 | `run_tick(only=, use_lock=)` seam in agents/ | unit | agents/sdlc_agents/tick.py | none |
| C5 | Coder service: HTTP server around existing `CoderService`/`JobRunner` using `CliEngine` instead of `AgyEngine`/Foundry loop | integ | services/sdlc_factory/coder_service.py, agents coder/ | C2,C4 |
| C6 | `DoltBranchStore` + `ledger-api` + roster update in `fold.AGENTS` + control center badges | unit+integ | services/sdlc_factory/ledger_*.py | C0 |
| C7 | Temporal: `run_step`, `list_work` activities; `WorkItemWorkflow`, `PollWorkflow`; humanGates; budget mapping | integ (time-skipping) | services/sdlc_factory/workflows.py, activities.py | C3,C4 |
| C8 | Scenarios a, d, b+c, d-maintenance through the workflow with fakes | e2e hermetic | services/tests/e2e/ | C7 |
| C9 | docker compose stack: Temporal+Postgres, Dolt, ledger-api, nginx control center, workers (foreman, coder), schedule-init, secrets, networks; Dockerfiles | smoke | deploy/compose/ | C5,C6,C7 |
| C10 | Compose smoke script (fake mode), README/runbook, spec deviations doc | e2e smoke | deploy/compose/, docs/ | C9 |

Every spec requirement maps to a chunk: Warp tree (C1), CliEngine (C2), per-stage engine config (C1,C3), humanGates (C1,C7), budget (C1,C7), Dolt+ledger-api+control center (C6), compose (C9), Schedule poll (C7), agy token secret (C5,C9), coder isolation (C9), scenarios (C8).
