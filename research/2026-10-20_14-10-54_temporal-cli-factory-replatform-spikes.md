# Spike results: Temporal + CLI factory

**Date**: 2026-10-20
**Branch**: stevengonsalvez/temporal-cli-workflow @ f9c9fc0
**Spec**: research/2026-10-20_14-10-54_temporal-cli-factory-replatform-spec.md

Throwaway code lived in the session scratchpad; nothing here is in the repo. Environment: agy 1.4.2, Docker 29.1.3, Dolt 2.5.0, `temporalio` Python SDK (uv, Python 3.12).

## Summary

| Spike | Result | Consequence for the spec |
|---|---|---|
| 1. agy headless, `stream-json` + `--json-schema` | Works, but 2 of 3 triage runs hit the print timeout and returned `SUCCESS` with an empty response | Adapter must not trust `status` or exit code |
| 2. CLI JSON reliability | Small sample (n=3): 1 valid JSON in 120 s, 2 empty. Valid run took 104 s and 12k thinking tokens for a trivial triage | Cheap stages need a faster engine option (direct API) or a long timeout; per-stage engine config is justified |
| 3. Temporal compose + Python SDK | Boots healthy in 40 s; gate signal and heartbeat cancel both work | Design is sound; fix upstream script typo |
| 4. Dolt BranchStore | CAS works; 1 of 8 racing writers wins; history in `dolt log` | Dolt ledger store is viable behind the existing protocol |

## 1. agy headless (observed)

- `agy --help` on 1.4.2: `--print-timeout` default is `0s` ("waits until the turn completes"), not the 5 minutes in the docs the research agent read. Flags `--output-format stream-json`, `--json-schema`, `--mode accept-edits|auto|plan`, `--input-format stream-json` all exist.
- The `result` event carries `status`, `response`, `duration_seconds`, `num_turns`, `usage{input_tokens, output_tokens, thinking_tokens, cache_read_tokens, total_tokens}` and `denied_actions[]`. So CLI usage IS reported, which settles the open question on token visibility (for agy 1.4.2).
- Soft deny confirmed: run 1 ended `status: SUCCESS`, rc 0, `response: ""`, `denied_actions: [RunCommand]`, plus a stderr line "jetski: no output produced - a tool required the "command" permission...".
- Timeout confirmed as a silent failure: runs 2 and 3 printed `[agy] print timeout after 2m0s with turn in progress; returning partial output` to stderr, with `SUCCESS`, rc 0, empty response, zero usage.
- Run 4 (third attempt) returned schema-valid JSON (`owner`, `severity`, `summary`) after 103.8 s using 42,270 total tokens (12,341 thinking).
- Classification rule derived: a call is OK only if `response` is non-empty and parses against the schema; otherwise inspect `denied_actions` and stderr for `print timeout`, `no output produced`, `Authentication required`, quota patterns.

Limits: 4 runs total, plan mode, one prompt, no tools allowed. Not a failure-rate measurement. Not tested: `accept-edits` coder flow, allow-list, ui-tester image input, quota behaviour.

## 3. Temporal compose and SDK (observed)

- Official `samples-server/compose` Postgres file, pinned `temporalio/server:1.31.4`, admin-tools 1.31.4, UI 2.56.0, Postgres 16. Up and healthy in 40 s; namespace `factory` created; UI answered HTTP 200 on localhost.
- Upstream `scripts/create-namespace.sh` has the typo `MAX_ATTdMPTS` on the failure branch (confirmed). With `set -u` it would abort with an unbound variable instead of retrying. Fixed locally with sed.
- Upstream `.env` sets `COMPOSE_PROJECT_NAME=temporal`, which overrides a `name:` in the compose file. Set our own project name explicitly to avoid clashing with other stacks on the same Docker host.
- Host Docker already runs unrelated Supabase containers on many high ports; 7233 and 8233 were free. Bind to localhost and pick ports deliberately.
- SDK test (sync activity running a subprocess, `heartbeat_timeout=10s`, `WAIT_CANCELLATION_COMPLETED`):
  - Gate flow: activity finished, workflow waited on `wait_condition`, a `human_approved` signal completed it.
  - Cancel: `activity.heartbeat()` raised `CancelledError` inside the sync activity, the handler killed the process group, the child PID was gone. Workflow ended `CancelledError` 5.1 s after `cancel()`.
- Gotcha: the workflow sandbox re-imports `__main__`, so running worker and workflow in one file needs an `if __name__ == "__main__":` guard.

## 4. Dolt BranchStore (observed)

- `dolt sql-server` (local binary 2.5.0) plus `pymysql`. Tables `files(path PK, content)` and `meta(id, head)`. Write does a conditional `UPDATE meta SET head=<token> WHERE head <=> <parent>`; zero rows maps to `StoreConflict`; then `REPLACE` files, SQL commit, `CALL DOLT_COMMIT('-Am', msg)`.
- Results: stale parent rejected with `StoreConflict`; 8 threads racing on one parent gave 1 success and 7 conflicts; `dolt log` shows one Dolt commit per ledger write with the message and token.
- Caveat: SQL commit and `DOLT_COMMIT` are two steps, so a crash between them leaves working-set changes that the next write's `-Am` sweeps into its commit. Acceptable for a ledger rebuildable from `events.jsonl`; if not, hold the writer lock across both.
- Not tested: reading `state.json` back through an HTTP service, remote push, concurrent readers during writes, container image `dolthub/dolt-sql-server`.

## Spec changes these results justify

1. Drop the assumption that agy usage is unknown: record `usage` from the `result` event, and keep calls and minutes as the cap unit.
2. Add classification rules (above) to the `CliEngine.classify` contract; never treat `status == SUCCESS` as success.
3. Set `--print-timeout` explicitly per stage; default is unbounded in 1.4.2.
4. Expect slow stages (about 100 s for a trivial triage). Keep per-stage engine config, and consider `gemini`/API-key model with lower thinking effort (`--effort low`) for cheap stages. Untested.
5. Pin an explicit compose project name and ports; vendor the upstream scripts with the typo fixed.

## Cleanup

Dolt server stopped by PID; compose project `temporal` brought down with volumes removed (`docker compose down -v` from the spike directory). Unrelated Supabase containers were not touched.
