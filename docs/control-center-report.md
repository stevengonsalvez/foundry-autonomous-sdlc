# Control center, continuous deployment and the state-keeper: final report

What was added to the autonomous SDLC demo, what was proven live on 2026-10-11, and what is not true yet. Every claim has a link, a run, or a command.

```
 issue ─▶ orchestrator ─events─▶ sdlc-ledger (hosted) ─one commit─▶ branch state ─▶ /control-center/
 merge ─▶ CI ─▶ /staging/ ─▶ smoke ─▶ 10 min soak ─▶ prod (site root)   |   any failure: rollback + flag
```

## Success criteria

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | A new issue appears on the board within 60 s and moves through every stage with timestamps, detail, cost, gates, questions-back and environment hops, across all 8 views | **Partly met, live; the stages after the first four were not re-run** | Issue [#45](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/issues/45) was opened on the live site and appeared as a "waiting for ledger" card after 58.8 s ([screenshot](proof/live-new-issue-waiting-for-ledger.png)). The real orchestrator (run on the maintainer's machine against the real prompt agents) then took it through backlog, refining (4 simulated product owner answers), ready and `escalated:not-agent-suitable`, and the hosted ledger recorded every transition with the orchestrator's timestamps. The later stages (tests, building, review, staging, prod) were **not** run for a new ticket: no coder job could be paid for (see Spend). They are shown for real tickets from the first run (#12, #23, #24, #25, PR #40) that went through every stage, and for the CD hops of the merge of PR #44 and the drill below. All 8 views render live ([screenshots](proof/)). Intake timing needs a clean re-measure: later probes read 59.2 s and 59.5 s while my own testing had drained this IP's 60 requests per hour GitHub budget, which stretches the poll cadence |
| 2 | A merged PR reaches /staging/ and then prod after Playwright smoke plus a 10 minute soak with no human step; a forced smoke failure rolls back and shows as escalated on Environments and Escalation | **Met** | Merge of [PR #44](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/pull/44): [CD run 38178080036](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/actions/runs/38178080036), plan, build, stage, smoke on the live `/staging/` URL, soak 10 minutes, promote, tag `prod/20261011-220522-641cb02`, live root `build.json` equal to the merge. Forced failure: [run 38180836579](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/actions/runs/38180836579) (`inject_fault=smoke` broke the built heading): smoke failed, soak and promote skipped, rollback restored `/staging/` to prod's artifact, prod and the tag list unchanged, [PR #46](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/pull/46) labelled `escalated:deploy-failed` with a comment. The control center showed it on [Environments](proof/live-environments-after-rollback.png) (gate that failed, ticket flagged, run link, change failure rate 33 percent), [Escalations](proof/live-escalations-after-rollback.png) and the [ticket](proof/live-ticket-rolled-back.png). A clean re-run ([run 38181279359](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/actions/runs/38181279359), 2 minute soak) promoted the same commit, tagged `prod/20261011-224538-8137c60` and took the failure label off the PR |
| 3a | Per-ticket cost matches the orchestrator ledger within 5 percent | **Met** | A ticket's cost is the orchestrator's own figure. Checked on the live data: 23 tickets, worst difference 0.012 percent (state.json against `metrics.json`). The ledger's own compute is a separate field (`ledger_usd`) that counts toward the cap in `total_usd` |
| 3b | Billed versus ledger gap shown, not hidden | **Met** | [Cost view](proof/live-cost-billed-vs-ledger.png): Azure billed 13.02 USD, ledger estimate 1.87 USD, 7.0x, billing read time, meter breakdown, banner. Read live by the ledger from Azure Cost Management |
| 3c | `sdlc-ledger` runs as a hosted Foundry agent writing only to branch `state` | **Met** | Hosted agent, version 7, 0.25 vCPU, 0.5 GiB, 2 minute idle. Its client refuses any repository but this one and it writes through the git data API onto `state` only. Last commits on [branch state](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/commits/state). Whether its compute scales to zero is by platform design (deprovisioned after the idle timeout); Azure has not posted any usage for 2026-10-11 yet, so the bill cannot confirm it today |
| 3d | gitleaks 0 findings across full history | **Met** | CI `gitleaks` check passes on every PR and on main (8.30.1); a local run (8.11) over the history reports none. Local working-tree hits are only ignored `.pyc` caches |
| 3e | Total Azure spend stays under 5 USD | **Not met, and not caused by this work** | Azure had billed 13.02 USD for the resource group by 2026-10-11, before work began (the first run's report said 4.80 USD because Cost Management lags). See Spend |
| 3f | Explainer system diagrams reflect what shipped | **Met** | [docs/explainer/foundry-autonomous-sdlc.html](explainer/foundry-autonomous-sdlc.html), 10 diagrams including the CD flow, the data plane and the cost gap |
| 4 | Final deliverable runs without errors | **Met** | 829 agent tests, 461 script tests, 164 app tests, 66 dashboard tests, 92 control center tests, CI green on PRs #44 and #46 and on main, three live CD runs |
| 5 | Proof | **Met** | Links above, screenshots in [docs/proof/](proof/) |

## Spend, and the decision behind it

Azure Cost Management, resource group `rg-fsdlcd-demo`, month to date, read 2026-10-11 20:00 UTC: **13.02 USD** (9.83 GBP, all of it on 2026-10-10: Container Apps 6.74, Foundry Tools 5.97, models 0.30). The 4.80 USD in the first run's report was an early read. So the 5 USD cap was already exceeded, and the 4.50 USD halt, which reads the orchestrator's own estimate (1.86 USD), never protected it.

With no human to re-authorise spend, this work:

- ran no orchestrator tick on the hosted agent and no coder job; the routine `sdlc-tick` stayed disabled;
- ran four orchestrator ticks on the maintainer's machine for issue #45 only (prompt-agent tokens, about 0.007 USD by the ledger's price list), emitting to the hosted ledger;
- deployed `sdlc-ledger` at the smallest size and called it only when there was something to say. The ledger's own meter at the end of the work is in `cost.ledger` of [state.json](https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/state/state.json): about 0.0027 to 0.005 USD per call, a few cents in all.

These are estimates from list prices; Azure's number for 2026-10-11 will post with a lag. Check it with the query in `docs/runbook.md` section 8 before enabling the routine again. If the owner raises the cap, run the scenarios again with the routine enabled to see a new ticket cross every stage live.

## Files

| Path | What |
|------|------|
| `agents/sdlc_agents/ledger/` | events, ticket model, fold, reconcile, branch store, billing, summaries, service, emitter, runtime |
| `agents/hosted/ledger/` | the hosted agent entry point, requirements, zip builder |
| `agents/sdlc_agents/tick.py`, `metrics.py`, `runtime.py`, `cost.py` | the orchestrator hand-off (`LEDGER_MODE=hosted|inline|off`), ledger spend in `metrics.json` |
| `apps/control-center/` | the read-only app: 8 views, 92 tests, README |
| `.github/workflows/cd.yml`, `pages.yml`, `scripts/cd/`, `scripts/build_pages.sh` | continuous deployment, the branch `deploy` renderer |
| `app/e2e/smoke/`, `app/web/vite.config.ts` | smoke tests, path agnostic build |
| `scripts/deploy_agents.py`, `scripts/setup_repo.py` | ledger deploy and roles, the `escalated:deploy-failed` label |
| `docs/architecture.md`, `docs/cd.md`, `docs/runbook.md`, `docs/decisions.md` (D11 to D14), `docs/explainer/`, `docs/proof/` | contracts, operations, decisions, diagrams, evidence |

## Run, test, deploy

```bash
cd agents && uv run pytest                       # 829 tests
cd apps/control-center && npm test               # 92 tests (needs: cd app && npm ci)
uv run --project agents python scripts/deploy_agents.py hosted --only sdlc-ledger   # then: roles
gh workflow run cd.yml -f inject_fault=smoke     # rehearse a rollback
```

Operations are in `docs/runbook.md` section 7a and `docs/cd.md`.

## Decisions and things to know

- Ledger placement, the `deploy` branch, the read path of the control center and the spend decision: `docs/decisions.md` D11 to D14.
- Four independent reviews (two Opus, two security) ran on the work and found real defects, all fixed with tests: a rollback that could be cancelled and leave a failed build tagged as prod, a re-run that could roll prod back, a poisoned issue that froze the ledger, ledger spend counted twice, failed hosted calls booked at zero, a compare-and-swap that read the branch head twice, a smoke gate an agent PR could edit, and untrusted PR and comment text steering the CD flag.
- `raw.githubusercontent.com` caches for up to 300 seconds (measured) and ignores query strings; the control center therefore also reads the GitHub API while its 60 requests per hour budget lasts.

## Known limitations and follow-ups

- A new ticket was not run live through building, review, staging and prod (spend). Re-run `scripts/run_scenarios.py` once the cap is raised.
- Intake time: re-measure after GitHub's hourly rate-limit reset; with a fresh budget the issue list is read every 30 seconds.
- `events.jsonl` has no rotation; it grows by about 30 KB per 12 ticks for 1 issue. Add monthly files and a snapshot base before running the routine for weeks.
- The `deploy` branch cannot be locked to the Actions app on a personal repository (GitHub answers HTTP 422); anything with `contents: write` can push to it and reach the site root.
- Hosted-ledger scale to zero is by platform design, not yet confirmed on a bill.
- The first release had no earlier artifact to roll back to, so `deploy/prod` was seeded with the app live before CD (history entry says so).
- The control center was not tested in Firefox or Safari (its CSS uses `light-dark()`).
- A Renovate onboarding PR (#1) from a non-owner is ignored by design.
