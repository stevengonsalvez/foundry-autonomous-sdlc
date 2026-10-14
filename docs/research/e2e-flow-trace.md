# End-to-End Flow Trace

Tracing ONE feature (Issue #83: `feat(web): display event location pin in parcel timeline`) through the whole self-building autonomous SDLC loop.

## Flow Trace Table

| Hop | Expected | Observed | Evidence Link | Time |
|---|---|---|---|---|
| (1) Simulated-human PO files issue | PO files improvement issue with label `simulated-human` and header `### Simulated human (antigravity)` after answering escalation #72 | Escalation #72 closed at 19:41:34Z; PO filed issue #83 ("feat(web): display event location pin in parcel timeline") at 19:45:00Z with header `### Simulated human (antigravity)` and label `simulated-human` | [Issue #83](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/issues/83), [Issue #72 comment](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/issues/72#issuecomment-6176767537) | 2026-10-14T19:45:00Z |
| (2) Orchestrator tick: req-gate, feasibility, tests-written | Routine tick picks up issue: req-gate score, feasibility check, test designer tests-first, stage labels | req-gate scored 90/100 (`stage:ready` at 19:45:23Z); feasibility passed risk=low (`stage:feasible` at 19:50:25Z); test designer wrote tests for `app/web/tests/timeline-pins.test.tsx` (`stage:tests-written` at 19:55:40Z) | [Issue #83 comment 1](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/issues/83#issuecomment-6176889832), [Issue #83 comment 2](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/issues/83#issuecomment-6177080283), [`state.json`](https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/state/state.json) | 2026-10-14T19:45:23Z - 2026-10-14T19:55:40Z |
| (3) Hosted coder builds, opens `agent/issue-83-rK` PR | Coder commits red tests first, implements green solution, pushes branch and opens agent PR | In progress / pending orchestrator building tick | Pending | Pending |
| (4) Gate suite & UI proof on PR | All CI gates pass (test, coverage, e2e, gitleaks, tdd-order, agent-scope, evals) + UI screenshots proof comment | Pending | Pending | Pending |
| (5) Reviewer agent verdict & auto-merge | Reviewer agent evaluates diff against criteria and auto-merges | Pending | Pending | Pending |
| (6) CD: staging smoke, soak, prod tag | CD deploys to staging, runs smoke test, 10 min soak, releases prod tag | Pending | Pending | Pending |
| (7) Ledger state & control center | `state.json` on `state` branch tracks transitions; control center displays live stage | Tracking verified up to `stage:tests-written` | [`state.json`](https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/state/state.json) | 2026-10-14T19:55:40Z |
| (8) App history showcase `/history/` | Showcase shows new release entry for the feature | Pending release tag | Pending | Pending |

## Harness Fixes During Trace
- **Coder runner settle race condition**: CI flaky runs in `agents/tests/coder/test_runner.py` (`test_install_failure_is_reported`, `test_revise_puts_a_new_head_on_the_existing_pr`, `test_each_round_records_its_wall_seconds_and_whether_it_timed_out`) were caused by `CoderService._settle()` observing a terminated worker thread and reading stale in-memory `RUNNING` status loaded before terminal checkpoint, erroneously marking the job `interrupted`. Fixed on branch `stevengonsalvez/e2e-runner-race` by checking fresh state from store and joining active worker thread before falling back to `interrupted`. PR #85 opened to `main`.
