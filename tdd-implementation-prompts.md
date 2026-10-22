# Per-chunk red/green/refactor prompts

Rules for every chunk: write the failing test first and show it fails; minimal code to pass; refactor with tests green; run both gate commands; never edit existing agents tests to make them pass (add new tests); no em-dashes in any file; no AI attribution; do not commit (the orchestrator commits).

## C1 config + factory tree
Red: `test_config.py`: loads `factory/factory.yaml` into `FactoryConfig`; `human_gates.merge is False` default for this deployment per file, `spec False`; unknown agent engine raises; every one of the 9 agents in `sdlc_agents.definitions` has `factory/agents/<name>/agent.md` and `schema.json` whose schema equals the one in definitions; budget rates positive; repo owner/name parsed.
Green: dataclasses + PyYAML loader; script `services/scripts/gen_factory_agents.py` emitting agents from definitions.
Refactor: validation errors name the file and key.

## C2 CliEngine
Red: fixtures drive `AgyEngine.classify`: valid JSON result -> OK; `SUCCESS` with empty response -> EMPTY (timeout or denied); `denied_actions` non-empty -> DENIED; stderr `print timeout` -> TIMEOUT; `Authentication required` -> AUTH; `RESOURCE_EXHAUSTED`/429 -> QUOTA. `extract_json` strips fences and prose. `run_json_agent` retries up to 2 repair rounds quoting the error and returns usage.
Green: protocol + `AgyEngine.argv` (`agy -p ... --mode plan --output-format stream-json --json-schema <file> --print-timeout Ns`, no `--sandbox`), env built from nothing, abort_on.
Refactor: shared subprocess runner with process-group kill.

## C3 CliFoundry
Red: `call_prompt_agent` returns `AgentResult` with tokens from `usage`; schema-invalid output is repaired then raises `AgentRunError`-compatible error; budget counters (calls, minutes) increment; coder `invoke_hosted` posts to the coder URL and returns `(json, session_id)`.
Green: adapter using factory config per-agent engine/timeouts.

## C4 tick seam
Red: new `agents/tests/test_tick_single.py`: `run_tick(..., only=N, use_lock=False)` advances only issue N, takes no lock ref, leaves other issues untouched; default behaviour unchanged (whole suite green).
Green: filter in `_load`, optional lock.

## C5 coder service
Red: HTTP `start/status/cancel` round trip with a fake `CliEngine` and fake git; job reaches `succeeded`; scope violation fails; engine AUTH/QUOTA outcomes map to existing reasons.
Green: `http.server` wrapper around `CoderService`; `CliEngineAdapter` implementing `CodingEnginePort`.

## C6 ledger
Red: `DoltBranchStore` contract tests identical to `MemoryBranchStore` (CAS conflict, head advance) using an in-process fake DB-API or a dolt server when `DOLT_TEST_PORT` is set; `ledger-api` GET `/state.json` returns folded v1 state with the new agent roster; control center `node --test` still passes.
Green: store, API, roster edit.

## C7 Temporal
Red: time-skipping tests: workflow loops until terminal; `humanGates.merge=true` holds until `human_approved`; `humanGates.merge=false` does not wait; step activity serialized; `PollWorkflow` starts workflows only for owner issues, idempotent by id.
Green: workflows + activities.

## C8 scenarios
Red: four e2e tests mirroring `agents/tests/test_scenarios.py` a, d, b+c, d-maintenance through the workflow.
Green: wiring only.

## C9/C10 compose
Red: `deploy/compose/smoke.sh` fails with no stack. Green: compose + Dockerfiles; `docker compose config -q` passes; smoke passes in fake mode.
