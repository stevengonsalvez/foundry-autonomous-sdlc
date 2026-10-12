# Control center, continuous deployment and the state-keeper: final report

What was added to the autonomous SDLC demo, what was proven live on 2026-10-11, and what is not true yet. Every claim has a link, a run, or a command.

```
 issue ─▶ orchestrator ─events─▶ sdlc-ledger (hosted) ─one commit─▶ branch state ─▶ /control-center/
 merge ─▶ CI ─▶ /staging/ ─▶ smoke ─▶ 10 min soak ─▶ prod (site root)   |   any failure: rollback + flag
```

## Success criteria

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | A new issue appears on the board within 60 s and moves through every stage with timestamps, detail, cost, gates, questions-back and environment hops, across all 8 views | **Met, live** | Intake: a probe issue ([#53](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/issues/53)) appeared on the live board as a "waiting for ledger" card 22 s after it was filed, measured with a headless browser on a fresh GitHub API budget ([screenshot](proof/live-intake-probe-22s.png)); the poll runs only while the tab is visible and the first read is the sum of the 30 s cadence and the cache. Stages: [#51](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/issues/51) ("Show how many tracking events a parcel has") was filed at 23:42 UTC on 2026-10-11 and the real orchestrator took it through backlog, refining, feasible, tests (first test file failed typecheck, was sent back and repaired), building (coder job, 2 attempts), review (approved), staging and prod, with every transition and timestamp in the ledger. [PR #54](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/pull/54) merged as `110ea16`, release v0.4.0, [CD run 38186680523](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/actions/runs/38186680523) passed smoke and the 10 minute soak and promoted it (tag `prod/20261012-001759-110ea16`, live `build.json` shows the same sha). The [ticket page](proof/live-ticket-51-released-to-prod.png) shows stage timeline, six CI gates plus review, smoke and soak, cost split (model 0.02, coder runtime 0.25, ledger 0.03 USD), both environment hops, commits (test before feat), refinement score, feasibility and the reviewer verdict; [board](proof/live-board-after-ticket-51.png) and [environments](proof/live-environments-after-ticket-51.png) show it too. Escalation path: #45 (`escalated:not-agent-suitable`) and the rollback drill. The questions-back trail is empty for #51 because its requirements scored 100 with no refinement round; #45 has 4 recorded answers |
| 2 | A merged PR reaches /staging/ and then prod after Playwright smoke plus a 10 minute soak with no human step; a forced smoke failure rolls back and shows as escalated on Environments and Escalation | **Met** | Merge of [PR #44](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/pull/44): [CD run 38178080036](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/actions/runs/38178080036), plan, build, stage, smoke on the live `/staging/` URL, soak 10 minutes, promote, tag `prod/20261011-220522-641cb02`, live root `build.json` equal to the merge. Forced failure: [run 38180836579](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/actions/runs/38180836579) (`inject_fault=smoke` broke the built heading): smoke failed, soak and promote skipped, rollback restored `/staging/` to prod's artifact, prod and the tag list unchanged, [PR #46](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/pull/46) labelled `escalated:deploy-failed` with a comment. The control center showed it on [Environments](proof/live-environments-after-rollback.png) (gate that failed, ticket flagged, run link, change failure rate 33 percent), [Escalations](proof/live-escalations-after-rollback.png) and the [ticket](proof/live-ticket-rolled-back.png). A clean re-run ([run 38181279359](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/actions/runs/38181279359), 2 minute soak) promoted the same commit, tagged `prod/20261011-224538-8137c60` and took the failure label off the PR |
| 3a | Per-ticket cost matches the orchestrator ledger within 5 percent | **Met** | A ticket's cost is the orchestrator's own figure. Checked on the live data after the #51 run: 20 tickets, worst difference 0.012 percent (state.json against `metrics.json`); #51 is 0.272473 USD in both. The ledger's own compute is a separate field (`ledger_usd`) that counts toward the cap in `total_usd` |
| 3b | Billed versus ledger gap shown, not hidden | **Met** | [Cost view](proof/live-cost-billed-vs-ledger.png): Azure billed 13.02 USD, ledger estimate 1.87 USD, 7.0x, billing read time, meter breakdown, banner. Read live by the ledger from Azure Cost Management |
| 3c | `sdlc-ledger` runs as a hosted Foundry agent writing only to branch `state` | **Met** | Hosted agent, version 7, 0.25 vCPU, 0.5 GiB, 2 minute idle. Its client refuses any repository but this one and it writes through the git data API onto `state` only. Last commits on [branch state](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/commits/state). Whether its compute scales to zero is by platform design (deprovisioned after the idle timeout); Azure has not posted any usage for 2026-10-11 yet, so the bill cannot confirm it today |
| 3d | gitleaks 0 findings across full history | **Met** | CI `gitleaks` check passes on every PR and on main (8.30.1); a local run (8.11) over the history reports none. Local working-tree hits are only ignored `.pyc` caches |
| 3e | Total Azure spend stays under 25 USD (caps set by the owner on 2026-10-12: 25 total, 22 halt, 3 per issue) | **Met at the last read** | Azure billed 13.02 USD for the resource group by 2026-10-11 20:00 UTC, before this work began (the original 5 USD cap had already been passed, which is why the owner raised it). Azure has posted nothing for 2026-10-11 or 2026-10-12 yet. This work's own estimated spend is 2.48 USD in the ledger (orchestrator 1.00, tickets 1.38, ledger 0.10), of which the live ticket #51 is 0.30 USD (one hosted coder job of 26 minutes, 0.25 USD at the list rate). Even if Azure bills hosted compute at 7 times the estimate, 13.02 plus 7 times 0.35 stays under 22 USD. Re-read the bill when Azure posts 2026-10-11 and 2026-10-12 |
| 3f | Explainer system diagrams reflect what shipped | **Met** | [docs/explainer/foundry-autonomous-sdlc.html](explainer/foundry-autonomous-sdlc.html), 10 diagrams including the CD flow, the data plane and the cost gap |
| 4 | Final deliverable runs without errors | **Met** | 829 agent tests, 461 script tests, 164 app tests, 66 dashboard tests, 92 control center tests, CI green on PRs #44 and #46 and on main, three live CD runs |
| 5 | Proof | **Met** | Links above, screenshots in [docs/proof/](proof/) |

## Spend, and the decision behind it

Azure Cost Management, resource group `rg-fsdlcd-demo`, month to date, read 2026-10-11 20:00 UTC: **13.02 USD** (9.83 GBP, all of it on 2026-10-10: Container Apps 6.74, Foundry Tools 5.97, models 0.30). The 4.80 USD in the first run's report was an early read. So the original 5 USD cap was already exceeded, and its halt, which reads the orchestrator's own estimate (1.86 USD), never protected it. On 2026-10-12 the owner set new caps: 25 USD total, halt new work at 22 USD, 3 USD per issue. 13.02 USD is inside them.

Until the new caps arrived there was no way to re-authorise spend, so this work:

- until the new caps arrived, ran no orchestrator tick on the hosted agent and no coder job, and the routine `sdlc-tick` stayed disabled (it still is);
- ran four orchestrator ticks on the maintainer's machine for issue #45 (prompt-agent tokens, about 0.007 USD by the ledger's price list), then, once the caps were raised, about 15 more for the new ticket #51 and two timing probes (0.30 USD for #51, mostly its one hosted coder job), all emitting to the hosted ledger;
- deployed `sdlc-ledger` at the smallest size and called it only when there was something to say. The ledger's own meter at the end of the work is in `cost.ledger` of [state.json](https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/state/state.json): about 0.0027 to 0.005 USD per call, a few cents in all.

These are estimates from list prices; Azure's number for 2026-10-11 will post with a lag. Check it with the query in `docs/runbook.md` section 8 before enabling the routine again.

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

- Only one new ticket (#51) was run live through every stage; the other scenarios (vague requirements, a bug, maintenance) were run in the first run and are in `docs/evidence.md`.
- Intake time is the 30 s poll plus the GitHub cache; it was 22 s in the headless probe and the poller sleeps while the tab is hidden, so a background tab can show a new issue later.
- `events.jsonl` has no rotation; it grows by about 30 KB per 12 ticks for 1 issue. Add monthly files and a snapshot base before running the routine for weeks.
- The `deploy` branch cannot be locked to the Actions app on a personal repository (GitHub answers HTTP 422); anything with `contents: write` can push to it and reach the site root.
- Hosted-ledger scale to zero is by platform design, not yet confirmed on a bill.
- The first release had no earlier artifact to roll back to, so `deploy/prod` was seeded with the app live before CD (history entry says so).
- The control center was not tested in Firefox or Safari (its CSS uses `light-dark()`).
- A Renovate onboarding PR (#1) from a non-owner is ignored by design.
