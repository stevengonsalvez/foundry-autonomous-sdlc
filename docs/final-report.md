# Final report

An issue filed in this public repository is scored, refined, judged for agent suitability, given failing tests first, built by a coding agent in a Foundry hosted agent, reviewed by an independent agent, merged and released, with no human step. This report states what was proven, with links.

## Success criteria

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1a | A well-formed feature goes issue to release | Met | Issue [#12](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/issues/12), PR [#13](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/pull/13), release [v0.1.0](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/releases/tag/v0.1.0). Second run: [#23](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/issues/23), PR [#28](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/pull/28), [v0.2.0](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/releases/tag/v0.2.0) |
| 1b | A vague issue is bounced under 80 percent, answered by a labelled simulated product owner, re-scored and built | Met | Issue [#24](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/issues/24) (timeline `needs-refinement`, `ready`, ..., `released`), PR [#29](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/pull/29), [v0.3.0](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/releases/tag/v0.3.0) |
| 1c | A task that is not agent-suitable is escalated with reasons | Met | Issue [#17](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/issues/17), label `escalated:not-agent-suitable`, reasons in its escalation comment (production keys, DNS and firewall changes, vendor sign-off) |
| 1d | A bug is triaged with severity and owner, a failing regression test comes first, the fix merges | Met | Issue [#25](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/issues/25) (`severity:s3`, `owner:api`), PR [#26](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/pull/26), [v0.1.1](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/releases/tag/v0.1.1) |
| 1d | One deliberately broken test is repaired by the maintenance agent | Met | PR [#40](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/pull/40): the owner changed the home heading, the maintenance flow repaired three stale test files (vitest and the Playwright spec), six gates green, review approved, [v0.3.1](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/releases/tag/v0.3.1). The live app now reads "Track a parcel" |
| 2 | Per agent PR: tests committed before implementation, CI green, coverage at least 80 percent, review approved before the orchestrator merged, release notes and tag | Met | Commit tables, six check results, review verdicts and release links per issue in [`docs/evidence.md`](evidence.md). The `tdd-order` check is a script (`scripts/gates/`) that fails a PR whose first commit is not tests-only and red for an assertion. App coverage is 99.6 percent of lines (162 tests, 18 files) against the 80 percent gate |
| 3 | Fresh clone reproduces the stack, gitleaks finds nothing in full history, spend under 5 USD with a per-issue table, Pages app and dashboard live | Met | Fresh clone applied 15 resources and destroyed them with no group left ("Fresh clone reproduction" in [`docs/findings.md`](findings.md)). `gitleaks` 8.30.1 over all commits: no leaks. Spend 1.86 USD of 5 (model calls, coder compute and orchestrator compute), per-issue table on the dashboard and in `docs/evidence.md`. App <https://stevengonsalvez.github.io/foundry-autonomous-sdlc/> and dashboard <https://stevengonsalvez.github.io/foundry-autonomous-sdlc/dashboard/> both return 200 |
| 4 | The final deliverable runs without errors | Met | The runbook steps were run from a fresh clone (apply, destroy) and on the live stack (deploy, enable, scenarios); CI is green on `main` (12 checks); 754 agent tests, 223 script tests and 162 app tests pass |
| 5 | Proof: screenshot, test output, URL | Met | Screenshots in [`docs/proof/`](proof/), test and gate output in `docs/evidence.md`, live URLs above |

## Proof

- Screenshots: `docs/proof/app-home-desktop.png`, `app-home-mobile.png`, `app-parcel-desktop.png`, `dashboard-desktop.png`, `dashboard-mobile.png`, all taken from the published Pages site after the last release.
- Traces: `docs/evidence.md` is generated from live GitHub data by `scripts/collect_evidence.py`. It lists every issue and maintenance PR, including the runs that failed along the way.
- Releases: v0.1.0, v0.1.1, v0.2.0, v0.3.0, v0.3.1.

## Files

- `app/`: the parcel tracker (`core`, `carrier-mock`, `api`, `web`, `e2e`).
- `agents/`: orchestrator logic, prompt agent definitions, the coder runtime, hosted agent entry points and their tests.
- `infra/terraform/`: Foundry, Key Vault, observability and budget modules, plus a remote-state bootstrap.
- `scripts/`: deploy, repo setup, merge gates, scenario runner, evidence collector, Pages assembly.
- `dashboard/`, `scenarios/`, `docs/` (architecture, decisions, findings, runbook, evidence, this report), `.github/workflows/`.

## Run, test, deploy

All steps are in [`docs/runbook.md`](runbook.md). In short: `az login`, `terraform apply` from `infra/terraform`, load the two secrets into Key Vault, `uv run --project agents python scripts/deploy_agents.py all`, `python scripts/setup_repo.py --phase bootstrap` then `--phase protect`, enable the routine with `deploy_agents.py routine --enable`, then `python scripts/run_scenarios.py` to file the scenario inputs. Tests: `cd agents && uv run pytest`, `python -m pytest scripts/tests`, `cd app && npm test`.

## Decisions

Recorded in [`docs/decisions.md`](decisions.md): D1 fresh stack and state, D2 orchestrator as code in a hosted agent, D3 schedule polling instead of the GitHub trigger, D4 gates enforced three times, D5 merge commits so test-first order stays visible, D6 owner-only issues, D7 the coder edits files and code does everything else, D8 public endpoints with Entra-only auth, D9 remote-built dependencies, D10 coder isolation and the owner decision to allow skipped permissions only as an unprivileged user.

## Honest accounting

- Seventeen issues and PRs were escalated, most of them early attempts while the system was being hardened (rate limits, the coder editing without permissions, stale repair scope). They are all listed in `docs/evidence.md`, and the cause of each class is in `docs/findings.md`. The maintenance repair needed four live attempts (PRs #27, #33, #36, #38) and two orchestrator fixes (test file grounding, reviewer context) before PR #40 merged.
- Highest single-item cost: 0.14 USD (PR #27), below the 1 USD per issue cap. Total 1.86 USD, below the 4.50 USD halt and the 5 USD limit. The figures are the orchestrator's own accounting from token counts and list prices, not an Azure invoice, which lags.

## Known limitations

- Commits pushed from the coder sandbox are not signed (no signing key in the sandbox); the owner's own commits are.
- The GitHub token the coder uses can reach every repository the owner's PAT covers, not only this one. The MCP connection for prompt agents is read-only.
- The `agy` login is a personal plan token; whether the plan terms allow this use is unverified. The model-loop fallback exists but is the last resort.
- Key Vault and Foundry use public endpoints with Entra-only auth; private networking is out of scope.
- A disabled `probe-tick` routine stub cannot be deleted (service limitation); the `sdlc-tick` routine is disabled now that the demo is complete.
- Open items: a Renovate onboarding PR from a non-owner, which the orchestrator ignores by design, and issue #17 left open as the escalation example.
