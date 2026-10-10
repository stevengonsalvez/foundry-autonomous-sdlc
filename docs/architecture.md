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
- Escalation (terminal): `escalated:not-agent-suitable`, `escalated:requirements`, `escalated:review-failed`, `escalated:cost-cap`, `escalated:build-failed`
- Type: `type:feature`, `type:bug`, `type:maintenance`
- Bug triage: `bug:triaged`, `severity:s1`, `severity:s2`, `severity:s3`, `severity:s4`, `owner:web`, `owner:api`, `owner:carrier-mock`
- PR: `agent:pr` (set on every PR the coder opens), `maintenance:test-repair`

An issue is acted on only if its author is the repo owner. Anything else is ignored with no spend.

### State comment

Each issue has exactly one bot comment starting with `<!-- sdlc-state:v1` followed by JSON and `-->`, then a human readable summary. The orchestrator edits it in place.

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

Every LLM call is made with the cumulative issue cost checked first. Cost over 1 USD per issue puts the object in `escalated:cost-cap`. Total spend is tracked in `metrics.json` (`totals.usd`) and the loop halts new work at 4.50 USD.

## Coder contract (Invocations protocol)

Request bodies (JSON). The platform issues the session id on the first call; callers store it and send `agent_session_id` on later calls.

```json
{"op": "start", "job": {
  "job_id": "j-12-1", "repo": "stevengonsalvez/foundry-autonomous-sdlc", "base": "main",
  "branch": "agent/issue-12", "mode": "feature",
  "issue": {"number": 12, "title": "...", "body": "..."},
  "spec": {"acceptance_criteria": ["..."], "notes": "..."},
  "tests": [{"path": "app/api/tests/parcel.test.ts", "content": "..."}],
  "test_cmd": "npm test", "max_iterations": 5, "deadline_s": 21600, "allowed_paths": ["app/"]}}
{"op": "status", "job_id": "j-12-1"}
{"op": "cancel", "job_id": "j-12-1"}
```

Response to `start`: `{"job_id", "status": "running"}` immediately; the work continues in a background thread in the same session. Response to `status`:

```json
{"job_id": "j-12-1", "status": "running|succeeded|failed|timeout|cancelled", "phase": "setup|tests|implement|push|pr",
 "iterations": 2, "engine": "agy|loop", "elapsed_s": 312, "pr": {"number": 13, "url": "..."}, "log_tail": "..."}
```

Coder steps, all in code (the CLI only edits files):

1. Install node and `agy` into `$HOME` if missing, read both secrets from Key Vault, clone the repo with the PAT (never written to disk in the remote URL), create the branch from `base`.
2. `feature` and `bugfix`: write `tests` and commit them alone with message `test: ...` first. Run `test_cmd`; at least one test must fail and every test file must load (no collection errors), else return `failed` with reason `tests-not-red`. `maintenance`: the branch already exists, only files matching test globs may change, no new red commit.
3. Loop up to `max_iterations`: run `agy -p` with the issue, spec, failing output and the rule "make the committed tests pass, never edit the test files, touch only `allowed_paths`"; run `test_cmd`; commit implementation changes with `feat:` or `fix:`. Stop on green.
4. Reject any diff outside `allowed_paths` (revert and fail). Push, open the PR with label `agent:pr`, body containing `Closes #N`, the red and green test output, and iteration count. For `maintenance`, push to the existing branch instead.
5. Hard stops: `deadline_s` (default 21600, six hours), `max_iterations`, and the engine fallback chain `agy`, then an Agent Framework style loop on the project model deployment (`sdlc-default`), recording which engine produced the result.

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

The orchestrator merges a PR only when all of the following hold on the PR head sha: all six checks `success`, a review marker `<!-- sdlc-review:v1 {"verdict":"approve","head":"<sha>"} -->` from the reviewer agent for exactly that sha, the PR and its issue are owner-authored, and cost is under the cap. Merge method is a merge commit (keeps commit order visible on `main`). The ruleset enforces the six checks again server-side with no bypass actors, so the orchestrator cannot merge around them.

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
