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

## Roles and secrets

| Secret | Where it lives | Who reads it |
|--------|----------------|--------------|
| `github-pat` | Key Vault secret | Orchestrator and coder, with their own managed identity (secret-scope `Key Vault Secrets User`). Prompt agents reach GitHub only through the `github-mcp` project connection. |
| `agy-cli-token` | Key Vault secret | Coder only. Written to `~/.gemini/antigravity-cli/antigravity-oauth-token`, mode 600. |

The PAT belongs to the repo owner `stevengonsalvez`. It is used only against `stevengonsalvez/foundry-autonomous-sdlc`; every client in this repo hard-codes that repo and refuses any other.

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
- Escalation (terminal): `escalated:not-agent-suitable`, `escalated:requirements`, `escalated:review-failed`, `escalated:cost-cap`, `escalated:build-failed`, `escalated:agent-error`
- Type: `type:feature`, `type:bug`, `type:maintenance`
- Bug triage: `bug:triaged`, `severity:s1`, `severity:s2`, `severity:s3`, `severity:s4`, `owner:web`, `owner:api`, `owner:carrier-mock`
- PR: `agent:pr` (set on every PR the coder opens), `maintenance:test-repair`

An issue is acted on only if its author is the repo owner. Anything else is ignored with no spend.

The object type comes from the `type:*` label (default `type:feature`); the scenario letter from the body marker `<!-- scenario: a|b|c|d|d-maintenance -->` (when absent, metrics infer it). A bug is triaged before its requirement is scored. The stale-test PR (owner-authored, labelled `maintenance:test-repair`) is its own object: its state comment lives on the PR, its type is `maintenance`, and it only enters the pipeline after its `test` check failed with no test file in the diff.

### State comment

Each issue (or maintenance PR) has exactly one bot comment starting with `<!-- sdlc-state:v1` followed by JSON and `-->`, then a human readable summary. The orchestrator edits it in place. The JSON is the source of truth for the stage; labels are a projection the orchestrator keeps in sync. Only comments authored by the owner identity count. Characters `<`, `>` and `&` in the JSON are written as `<`, `>`, `&`, so text inside can never close the comment. Unknown keys are preserved; a version above 1 is refused, never overwritten. Beyond the example below the orchestrator records `quality.history`, `ci_triage`, `tests` (file list; contents live in the `<!-- sdlc-tests:v1` comment), `gate_history` (results per evaluated head), `release.pending` (a reserved tag), `escalation`, `failures` (consecutive failures of one step; 3, or 6 for coder polls, escalate) and `cost.coder_model_usd`. A failing step rolls the state back to its last saved version, keeping only its spend and the failure count.

Failures are classified. Transient ones (HTTP 408, 429, 5xx, `rate_limit_exceeded`, timeouts, dropped connections, GitHub rate limits) are retried inside the tick with exponential backoff and jitter, honouring `Retry-After`, never past the tick's wall budget; if they persist the object is deferred: left exactly as it was (no label, comment or failure count change; spend already incurred is still saved), reported as `result: "deferred"` in the tick report and as `deferred` in metrics. Only non-transient failures count: an agent answer that fails its schema or checks after one repair retry (the validation error is sent back to the agent), a refusal or incomplete answer, or a contract violation. Three consecutive counted failures of a prompt agent step end in `escalated:agent-error`; `escalated:not-agent-suitable` is reserved for a real `suitable: false` verdict from the feasibility agent. The three MCP-using agents get one tool, `get_file_contents` (it also lists directories), because every listed tool's schema is billed as input tokens on every call. The tick report lists input and output tokens per model call.

```json
{
  "version": 1, "issue": 12, "type": "feature", "scenario": "a",
  "stages": [{"stage": "stage:ready", "at": "2026-10-10T12:00:00Z"}],
  "quality": {"score": 86, "rounds": 1, "questions": []},
  "feasibility": {"suitable": true, "reasons": []},
  "triage": {"severity": "s2", "owner": "api"},
  "coder": {"job_id": "j-12-1", "session_id": "...", "engine": "agy", "started_at": "...", "iterations": 3},
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

Every LLM call is made with the cumulative issue cost checked first. Cost over 1 USD per issue puts the object in `escalated:cost-cap`. Total spend is tracked in `metrics.json` (`totals.usd`, which never decreases) and the loop halts new work at 4.50 USD. Issue cost counts prompt agent tokens, coder compute (2 vCPU, 4 GiB: 0.2706 USD per hour of reported job time) and the coder's own model spend; each tick also adds the orchestrator's compute (1 vCPU, 2 GiB, tick seconds plus the 2 minute idle timeout) to `totals.orchestrator_usd` and `totals.usd`. Merged work is always released: past a cap the notes are written without a model call. Every coder job carries `deadline_s` 7200 and `max_model_usd` = what is left under the issue cap (at most 0.50); a job reported `interrupted` is started again with the same job id (at most three times).

GitHub port additions used by the orchestrator: `create_commit(message, *, parent_sha)` (the lock ref points at a fresh empty commit, so its tip time is the lock time), `get_check_log(sha, name)` (ci-triage input), `list_pull_files(number)` (merge gate), and `CheckRun.pull_requests` (runs GitHub ties to a PR).

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
| `maintenance` | the PR head ref (any branch except `base`, for example `chore/update-home-heading`) | `pr: {"number": 14}`, `tests: []`, `allowed_paths` = the test files named by ci-triage; `issue` optional | only those test files change (`test: repair stale tests for #N`), pushed to the existing PR |

`start` is idempotent per `job_id`: a retried start returns the existing job and its `session_id`. Optional fields: `workdir` (default `app`), `install_cmd` (default `npm ci`), `max_model_usd` (default 0.50, at most 1.00). Job ids match `[A-Za-z0-9][A-Za-z0-9._-]{0,63}` (`j-<issue>-<attempt>`, `j-pr<N>-<attempt>`).

Response to `start`: `{"job_id", "status": "running"}` immediately; the work continues in a background thread in the same session. `start` with the id of a job reported `interrupted` resumes it from the pushed branch; any other existing id returns its status unchanged. Response to `status`:

```json
{"job_id": "j-12-1", "status": "running|succeeded|failed|timeout|cancelled", "phase": "setup|tests|implement|push|pr",
 "reason": "tests-not-red|scope-violation|max-iterations|engines-exhausted|cost-cap|install-failed|branch-missing|branch-conflict|interrupted|deadline|cancelled|error",
 "detail": "...", "iterations": 2, "engine": "agy|loop", "elapsed_s": 312, "pr": {"number": 13, "url": "..."},
 "red": "...", "green": "...",
 "cost": {"model_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "coder_seconds": 312, "coder_usd": 0.0,
          "hosted_vcpu_usd_per_hour": 0.10934, "hosted_gib_usd_per_hour": 0.01298},
 "log_tail": "..."}
```

Coder steps, all in code (the CLI only edits files):

1. Install node into `/opt/node` (once per session, sha256-checked) and `agy` into `/opt/agy` (root-owned, run by `agyuser`) if missing, read both secrets from Key Vault, clone the repo, check out or create the branch. The PAT reaches git only through `GIT_ASKPASS` on clone, fetch and push (token-free script in a root-only directory, deleted after each call); it is never in `.git/config`, the remote URL, a log, or any environment agy or the tests see.
2. `feature` and `bugfix`: write `tests` and commit them alone with message `test: ...` first. Run `test_cmd` with the vitest JSON reporter; at least one assertion in the new tests must fail and every new test file must load, else `failed` with reason `tests-not-red`. `revise` finds the existing red commit; `maintenance` has none.
3. Loop up to `max_iterations`: run the engine with the issue, spec, failing output and the scope rules; run `test_cmd`; commit and push each round. Done when green: tests pass, the red suites (or, for maintenance, the suites failing at the start) ran with every assertion passing, and the result holds after `git clean -X` and a fresh `install_cmd`. A `revise` job is not done until it has committed.
4. After every engine run: any new symlink, any change to `.git/config` or `.git/hooks`, the branch switched, or a change outside `allowed_paths`, to an existing test file (feature, bugfix, revise), to vitest config, or (maintenance) to a non-test file is a `scope-violation`: reverted, job failed, nothing further pushed. Engine-made commits are undone first so their content is checked too. Then for `feature` and `bugfix` open (or reuse) the PR with label `agent:pr` and a body with `Closes #N`, the red and green summaries, iteration count and engine.
5. Engines: `agy -p "<prompt>" --mode accept-edits --sandbox` (edits only; shell commands are denied, so code runs the tests), killed early when it prints "Authentication required" or a quota message before editing (it blocks instead of exiting), 600 seconds per call, a timeout without edits retried once. agy, `install_cmd` and `test_cmd` run as the unprivileged user `agyuser` with an environment built from nothing when the sandbox allows `useradd` (else as root with the same environment); `agy_user` and `tests_user` are reported in status and the PR body, node is installed in `/opt/node` (root-owned, read-only for `agyuser`), leftover `agyuser` processes are killed after each agy run. Fallback: a model loop on the project deployment `sdlc-default` returning whole-file edits as JSON, written only to safe relative paths inside the checkout that pass through no symlink and are within `allowed_paths`. Hard stops: `deadline_s` (default and maximum 7200), `max_iterations`, `max_model_usd`, cancel.

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

`tdd-order` (script `scripts/gates/tdd_order.py`): for a branch named `agent/*`, list commits `base..head` oldest first and classify each as test-only (every changed file matches a test glob) or not. Pass when (a) the first commit is test-only, (b) no non-test commit precedes the last leading test-only commit, (c) the tip of the leading test-only commits fails `npm test` when run in a clean worktree (red evidence). A branch whose commits are all test-only (maintenance) passes with note `test-only`. Non-`agent/*` branches pass with note `not-agent-branch`.

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

Dashboard panels: cycle time per stage (median and per issue), defect owner and resolution time, cost per issue (table plus total against the 5 USD cap), gate pass rates (first-attempt and eventual).

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
| `sdlc-ci-triage` | failing check log and diff | `cause` stale-test or real-bug, `explanation`, `test_files[]` |
| `sdlc-release-notes` | PR title, body, commits | markdown notes |
