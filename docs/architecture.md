# Architecture and contracts

This is the contract every component is built against. If code and this file disagree, fix one of them in the same commit.

```
┌──────────┐ opened/closed ┌─────────────┐   Invocations   ┌──────────────────────────┐
│ GitHub   │──────────────▶│ Routines    │────────────────▶│ sdlc-orchestrator        │
│ issues   │  (poll: */5)  │ schedule    │                 │ hosted agent (Python)    │
│ PRs      │◀──labels,─────│ */5 * * * * │                 │ deterministic state      │
│ checks   │   comments,   └─────────────┘                 │ machine, owns all merges │
└────▲─────┘   merges, tags                                └───┬───────────┬──────────┘
     │                                     Responses API       │           │ Invocations
     │ PAT from Key Vault                  ┌───────────────────▼──┐    ┌───▼────────────────┐
     │                                     │ prompt agents        │    │ sdlc-coder         │
     │                                     │ gpt-5-mini           │    │ hosted agent       │
     │                                     │ req-gate, feasibility│    │ git + node + agy   │
     │                                     │ test-designer, po,   │    │ works for hours,   │
     │                                     │ reviewer, triage,    │    │ pushes its branch  │
     │                                     │ ci-triage, notes     │    │ opens its own PR   │
     │                                     └──────────────────────┘    └────────────────────┘
     └─── plain CI: test, e2e, coverage, gitleaks, tdd-order, agent-scope. CI never drives agents.
```

## Components

| Component | Where | Notes |
|-----------|-------|-------|
| Demo app | `app/` | npm workspaces: `core`, `carrier-mock`, `api`, `web`, `e2e`. Parcel tracker. |
| Carrier contract | `app/contracts/carrier.openapi.yaml` | Source of truth for the mocked carrier API. Contract tests validate mock and client against it. |
| Agents package | `agents/sdlc_agents/` | Python 3.12+, pytest. Orchestrator logic, GitHub client, gates, cost, coder runtime, specialist definitions. |
| Hosted agents | `agents/hosted/orchestrator/`, `agents/hosted/coder/` | Thin `main.py` plus `requirements.txt`, deployed as zips (`python_3_13`, `remote_build`, Invocations protocol). |
| Deploy tooling | `scripts/deploy_agents.py` | Creates prompt agent versions, hosted agent versions, project connections, role assignments, the routine. Idempotent. |
| Repo setup | `scripts/setup_repo.py` | Labels, branch ruleset, Pages. Idempotent, uses `gh`. |
| Gate scripts | `scripts/gates/` | `tdd_order.py`, `agent_scope.py`. Pure Python, pytest, run in CI and by the orchestrator logic. |
| CI | `.github/workflows/` | `ci.yml` (all gates), `pages.yml` (publish app and dashboard), `infra-ci.yml`. |
| Dashboard | `dashboard/` | Static site (no build step), reads `metrics.json`. |
| Metrics | branch `metrics`, file `metrics.json` | Written by the orchestrator, copied into the Pages artifact by `pages.yml`. |
| Ledger | `agents/sdlc_agents/ledger/`, `agents/hosted/ledger/` | The state-keeper: event schema, fold, reconcile, branch writer. Hosted agent `sdlc-ledger`, or the same code inline in the orchestrator. See "Ledger and control center". |
| State | branch `state`: `state.json`, `events.jsonl`, `archive.json` | Written only by the ledger. Read by the control center. |
| Control center | `apps/control-center/` | Read-only static app, 8 views, published at `/control-center/`. |
| CD | `.github/workflows/cd.yml`, `scripts/cd/`, branch `deploy` | Staging on merge, smoke, 10 minute soak, prod or rollback. See `docs/cd.md`. |

## Roles and secrets

| Secret | Where it lives | Who reads it |
|--------|----------------|--------------|
| `github-pat` | Key Vault secret | Orchestrator, coder and ledger, each with its own managed identity (secret-scope `Key Vault Secrets User`). Prompt agents reach GitHub only through the `github-mcp` project connection. The ledger uses it only to write branch `state` and to read issues, comments, PRs and branches `deploy` and `metrics`. |
| `agy-cli-token` | Key Vault secret | Coder only. Written to `~/.gemini/antigravity-cli/antigravity-oauth-token`, mode 600. |

The PAT belongs to the repo owner `stevengonsalvez`. It is used only against `stevengonsalvez/foundry-autonomous-sdlc`; every client in this repo hard-codes that repo and refuses any other.

## Egress

`sdlc-coder` runs untrusted code (agy, `npm ci`, the tests it writes), so its hosted agent version carries an egress policy: the account RAI policy `sdlc-coder-egress` (`Microsoft.CognitiveServices/accounts/raiPolicies@2026-05-15-preview`, module `infra/terraform/modules/egress_policy`), attached as `rai_config` by `scripts/deploy_agents.py`. Default action Deny, one exact-host `Fqdn` Allow rule per host the coder's code calls:

| Host | Why |
|------|-----|
| `github.com`, `api.github.com` | clone, fetch, push; issues, PRs, owner lookup |
| `registry.npmjs.org` | `npm ci` |
| `nodejs.org` | node 22 download and `SHASUMS256.txt` |
| `deb.debian.org` | `apt-get install git ca-certificates` |
| `antigravity.google`, `antigravity-cli-auto-updater-974169037036.us-central1.run.app` | agy installer and the binary it downloads |
| `<account>.services.ai.azure.com`, `<vault>.vault.azure.net` | the fallback model loop; secrets |

Platform connectivity (managed identity, telemetry) is allowed by the service without rules. agy's own API hosts are not known from the code, so the policy starts in `Audit` (nothing blocked, would-be denials logged) and moves to `Enforced` (unlisted hosts get a proxy 403) only after a real job's decisions are read; hosts found that way go in `coder_egress_extra_hosts`. The orchestrator and ledger run only this repository's code and have no policy. A policy binds to an agent version: a change reaches the coder only through a new version and new sessions.

## State machine

One object, one `stage:*` label at a time. Transitions are performed only by the orchestrator, are idempotent (label swap plus state comment), and each is recorded with a timestamp in the state comment.

```
 issue opened (owner only)
        │
        ▼
 ┌──────────────┐ score<80 ┌────────────────────┐ questions ┌──────────────────┐
 │ req-gate     │─────────▶│ stage:needs-       │──────────▶│ product-owner    │
 │ score 0..100 │          │ refinement         │◀──answers─│ (simulated)      │
 └──────┬───────┘          └─────────┬──────────┘ re-score  └──────────────────┘
        │ score>=80                  │ 2 rounds without 80: escalated:requirements
        ▼                            ▼
 stage:ready ──feasibility──▶ stage:feasible        escalated:not-agent-suitable (terminal, reasons)
        │                          │
        │               test-designer writes tests
        ▼                          ▼
 (bug) triage: severity:*,   stage:tests-written ─▶ stage:building ─▶ stage:in-review ─▶ stage:merged ─▶ stage:released
  owner:*, bug:triaged        (coder commits the     (coder pushes,     (CI + reviewer)    (merge commit)   (notes + tag)
                               tests first, red)      opens PR)
```

Label set (created by `scripts/setup_repo.py`; names are exact):

- Stage: `stage:needs-refinement`, `stage:ready`, `stage:feasible`, `stage:tests-written`, `stage:building`, `stage:in-review`, `stage:merged`, `stage:released`
- Escalation (terminal): `escalated:not-agent-suitable`, `escalated:requirements`, `escalated:review-failed`, `escalated:cost-cap`, `escalated:build-failed`, `escalated:agent-error`, `escalated:deploy-failed` (set by the CD workflow when a release is rolled back, never by the orchestrator)
- Type: `type:feature`, `type:bug`, `type:maintenance`
- Bug triage: `bug:triaged`, `severity:s1`, `severity:s2`, `severity:s3`, `severity:s4`, `owner:web`, `owner:api`, `owner:carrier-mock`
- PR: `agent:pr` (set on every PR the coder opens), `maintenance:test-repair`

An issue is acted on only if its author is the repo owner. Anything else is ignored with no spend.

The object type comes from the `type:*` label (default `type:feature`); the scenario letter from the body marker `<!-- scenario: a|b|c|d|d-maintenance -->` (when absent, metrics infer it). A bug is triaged before its requirement is scored. The stale-test PR (owner-authored, labelled `maintenance:test-repair`) is its own object: its state comment lives on the PR, its type is `maintenance`, and it only enters the pipeline after its `test` check failed with no test file in the diff.

### State comment

Each issue (or maintenance PR) has exactly one bot comment starting with `<!-- sdlc-state:v1` followed by JSON and `-->`, then a human readable summary. The orchestrator edits it in place. The JSON is the source of truth for the stage; labels are a projection the orchestrator keeps in sync. Only comments authored by the owner identity count. Characters `<`, `>` and `&` in the JSON are written as `<`, `>`, `&`, so text inside can never close the comment. Unknown keys are preserved; a version above 1 is refused, never overwritten. Beyond the example below the orchestrator records `quality.history`, `ci_triage`, `tests` (file list; contents live in the `<!-- sdlc-tests:v1` comment), `gate_history` (results per evaluated head), `release.pending` (a reserved tag), `escalation`, `failures` (consecutive failures of one step; 3, or 6 for coder polls, escalate) and `cost.coder_model_usd`. A failing step rolls the state back to its last saved version, keeping only its spend and the failure count.

Failures are classified. Transient ones (HTTP 408, 429, 5xx, `rate_limit_exceeded`, timeouts, dropped connections, GitHub rate limits) are retried inside the tick with exponential backoff and jitter, honouring `Retry-After`, never past the tick's wall budget; if they persist the object is deferred: left exactly as it was (no label, comment or failure count change; spend already incurred is still saved), reported as `result: "deferred"` in the tick report and as `deferred` in metrics. Only non-transient failures count: an agent answer that fails its schema or checks after one repair retry (the validation error is sent back to the agent), a refusal or incomplete answer, or a contract violation. Three consecutive counted failures of a prompt agent step end in `escalated:agent-error`; `escalated:not-agent-suitable` is reserved for a real `suitable: false` verdict from the feasibility agent. The three MCP-using agents get one tool, `get_file_contents` (it also lists directories), because every listed tool's schema is billed as input tokens on every call. The tick report lists input and output tokens per model call.

Designed tests are checked in code before the coder sees them: each file is `app/<workspace>/tests/**/*.test.ts(x)` (the only files each workspace's vitest config collects), imports `describe`, `expect`, `it` (and `vi` or hooks if used) from `vitest` because globals are off, imports only files that exist on main (named imports must be exported there) and only the packages `vitest`, `@testing-library/*`, `@parcel/core`, `react` and `react-dom`, and is not an existing file. A failing check re-asks the designer once with the problems. The designer gets the file list under `app/`, the exports of the workspace's `tests/helpers` and of `@parcel/core`, an existing test as a template and the most relevant sources (about 12K characters). When the coder still reports `failed` with reason `tests-invalid`, the error lines go back to the designer (stage back to `stage:feasible`, at most two repair rounds, within the cost cap) and a new coder job starts from main on a new branch `agent/issue-N-r<round>` (the abandoned branch is deleted), so the PR opens with exactly one test commit; a third `tests-invalid` ends in `escalated:agent-error`. The designer must also write files that pass `tsc --noEmit` under the strict tsconfig: types are imported with `import type` (`verbatimModuleSyntax`), and branded types are built with a cast (`"PK1000000001" as TrackingNumber`); the context lists every branded type of `@parcel/core`, and the lint flags a type imported as a value and a string literal for a field of a branded type. A `tests-invalid` detail made of tsc lines (`<path>(l,c): error TSxxxx: ...`) is handled like a vitest one.

Red required checks on an agent PR head (only `test`, `coverage` or `e2e`; a red `gitleaks`, `tdd-order` or `agent-scope` escalates at once) are worked on before anything escalates. The orchestrator reads the tail of the failing check log (`get_check_log`, 20K characters). When the log names a designed test file, or `sdlc-ci-triage` calls it `stale-test` on those files, the PR is closed unmerged and the designer repair loop above runs (new branch `agent/issue-N-r<round>`). Otherwise `sdlc-ci-triage` explains the failure and the coder runs `revise` on the same PR with the log's error lines and the explanation as `spec.notes` (state key `ci_revise`, bound to the head sha), then the checks run again on the new head. After two CI revise rounds a red head escalates `escalated:build-failed` with the failing check names and the last log line. Maintenance PRs still escalate at once.

```json
{
  "version": 1, "issue": 12, "type": "feature", "scenario": "a",
  "stages": [{"stage": "stage:ready", "at": "2026-10-10T12:00:00Z"}],
  "quality": {"score": 86, "rounds": 1, "questions": []},
  "feasibility": {"suitable": true, "reasons": []},
  "triage": {"severity": "s2", "owner": "api"},
  "coder": {"job_id": "j-12-1", "session_id": "...", "engine": "agy", "started_at": "...", "iterations": 3, "engine_events": [...]},
  "pr": {"number": 13, "branch": "agent/issue-12", "head": "<sha>"},
  "review": {"verdict": "approve", "head": "<sha>", "rounds": 1},
  "gates": {"test": "success", "coverage": "success", "e2e": "success", "gitleaks": "success", "tdd-order": "success", "agent-scope": "success"},
  "release": {"tag": "v0.2.0", "url": "..."},
  "cost": {"usd": 0.0123, "calls": [{"agent": "sdlc-req-gate", "in": 900, "out": 400, "usd": 0.00103}], "coder_seconds": 412, "coder_usd": 0.0}
}
```

## Control loop

A routine fires `sdlc-orchestrator` every five minutes (cron `*/5 * * * *`, the platform minimum). A tick:

1. Takes a lock: create ref `refs/heads/sdlc-lock` (atomic; 422 means held). A lock older than 10 minutes is stale and may be replaced. Release at the end of the tick.
2. Lists open owner-authored issues and open PRs with `agent:pr` or `maintenance:test-repair`, computes the next transition for each from labels, check runs and the state comment, performs at most one transition per object, bounded by a 4 minute wall budget.
3. Calls the coder (`start` or `status`) when an object is `stage:building`. The status call also keeps the coder session alive (sandbox idle timeout is at most 60 minutes).
4. Writes `metrics.json` to branch `metrics` and dispatches `pages.yml`.

Every LLM call is made with the cumulative issue cost checked first. Cost over 3 USD per issue puts the object in `escalated:cost-cap`. Total spend is tracked in `metrics.json` (`totals.usd`, which never decreases) and the loop halts new work at 22 USD. Issue cost counts prompt agent tokens, coder compute (2 vCPU, 4 GiB: 0.2706 USD per hour of reported job time) and the coder's own model spend; each tick also adds the orchestrator's compute (1 vCPU, 2 GiB, tick seconds plus the 2 minute idle timeout) to `totals.orchestrator_usd` and `totals.usd`. Merged work is always released: past a cap the notes are written without a model call. Every coder job carries `deadline_s` 7200 and `max_model_usd` = what is left under the issue cap (at most 0.50); a job reported `interrupted` is started again with the same job id (at most three times).

GitHub port additions used by the orchestrator: `create_commit(message, *, parent_sha)` (the lock ref points at a fresh empty commit, so its tip time is the lock time), `get_check_log(sha, name)` (ci-triage input), `list_pull_files(number)` (merge gate), and `CheckRun.pull_requests` (runs GitHub ties to a PR).

A coder job that ends `failed` (including `tests-invalid`) or `timeout` leaves its evidence on the issue, because the sandbox log does not outlive its session: one owner-authored comment per job id (marker `<!-- sdlc-coder-log:v1 <job_id> -->`, updated in place) with the reason, phase, iterations and engine, and inside a `<details>` block the `engine_events` JSON, the red and green summaries and the last 3000 characters of `log_tail`. Token-shaped strings (GitHub tokens, JWTs, bearer values, URL credentials, storage keys) are replaced with `[REDACTED]`, and each part sits in a code fence longer than any backtick run in it, so nothing in it renders, links or mentions. The state comment's coder block keeps the last 20 `engine_events`, redacted.

A maintenance triage is checked in code: ci-triage gets every test file at the PR head, and of its `test_files` only real paths survive (exact, unique suffix or unique basename), joined by every test file the log reports failing (vitest prints `|web| tests/x.test.tsx` for `app/web/tests/x.test.tsx`), and by every test file, `app/e2e` specs included, that still contains a string or JSX text the PR removed from non-test files and did not put back (live PR #36: the failing unit log named only the vitest files, so the Playwright spec kept the old heading and e2e stayed red); when none remains the PR escalates `escalated:agent-error`. A coder job is lost when `status` answers `session_not_accessible` (HTTP 400/404) on two consecutive polls, or when it is unfinished 30 minutes past its deadline whatever the polls say (it is then cancelled, best effort). A lost job's lease is released, its wall time is charged, `coder_sessions_lost` is counted in the state and in `metrics.json`, a PR it already pushed is adopted, and otherwise the job restarts once under a new job id on the same branch (counting an attempt; the coder continues from a pushed branch); a second loss escalates `escalated:build-failed` with reason `coder-session-lost`. Failures that pushed nothing also start a new job (new job id, fresh session, same branch rules, counting an attempt): `engine-unavailable` up to the attempt limit and `internal-error` once, then `escalated:build-failed`; `invalid-allowed-paths` on a maintenance job reruns the triage file validation on the current head and starts one new job when that yields other real paths, else `escalated:agent-error`. An `interrupted` job is resumed under the same job id; when the resume lands in a session that never saw the job (the coder answers `lease-held` with the interrupted job's own lease), the lease is released and a new attempt starts. Each of these still leaves its coder-log comment.

Coder starts are never duplicated. The job id is written ahead; a `start` without a session id is retried only when the request provably never left (connection refused, unknown host, 429). After an ambiguous failure (timeout, 5xx) the job is `start-unconfirmed`: with a stored session the next tick asks `status` (404 `unknown_job` means it never landed); without one it waits two ticks and resends `start` once. A new job takes the lease ref `agent-lease/<issue>` (created by the coder; 422 means another live job holds it and `start` is refused with reason `lease-held`). While a lease is held the orchestrator adopts the PR the unreachable job produces (or the new head of an existing PR), and sweeps the lease and escalates `escalated:build-failed` when nothing arrives within the job deadline; it deletes the lease on every terminal coder outcome and escalation. Required checks that stay missing or pending for 3 hours (from entering `stage:in-review`, or from PR creation for a maintenance PR) escalate `escalated:build-failed`; a `cancelled` check waits one tick for its rerun. An object deferred for transient failures on 24 consecutive ticks escalates `escalated:agent-error` (the streak lives in `metrics.json` under `deferrals`). A coder start with less than 0.01 USD left under the issue cap escalates `escalated:cost-cap`. Lists from GitHub are never silently shortened: a listing past 20 pages or a truncated tree raises, and a PR with 3000 or more changed files (the API maximum) or a head in another repository is never merged.

## Coder contract (Invocations protocol)

Request bodies (JSON). The platform issues the session id in the `x-agent-session-id` response header of the first call; callers store it and pass it back as the query parameter `agent_session_id=<id>` on later calls. Replies are plain JSON.

```json
{"op": "start", "job": {
  "job_id": "j-12-1", "repo": "stevengonsalvez/foundry-autonomous-sdlc", "base": "main",
  "branch": "agent/issue-12", "mode": "feature",
  "issue": {"number": 12, "title": "...", "body": "..."},
  "spec": {"acceptance_criteria": ["..."], "notes": "..."},
  "tests": [{"path": "app/api/tests/parcel.test.ts", "content": "..."}],
  "test_cmd": "npm test", "max_iterations": 5, "deadline_s": 7200, "allowed_paths": ["app/"]}}
{"op": "status", "job_id": "j-12-1"}
{"op": "cancel", "job_id": "j-12-1"}
```

Modes:

| Mode | Branch | Extra fields | Result |
|------|--------|--------------|--------|
| `feature`, `bugfix` | `agent/issue-N`, created from `base` | `tests` (non-empty) | red commit, implementation, new PR with `agent:pr` |
| `revise` | `agent/issue-N`, must exist | `pr: {"number": 13}`, `tests: []`, reviewer findings in `spec.notes` | at least one new commit (`fix: address review findings for #N`) on the existing PR; tests from the red commit untouched; no new PR |
| `maintenance` | the PR head ref (any branch except `base`, for example `chore/update-home-heading`) | `pr: {"number": 14}`, `tests: []`, `allowed_paths` = the real test files ci-triage named or the failing log reports (validated by the orchestrator, never a path that does not exist); `issue` optional | only those test files change, pushed to the existing PR only once green as ONE squashed commit `test: repair stale tests for #N` (a failed job pushes nothing) |

`start` is idempotent per `job_id`: a retried start returns the existing job and its `session_id`. A new `job_id` first takes the lease ref `agent-lease/<issue>` (GitHub API, atomic); if it exists the reply is `{"job_id", "status": "failed", "reason": "lease-held"}` and no work is done; the orchestrator deletes the lease on every terminal outcome. Without the unprivileged engine user the job fails with `sandbox-unavailable` (nothing runs as root). Engine order: `agy` (`--mode accept-edits`, allow-list, no `--sandbox`, exactly one round), then `agy-unrestricted` (`--dangerously-skip-permissions`, `agyuser` only), then the model loop; `agy` rounds are capped at 360 seconds, `agy-unrestricted` gets at most two rounds of 900 seconds; every round is recorded in `engine_events` (`round`, with `seconds` and `timed_out`); each commit is recorded in `engine_events` with its engine. Optional fields: `workdir` (default `app`), `install_cmd` (default `npm ci`), `max_model_usd` (default 0.50, at most 1.00). Job ids match `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` (`j-<issue>-<attempt>`, `j-pr<N>-<attempt>`).

Response to `start`: `{"job_id", "status": "running"}` immediately; the work continues in a background thread in the same session. `start` with the id of a job reported `interrupted` resumes it from the pushed branch; any other existing id returns its status unchanged. A running job rewrites its state every 30 seconds, so `stale_s` (seconds since `updated_at`) shows a stuck or dead job; a restarted server marks every job it finds `running` as `interrupted` at once. Any unexpected exception in a job ends it as `internal-error` (detail: the redacted traceback tail; the lease is released, the traceback is printed to stdout) and the server keeps answering; a request that fails answers 500 `internal_error`. revise and maintenance jobs whose `allowed_paths` match no file at the branch head fail at setup with `invalid-allowed-paths` (paths that match nothing are dropped when others do). Response to `status`:

```json
{"job_id": "j-12-1", "status": "running|succeeded|failed|timeout|cancelled", "phase": "setup|tests|implement|push|pr",
 "reason": "tests-not-red|tests-invalid|sandbox-unavailable|lease-held|lease-error|scope-violation|max-iterations|engines-exhausted|cost-cap|install-failed|branch-missing|branch-conflict|interrupted|deadline|cancelled|error|internal-error|invalid-allowed-paths|engine-unavailable",
 "detail": "...", "updated_at": "2026-10-10T12:00:00Z", "stale_s": 12, "iterations": 2, "engine": "agy|agy-unrestricted|loop", "elapsed_s": 312, "pr": {"number": 13, "url": "..."},
 "red": "...", "green": "...",
 "cost": {"model_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "coder_seconds": 312, "coder_usd": 0.0,
          "hosted_vcpu_usd_per_hour": 0.23174, "hosted_gib_usd_per_hour": 0.02738},
 "log_tail": "..."}
```

Coder steps, all in code (the CLI only edits files):

1. Install node into `/opt/node` (once per session, sha256-checked) and `agy` into `/opt/agy` (root-owned, run by `agyuser`) if missing, read both secrets from Key Vault, clone the repo, check out or create the branch. The PAT reaches git only through `GIT_ASKPASS` on clone, fetch and push (token-free script in a root-only directory, deleted after each call); it is never in `.git/config`, the remote URL, a log, or any environment agy or the tests see.
2. `feature` and `bugfix`: write `tests` and commit them alone with message `test: ...` first. Run `test_cmd` with the vitest JSON reporter; at least one new test must fail on an assertion (else `tests-not-red`); a new test that errors instead (`ReferenceError`, bad import, timeout, ...), fails to load or is not collected stops the job with `tests-invalid`, listing the first error line per broken test for the test designer. `revise` finds the existing red commit; `maintenance` has none.
3. Loop up to `max_iterations`: run the engine with the issue, spec, failing output and the scope rules; run `test_cmd`; commit and push each round. Done when green: tests pass, the red suites (or, for maintenance, the suites failing at the start) ran with every assertion passing, and the result holds after `git clean -X` and a fresh `install_cmd`. A `revise` job is not done until it has committed.
4. After every engine run: any new symlink, any change to `.git/config` or `.git/hooks`, the branch switched, or a change outside `allowed_paths`, to an existing test file (feature, bugfix, revise), to vitest config, or (maintenance) to a non-test file is a `scope-violation`: reverted, job failed, nothing further pushed. Engine-made commits are undone first so their content is checked too. Then for `feature` and `bugfix` open (or reuse) the PR with label `agent:pr` and a body with `Closes #N`, the red and green summaries, iteration count and engine.
5. Engines: `agy -p "<prompt>" --mode accept-edits` with the allow-list (no `--sandbox`: it blocked every command), killed early when it prints "Authentication required" or a quota message before editing (it blocks instead of exiting), 360 seconds per call (900 for `agy-unrestricted`), a timeout without edits retried once, a timeout with edits kept for the test run. agy, `install_cmd` and `test_cmd` run only as the unprivileged user `agyuser` with an environment built from nothing (no engine user: `sandbox-unavailable`, nothing runs as root); `agy_user` and `tests_user` are reported in status and the PR body, node is installed in `/opt/node` (root-owned, read-only for `agyuser`), leftover `agyuser` processes are killed after each agy run. If agy cannot be set up (token read, install, token or settings write, copy to `/opt/agy`; retried once) the job fails at setup with `engine-unavailable` and an `agy-unavailable` engine event naming the step; it never runs the model loop alone. Fallback after agy: a model loop on the project deployment `sdlc-default` returning whole-file edits as JSON, written only to safe relative paths inside the checkout that pass through no symlink and are within `allowed_paths`. Its prompt carries the hard rules (test files import `describe`, `expect`, `it` from `vitest`; import only files that exist), the current content of every allowed file and failing test, every `app/*/src` and `app/*/tests/helpers` file with its exported names, and a passing test as a style template; a proposal with a relative import that resolves to nothing or vitest names used without the import is rejected and asked again, nothing written. Every loop round is re-checked (tests, typecheck, lint) and kept only if strictly better (no more load errors, failures or check errors, and fewer of one); otherwise it is reverted, and two such rounds in a row stop the loop. revise and maintenance commit locally per round and push once, squashed, when green; feature and bugfix push every commit as a checkpoint. Hard stops: `deadline_s` (default and maximum 7200), `max_iterations`, `max_model_usd`, cancel.

## Gates

CI jobs, all run on every pull request with no path filters so the names always report. These six are required status checks in the branch ruleset on `main`.

| Check | Passes when |
|-------|-------------|
| `test` | lint, typecheck, unit, component and contract tests pass |
| `coverage` | line coverage across `app/` workspaces is at least 80 percent |
| `e2e` | Playwright tests pass against the built app and mock carrier |
| `gitleaks` | zero findings in the PR range and in the working tree |
| `tdd-order` | see below |
| `agent-scope` | for branches `agent/*`, every changed file is under `app/` |

`tdd-order` (script `scripts/gates/tdd_order.py`): for a branch named `agent/*`, list commits `base..head` oldest first and classify each as test-only (every changed file matches a test glob) or not. Pass when (a) the first commit is test-only, (b) no non-test commit precedes the last leading test-only commit, (c) the tip of the leading test-only commits fails `npm test` when run in a clean worktree, and that red is real: at least one assertion failure and no invalid failure (`ReferenceError`, `TypeError`, `SyntaxError`, `is not defined`, `is not a function`, `Cannot find module`, `Failed to resolve import`, a test file that fails to load) among the test files those commits added or changed, read from the vitest JSON report (result `tests-invalid-red` otherwise), and (d) later commits never modify or delete a test file that exists at that tip. A branch whose commits are all test-only (maintenance) passes with note `test-only`. Non-`agent/*` branches pass with note `not-agent-branch`.

Test globs: `**/*.test.ts`, `**/*.test.tsx`, `**/*.spec.ts`, `app/e2e/**`, `**/tests/**`, `**/__fixtures__/**`.

The orchestrator merges a PR only when all of the following hold on the PR head sha: all six checks `success`, a review marker `<!-- sdlc-review:v1 {"verdict":"approve","head":"<sha>"} -->` from the reviewer agent for exactly that sha, the PR and its issue are owner-authored, cost is under the cap, the branch is `agent/*` or the PR is labelled `maintenance:test-repair`, and every file the PR changes (including rename sources) is under `app/`. The last rule applies to every PR the orchestrator merges, because for `pull_request` events GitHub runs the workflow files from the PR head, so a PR touching `.github/` could weaken its own checks; a violation escalates `escalated:build-failed` at once. Check runs GitHub ties to the PR win over other runs on the same sha (a fork PR cannot override them). Merge method is a merge commit (keeps commit order visible on `main`). The ruleset enforces the six checks again server-side with no bypass actors, so the orchestrator cannot merge around them.

## Release

After a merge: the release-notes agent writes notes from the PR title, body and commits. The orchestrator computes the next version from existing tags (`vMAJOR.MINOR.PATCH`; feature bumps minor, bugfix and maintenance bump patch; first tag is `v0.1.0`), creates the tag on the merge commit and a GitHub Release with the notes, labels `stage:released` and closes the issue.

## Metrics

`metrics.json` (branch `metrics`), schema version 1:

```json
{
  "version": 1, "generated_at": "...", "repo": "stevengonsalvez/foundry-autonomous-sdlc",
  "totals": {"usd": 0.0, "issues": 0, "released": 0},
  "issues": [{
    "number": 12, "title": "...", "scenario": "a", "type": "feature", "outcome": "released|escalated|open",
    "opened_at": "...", "closed_at": "...", "stages": [{"stage": "stage:ready", "entered_at": "...", "seconds": 120}],
    "severity": "s2", "owner": "api", "resolution_seconds": 3600,
    "pr": 13, "release": "v0.2.0", "quality_score": 86, "coder_engine": "agy",
    "cost": {"usd": 0.0123, "model_usd": 0.0123, "coder_usd": 0.0, "calls": 9},
    "gates": {"test": "success", "coverage": "success", "e2e": "success", "gitleaks": "success", "tdd-order": "success", "agent-scope": "success"}
  }],
  "gate_pass_rates": {"test": {"pass": 3, "fail": 1}}
}
```

Additions to schema version 1 (all optional for readers): `totals.escalated`, `totals.orchestrator_usd`; per entry `kind` (`issue` or `pr`; the maintenance PR has `number: null`, `pr` set and scenario `d-maintenance`), `escalation`, `cost.coder_model_usd`, `deferred` (the transient error that deferred the object this tick, else null; `totals.deferred` counts them), `gate_attempts` (each gate's conclusions per evaluated head sha, oldest first: first element is the first attempt, last is the eventual result); per gate in `gate_pass_rates`, `first_pass` and `first_fail`. The stage the object is in now has `seconds: 0` and `in_progress: true`.

Dashboard panels: cycle time per stage (median and per issue), defect owner and resolution time, cost per issue (table plus total against the 25 USD cap), gate pass rates (first-attempt and eventual).

## Ledger and control center

```
┌──────────────┐ ticket.updated   ┌──────────────┐ one commit  ┌───────────────┐ poll 30 s  ┌─────────────┐
│ orchestrator │ tick.finished    │ sdlc-ledger  │────────────▶│ branch state  │◀───────────│ control     │
│ (every tick) │─────────────────▶│ hosted agent │             │ state.json    │ raw GitHub │ center      │
└──────────────┘  Invocations     │ fold + guard │◀── reads ───│ events.jsonl  │ + API      │ (read-only) │
┌──────────────┐ deploy.json      │ code derives │  GitHub:    │ archive.json  │            └─────────────┘
│ CD workflow  │ (branch deploy)  │ LLM only     │  issues, PRs│               │
│ cd.yml       │─ reconciled ────▶│ summarises   │  deploy, metrics            │
└──────────────┘                  └──────────────┘                             │
```

**Rule of three.** GitHub is the source of truth, the orchestrator and CD say what happened, the ledger is the only writer of branch `state`. Anything an event missed is repaired by `reconcile`, which rebuilds each ticket from its state comment, PR, commits and the CD record.

### Events (`events.jsonl`, one JSON object per line, schema version 1)

`{"v":1,"id":"<16 hex>","at":"<ISO UTC>","type":"...","issue":12|null,"source":"orchestrator|reconcile|cd|ledger|operator","data":{...}}`. The id is a digest of the content, so the same event sent twice is dropped. Every string is cleaned on the way in (control characters removed, token-shaped strings replaced by `[REDACTED]`, length bounded); an event over 96 KB, a batch over 500 or a payload that fails its schema is rejected whole.

| Type | Data | Sent by |
|------|------|---------|
| `ticket.updated` | `ticket`: the full ticket record (below) after any change to the object in the tick | orchestrator (one per object per tick, the latest), reconcile |
| `tick.finished` | lock, per-object results, errors, model calls, spend of the tick | orchestrator, when something happened or every ~9 minutes as a heartbeat |
| `metrics.observed` | the orchestrator's own spend estimate (`totals` of `metrics.json`) | orchestrator, reconcile |
| `env.changed` | the `deploy.json` snapshot written by the CD workflow | reconcile (reads branch `deploy`) |
| `billing.observed` | what Azure Cost Management billed for the resource group, month to date, by meter, with the read time | ledger (Cost Management Reader), at most every 6 hours |
| `ledger.invoked` | the ledger's own compute for one call: seconds, USD, issues touched, mode | ledger |

The orchestrator sends the batch once at the end of a tick (`HostedEmitter`: one Invocations call, session reused). It is best effort: a failure is a note in the tick report, never a failed tick. Once an hour (`metrics.json` key `ledger.reconciled_at`) the call carries `reconcile: true`.

### Ticket record and board stages

The record (`ledger/model.py`, pure functions) is derived from the state comment, issue metadata, PR facts and the CD record. Board stage mapping:

| Board stage | `stage:*` label |
|-------------|-----------------|
| backlog | none (issue opened, nothing done yet) |
| refining | `needs-refinement`, `ready` (a scored requirement still waiting for the feasibility call) |
| feasible | `feasible` |
| tests | `tests-written` |
| building | `building` |
| review | `in-review` |
| staging | `merged`, `released` while the change is on `/staging/` or waiting for CD |
| prod | `released` and the CD record says the change is live at the site root |
| escalated | any `escalated:*` label, or a release rolled back by CD (`escalated:deploy-failed`) |

A change released before CD existed was published to the root by `pages.yml` straight from `main`; the ledger shows it in prod with one hop labelled `legacy-publish`, never as a fake staging pass.

Fields: `issue`, `kind` (`issue` or `pr`), `title`, `type`, `scenario`, `url`, `opened_at`, `closed_at`, `updated_at`, `stage`, `sdlc_stage`, `env` (`none`, `staging`, `prod`, `rolled-back`), `escalation` (`label`, `reasons`, `attempts`, `tried`, `evidence_url`), `stage_history` (backlog first, each with `at` and `seconds`), `pr`, `commits`, `release`, `hops` (environment hops), `gates` (the six CI checks plus `smoke` and `soak`), `gate_history`, `cost` (`usd`, `model_usd`, `coder_usd`, `ledger_usd`, tokens, per-agent rows, `cap_used_pct` against 1 USD), `agent_runs`, `coder`, `qa` (refinement questions and answers, answers labelled as the simulated product owner), `reviews`, `ci_triage`, `quality`, `triage`, `feasibility`, `summary`, `flags`, `digest`. A model writes only `summary`; it is shown only while the ticket's digest still matches, and is dropped when it contains a number, link or markup that the facts do not (`ledger/summary.py`).

### state.json

Top level: `version` (1), `repo`, `generated_at`, `updated_at`, `seq`, `board_stages`, `tickets`, `environments` (`staging`, `prod`, `previous_prod`, `history`, `rollbacks`, `source`), `agents` (the 10 agents and the ledger: state, last activity, calls, tokens, USD, errors, retries, current object, lock holder), `cost` (`totals`, `caps`, `billing`, `gap`, `metrics`, `ledger`), `flow` (lead time issue to prod, stage medians, first-attempt gate pass, defects, change failure rate per release, counts), `archived`, `ledger` (event count, last ingest, mode, last tick, recent problems). Closed tickets older than 30 days move to `archive.json`.

`cost.gap` is the number the demo must not hide: `billed_usd` (Azure Cost Management, with its read time), `ledger_usd` (the orchestrator's estimate plus the ledger's own compute), their difference and ratio. The run of 2026-10-10 is the example: the ledger said 1.86 USD, Azure billed 4.80 USD when first read and 13.02 USD when read again on 2026-10-11, after the lagging usage had posted.

### The hosted agent `sdlc-ledger`

Invocations protocol, 0.25 vCPU, 0.5 GiB, idle timeout 2 minutes (the platform minimum): it is woken by a request and its compute is deprovisioned after the idle timeout, so between events it bills nothing. Ops: `ingest` (`events`, optional `reconcile`, `billing`), `reconcile` (optional `issue`), `rebuild` (state.json from events.jsonl), `status`. Each write is one commit built through the git data API and moved onto `state` without force; a lost race re-reads and folds again (up to 4 attempts). A missing or corrupt `state.json` is rebuilt from `events.jsonl`. Its roles: `Key Vault Secrets User` on `github-pat`, `Foundry User` on the project (model summaries on `sdlc-default`), `Cost Management Reader` on the resource group.

Its own compute is priced like the other hosted agents (`cost.ledger_call_usd`: wall time plus the idle tail at 0.25 vCPU and 0.5 GiB, about 0.0027 USD for a 10 second call), recorded as `ledger.invoked`, added to `metrics.json` `totals.ledger_usd` and `totals.usd` (so the 22 USD halt counts it) and shown in the cost view and per ticket.

**Fallback.** `LEDGER_MODE=inline` runs the same `Ledger` class in the orchestrator process (no second agent, no extra compute meter, `mode: "inline"` in `state.json`); `LEDGER_MODE=off` sends nothing. The event and state schema are identical in all three modes. `deploy_agents.py hosted --ledger-mode inline` selects it and deploys no ledger agent.

### Control center (`apps/control-center/`)

Static HTML, CSS and ES modules, inline SVG, no build. Eight views: ticket board, ticket detail, cost, environments, agent activity and health, escalation queue, flow metrics, questions-back and review trail. It holds no token and makes no write call; ticket creation is a link to the GitHub issue form. Freshness: it polls `raw.githubusercontent.com/.../state/state.json` every 30 seconds (that CDN caches for up to 300 seconds, measured) and, while GitHub API budget allows (60 unauthenticated requests per hour per IP), the contents API (cached 60 seconds) and the open-issues list, so a new issue appears as a "waiting for ledger" backlog card within about a minute and the ledger's own record replaces it later. A banner marks the data stale after 10 minutes. All text from GitHub or a model is inserted as text and links are limited to this repository.

## Prompt agents

All run on the `sdlc-default` deployment (gpt-5-mini, GlobalStandard). All treat issue, PR and file text as untrusted data inside nonce-delimited tags (existing `sdlc_agents/call.py` pattern). Structured output is enforced by JSON schema and re-validated in code.

| Agent | Input | Output |
|-------|-------|--------|
| `sdlc-req-gate` | issue title and body (plus clarifications) | `score` 0..100 with per-criterion scores (clear goal, testable acceptance criteria, scope, edge cases), `questions[]` |
| `sdlc-product-owner` | issue and the questions | `answers[]`; every output is posted under the label "simulated product owner" |
| `sdlc-feasibility` | issue and spec; read-only GitHub MCP to inspect the repo | `suitable`, `reasons[]`, `risk` |
| `sdlc-test-designer` | spec and repo files via read-only MCP | `tests[]` (`path`, `content`), `rationale` |
| `sdlc-reviewer` | issue, spec, PR diff, check results | `verdict` approve or request-changes, `findings[]` with severity |
| `sdlc-triage` | bug report | `severity` s1..s4, `owner` web, api or carrier-mock, `summary`, `suspected_area` |
| `sdlc-ci-triage` | failing check log, diff and the repo's test file list | `cause` stale-test or real-bug, `explanation`, `test_files[]` |
| `sdlc-release-notes` | PR title, body, commits | markdown notes |
