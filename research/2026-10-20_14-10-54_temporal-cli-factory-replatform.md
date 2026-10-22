# Research: Re-platform the autonomous SDLC onto Temporal + a CLI agent, shaped like Warp Factories

**Date**: 2026-10-20 14:10:54
**Repository**: temporal-cli-workflow (origin: stevengonsalvez/foundry-autonomous-sdlc)
**Branch**: stevengonsalvez/temporal-cli-workflow
**Commit**: f9c9fc0
**Research Type**: Comprehensive (codebase + documentation + web)

## Research Question

Understand the entire project, then plan the same system with Temporal as the orchestrator and a CLI coding agent (Antigravity `agy` first, later Copilot CLI or Claude Code) in place of Azure AI Foundry agents. Keep mission control (the control center). Restructure as a monorepo shaped like the Warp Factories diagram (work sources, automations, foreman, triage/spec/implement/review with a revision loop, human handoff, factory definition, execution, dashboard, measure and improve). Build exactly what exists first, then extend. Run all of it from docker compose first, then on an Azure VM.

## Executive Summary

About 70 percent of the existing code is not Foundry-bound and ports as is: the pure state machine (`machine.py`), merge gates (`gates.py`), the ledger event/fold pipeline, the control center (static, reads `state.json`), the CI gates, and most of the coder runtime. What gets replaced is the thin Foundry and cron layer: `foundry.py`, `keyvault.py`, `lock.py`, the tick loop, the hosted-agent wrappers and the Terraform. Temporal replaces the tick with one durable workflow per work item. The recommended first build is a like-for-like port (same stages, same gates, same control center) on docker compose, with the Warp-style factory definition tree and a real human merge gate added as the first extension, because today's system auto-merges, which the Warp model forbids.

The largest open risk is not technical. Wrapping `agy` with a personal-plan OAuth token inside automation is likely against Antigravity's terms. An API key or GCP ADC path avoids that.

## Key Findings

- **Architecture today.** A `*/5` cron routine fires a stateless orchestrator tick (lock ref on GitHub, state comment on each issue as the source of truth) that drives 9 Foundry prompt agents, a hosted coder sandbox, a ledger that writes `state.json` to a git branch, and a static control center that polls it. Source of truth for contracts is `docs/architecture.md`, but code was used as the authority throughout.
- **Pure core is separable.** `machine.next_action(ctx)` has no I/O (`agents/sdlc_agents/machine.py:131`). `gates.verify_merge` (`gates.py:130-178`) is the security-critical merge check. Both port unchanged.
- **Temporal makes about a third of the orchestrator dead code.** Lock ref, deferral streaks, wall-budget logic, `start-unconfirmed` resend and session-lost counting exist only to survive a stateless 5-minute tick.
- **The coder already runs `agy`.** The Foundry coder wraps `agy -p ... --mode accept-edits` with an unprivileged user, scrubbed env, scope checks and a tdd-order red commit (`agents/sdlc_agents/coder/engines.py:157-166`). It is the closest prior art and about 70 percent reusable.
- **Ledger has a clean seam.** `BranchStore` is a two-method compare-and-swap protocol (`agents/sdlc_agents/ledger/store.py:33-35`). The control center can be pointed at any same-origin `state.json` with `?data=state.json` and no JS changes (`apps/control-center/js/main.js:28-37`).
- **Warp Factories is a repo tree, and the human gates are repo-enforced.** `factory.yaml`, `agents/<n>/agent.md`, `automations/<n>/automation.md`, `runners/`, `scorers/`, `benchmarks/`, `skills/`, `webhooks/`. Spec approval is a draft PR, merge is branch protection. A reference repo exists: `warpdotdev/warp-factory-examples` (MIT).
- **Gaps versus Warp.** Missing today: human merge gate, human spec approval, work sources beyond GitHub, webhook ingress, scorers on live runs, benchmarks, self-improvement PRs, a declarative factory definition.
- **Temporal fits.** Postgres-only visibility (no Elasticsearch), `temporalio/server` 1.32.1, Python SDK 1.34.0. Signals/updates plus `wait_condition` model human approval. A long coder run is a heartbeating sync activity on its own task queue.
- **CLI auth and terms are the real risk.** Copilot and Claude Code have documented API-key or token paths. `agy` offers a Gemini API key or ADC, and its personal OAuth token path is buggy in containers and contested under the terms.

## Prior Learnings

Step 0 recall could not run: `~/.claude/skills/recall/scripts/recall.py` does not exist on this machine. The prompt-time hook injected learnings (Supabase RLS, jsdom, release flake triage) but none relate to this topic, so none are used.

## Detailed Findings

### Codebase Analysis

Repo is a demonstration: a parcel-tracker target app (`app/`), the agents package (`agents/`), a control center (`apps/control-center/`), Terraform for Azure (`infra/terraform/`), CI/CD in `.github/workflows/`, a simulated product owner (`po/`, `scripts/po/`), scenarios, evals, and a legacy metrics dashboard (`dashboard/`). All paths below are at commit f9c9fc0.

#### Orchestrator core (`agents/sdlc_agents/`)

State machine, as implemented:

| Stage | Action | Effect |
|---|---|---|
| none, untriaged bug | TRIAGE | sdlc-triage, triage comment (`tick.py:611`) |
| none | GATE | sdlc-req-gate, `after_score` (`tick.py:633`) |
| needs-refinement | ANSWER / RESCORE | sdlc-product-owner answers (`tick.py:677`) |
| ready | FEASIBILITY | sdlc-feasibility, feasible or escalate not-suitable (`tick.py:696`) |
| feasible | DESIGN_TESTS | test-designer plus `designed_tests.lint` (`tick.py:708`) |
| tests-written | START_CODER | write-ahead job id, coder start (`tick.py:773,858`) |
| building | POLL_CODER / CODER_LOST / RECONCILE | status poll, lease, adopt, restart (`tick.py:893-1063`) |
| in-review | CI_TRIAGE / REVIEW / MERGE / revise | ci-triage or designer repair, reviewer marker, `verify_merge`, merge (`tick.py:1123-1339`) |
| merged | RELEASE | tag, notes, GitHub release, close (`tick.py:1364`) |
| any | ESCALATE / WAIT / NOOP / HALT / IGNORE | label, comment, cancel coder |

- Pure: `next_action` (`machine.py:131`), `_guard` (`145-171`, failure limit, fail-closed unknown spend, per-issue cap, total halt), `after_score`, `after_feasibility`, `after_coder` (`368-400`). Impure dispatch is `tick.py:403`.
- Ports (`ports.py:88-201`): `GitHubPort`, `FoundryPort` (`call_prompt_agent`, `invoke_hosted`), `SecretsPort`, `ClockPort`, `GitPort`, `CodingEnginePort`, `Budget`. Foundry/Azure-coupled: `foundry.py`, `keyvault.py`, `runtime.py` (DefaultAzureCredential), `hosted/orchestrator/main.py`, and `ResponsesClient` / `ModelLoopEngine` in `coder/engines.py:187,274`.
- Prompt agents (`definitions.py:571-595`): req-gate, product-owner, feasibility, test-designer, reviewer, triage, ci-triage, release-notes, ui-tester. Structured output is enforced twice: server-side strict JSON schema in Foundry (`create_agents.py:60-61`), then client-side `parse_json_strict` plus `schema_check` plus agent checks plus one repair retry (`foundry.py:331-364`). A CLI agent loses the server-side layer. `parse_json_strict` is plain `json.loads` (`sanitise.py:43-45`), so fenced replies fail; an extract step is needed.
- Under Temporal these become dead code: lock ref (`lock.py:146-180`), deferral streak (`tick.py:419-438`), wall budget, `start-unconfirmed`, session-lost counting, poll-to-keep-alive. These must stay: owner-only guard, fail-closed spend, per-issue and total caps, full `verify_merge` (head-sha-bound review marker, scope under `app/`, fork check, 3000-file cap), head-sha binding of `ci_revise`, `merge_conflict` and review, idempotent release (`release.py:228`), allow-listing and redaction of coder text.
- One cross-item concern: release tag reservation reads all objects in a tick (`tick.py:1373-1377`). Per-issue workflows lose that view, so releases need a serializing component.
- Cost model (`cost.py`): token prices are for gpt-5-mini (0.25 / 2.00 USD per Mtok), hosted compute is per vCPU/GiB second. Caps are 3 USD per issue, 32 halt, 35 total. On a subscription CLI every price constant is wrong and token usage may not be reported. Cap mechanics survive; the unit changes (calls or minutes per issue, plus quota as a first-class signal; `agent-quota` already exists at `machine.py:392-395`).
- Tests: about 290 tests. `run_tick` takes every port, and `tests/fakes.py` has `FakeGitHub`, `FakeFoundry`, `FakeCoder`, `FakeClock`. Pure `Context -> Action` tests (`test_core.py:124-247`) port unchanged. Scenario tests (`test_scenarios.py`, 38) can run under Temporal's time-skipping test environment bound to the same fakes (inference). Lock, deferral and coder-loss tests retire.

#### Coder runtime (`agents/sdlc_agents/coder/`)

- Install: `https://antigravity.google/cli/install.sh` into `~/.local/bin/agy`, copied root-owned to `/opt/agy/bin/agy` (`toolchain.py:157-167`, `sandbox.py:104-118`).
- Auth: token JSON at `~/.gemini/antigravity-cli/antigravity-oauth-token`, mode 0600, obtained by interactive sign-in on a dev machine and loaded to Key Vault (`runbook.md:82-83`).
- Invocation: `agy -p <prompt[:100000]> --mode accept-edits [--log-file ...]`; fallback engine uses the unrestricted flag and refuses to run as root (`engines.py:47-50,104-105,157-166`). Allow-list in `settings.json` (`toolchain.py:38-53`). Env built from nothing (`engines.py:84-91`). 360 s per restricted round, 900 s unrestricted (`engines.py:52-53`).
- Failure detection: `Authentication required` regex then abort; quota via `AGY_ERROR` lines with `RESOURCE_EXHAUSTED` or exit 3; soft deny is exit 0 with no edits (`engines.py:56-80`, `runner.py:84`).
- Recorded gotchas: `--sandbox` blocks every shell command; unauthenticated agy blocks instead of exiting; allow-list soft-denied even when loaded (hence one round); missing `~/.bashrc` stalls the first command; quota patterns must be line-anchored; agy can edit its own settings or switch branches (handled by settings rewrite plus `reset_soft` and a branch check).
- Doc drift found: `runbook.md:222` says 600 s per call (code: 360/900), `architecture.md:183` says `max_model_usd` max 1.00 (code: 3.00, `job.py:34`).
- Lifecycle: setup, red (tests committed first, must fail on an assertion), implement loop (engine, scan, scope check, tests, checks), publish (push exact verified sha, open PR with `agent:pr`).
- agy-specific code leaks into the runner at 7 sites (`runner.py:36,74,84,385-408,602-620,732-762,883`). The existing `CodingEnginePort` is only `name` plus `edit()` (`ports.py:178-182`). Proposed `CliEngine` protocol (provision, refresh, argv, env, abort_on, classify, tool_hint) with a shared runner owning retry, keep-edits and reap.
- Security controls to keep: fail closed without engine user, privilege drop, per-call `GIT_ASKPASS`, scans after each untrusted step (git config and hooks digest, nested `.git`, symlinks), scope violations, push exact sha.
- File verdicts: reuse as is `shell.py`, `scope.py`, `checks.py`, `testrun.py`, `git_adapter.py`; adapt `sandbox.py`, `toolchain.py`, `engines.py`, `job.py`, `runner.py`; rewrite `wiring.py`; drop `hosted/coder/*` and `CoderService`.
- Docker mapping: separate worker container, Debian bookworm, Python 3.13, git and ca-certificates baked in, Node 22 in `/opt/node`, agy in `/opt/agy`, `agyuser` with empty `.bashrc`, root worker process dropping privilege. Capabilities `CHOWN, DAC_OVERRIDE, FOWNER, KILL, SETUID, SETGID` after `cap_drop: ALL` (inference). Egress needs rethinking: compose has no FQDN policy, so use an internal network plus an allow-list proxy. `agy_env` passes no proxy or CA variables today (`engines.py:84`), a gap. New risk (inference): agent code on the compose network could reach an unauthenticated Temporal frontend, so isolate by network.

#### Ledger, control center, CI, infra

- Flow: orchestrator emits events, `Ledger._commit` folds and writes via `BranchStore` with CAS retry (`ledger/service.py:120-226`), control center polls (`apps/control-center/js/data.js:183`). Content-addressed event ids make replays safe (`ledger/events.py`). `state.json` is rebuildable from `events.jsonl`.
- `state.json` contract (hard requirements: `version === 1`, `tickets` array): see `apps/control-center/js/schema.js:437-478`. Nine board stages, ticket, environments, agents, cost (caps, totals, billing, gap), flow, ledger sections. `billing: null` degrades cleanly.
- Azure coupling is only in wiring: `ledger/runtime.py:33-51` (Key Vault, Foundry summariser, Cost Management) and `hosted/ledger/main.py`. `InlineEmitter` already runs the ledger in-process (`ledger/emitter.py:68-75`).
- `fold.py:29-60` hard-codes the 11 Foundry agent roster and `views/common.js:42-52` maps names to badges. Both need the new roster.
- Control center: `?data=state.json` same-origin works with no JS change. Cosmetic Azure copy at `model.js:256` and `views/cost.js:1`.
- Store phases: phase 1 keep the GitHub `state` branch with an env token; phase 2 Postgres `BranchStore` (about 40 LOC, one row per file with a head version). Temporal visibility is not a fit for the rich derived document.
- CI: `test, coverage, e2e, gitleaks, tdd-order, agent-scope` portable as is. `evals` imports `sdlc_agents.foundry._parse`, `definitions._check_req_gate`, `machine.after_score` (`evals/test_replay.py:16-19`), so extract those first. `infra-ci.yml` drops. `pages.yml` and `cd.yml` stage, promote and rollback are Pages-bound.
- CD on compose: smoke and soak are URL-parameterised and portable; staging needs a host. A GitHub-hosted runner cannot reach a NAT'd compose host, so a self-hosted runner or public URL is required.
- Simulated product owner: `po/` is an Orca scheduled automation driving `agy` every 4 hours (hats: intake from `ROADMAP.md`, answerer, triage lead, escalation owner), `gh` allow-list only, never merges. It reads `git show origin/state:state.json`. A second, in-loop `sdlc-product-owner` prompt agent also exists.
- Terraform: `foundry`, `keyvault`, `budget`, `observability`, `egress_policy`, `bootstrap`. Compose analogues: none, secrets via env or docker secrets, in-app caps, Temporal UI plus OTel, proxy allow-list. `scripts/deploy_agents.py` (835 lines) is 100 percent Foundry and drops. `scripts/setup_repo.py` (labels, ruleset, Pages) is portable.

#### Mapping to the Warp diagram

| Box | Status | Where / gap |
|---|---|---|
| Work sources | Partial | GitHub issue forms, PO roadmap, scenarios. No Slack, Linear, Jira, webhooks |
| Automations | Partial | `*/5` routine, 4 h PO, GH Actions. Polling, no webhook ingress |
| Foreman | Exists | `sdlc-orchestrator` state machine |
| Triage | Exists | `sdlc-triage`, `sdlc-ci-triage` |
| Spec | Partial | req-gate score, simulated PO answers, feasibility. No human approval gate |
| Implement | Exists | coder, test-designer first, tdd-order enforced |
| Review | Exists | `sdlc-reviewer` plus 7 required checks |
| Human handoff (agents never merge) | Contradicted | orchestrator merges (`github.py:238`, `machine.py:83`), CD auto-promotes (`docs/cd.md:3`) |
| Factory definition | Partial | agents in `definitions.py`, no declarative tree |
| Execution | Exists (Azure) | becomes Temporal workers |
| Factory dashboard | Exists | control center |
| Measure and improve | Partial | flow metrics and evals exist; no live scorers, benchmarks or fix PRs |

### Documentation Insights

- `docs/architecture.md` is the contract and is accurate on the main points checked. Two drifts found (see coder section).
- Existing research docs worth reading before design: `docs/research/sandboxing-security-options.md` (threat model, notes the Antigravity FAQ says third-party wrapping is unsupported on consumer plans, `:183`), `docs/research/aca-sandbox-spike.md`, `docs/findings.md`.

### External Research

#### Warp Factories (all pages fetched 2026-10-20, schema `v1alpha1`, pages undated)

- Factory root `factory.yaml`: `schemaVersion`, `name`, `repositories`, `agentDefaults` (model or harness `oz|claude|codex|claude-code`, runner, workerHost), optional `integrations`, `scorerDefaults`, `selfImprovement` ([factory-as-code](https://docs.warp.dev/factories/factory-as-code/)). Confidence high.
- Layout to mirror: `agents/<n>/agent.md` (frontmatter `agentType` FOREMAN, TRIAGE, SPEC, IMPLEMENT, REVIEW, VERIFY, plus model, runner, secrets), `automations/<n>/automation.md` (triggers with provider, event, filter), `runners/<n>.yaml` (docker image, shape, setup commands), `routers/`, `skills/<n>/SKILL.md`, `scorers/<n>/scorer.md`, `benchmarks/<suite>/suite.yaml`, `webhooks/<n>.yaml`. Dirs identify resources; invalid changes leave the last valid definition live; PR check dry-runs the change ([factory-as-code](https://docs.warp.dev/factories/factory-as-code/)). Confidence high.
- Flow: foreman is a parent agent dispatching one level of child runs over a durable message bus; a finished child wakes on a new message, which is the revision loop ([orchestration](https://docs.warp.dev/platform/orchestration/)). One work item continues across later activity on the same GitHub thread, Linear issue or Slack thread. Confidence high; the phrase "conversation per work item" is the diagram's, not the docs'.
- Gates: spec agent opens a draft PR and stops, implement continues on the same branch after approval, merge is repo branch protection, review agent never approves or merges ([example spec agent](https://raw.githubusercontent.com/warpdotdev/warp-factory-examples/main/examples/02-sdlc-issue-to-pr/agents/spec/agent.md)). How the platform detects spec approval is undocumented.
- Write-back to the source tool is agent-driven through skills and prompts, not a platform sync (inference from example prompts).
- Self-hosted: Warp keeps the control plane, customer runs `oz-agent-worker` (outbound only, Docker, Kubernetes, Direct or Command backends, `max_concurrent_tasks`, OTel metrics). Worker wire protocol undocumented ([self-hosting](https://docs.warp.dev/factories/self-hosting/)). We design our own.
- Measure: scorers are LLM judges choosing from fixed labels with scores 0..1, sampled (default 25 percent); self-improvement groups failures per agent and opens one fix PR when 25 unreviewed failures or 7 days is reached; benchmarks run task suites against up to 6 configurations ([scorers](https://docs.warp.dev/factories/measure-and-improve/scorers/), [benchmarks](https://docs.warp.dev/factories/benchmarks/), [self-improvement](https://docs.warp.dev/factories/measure-and-improve/self-improvement/)). Confidence high.
- Dashboard metrics: runs, PRs opened and merged, autonomy (merged PRs with no human code push), PR cycle time with per-stage medians, cost per PR with size buckets ([dashboard](https://docs.warp.dev/factories/factory-dashboard/)).
- Reference repo: [warp-factory-examples](https://github.com/warpdotdev/warp-factory-examples), MIT, example `02-sdlc-issue-to-pr` has 6 agents, 5 automations, 3 runners, 2 scorers. Not cloned.
- Gaps: skill frontmatter schema, harness identifiers page, full `factory.yaml` text, spec-approval detection.

#### Temporal (fetched 2026-10-20)

- Versions: server `temporalio/server:1.32.1` (2026-10-08), patch lines 1.31.4 and 1.30.8, UI 2.56.0, CLI 1.9.1 (Homebrew formula), Python SDK `temporalio` 1.34.0 (2026-09-30, Python 3.10+). `auto-setup` has no tags past 1.29.7; the archived compose README says use `temporalio/server` ([Docker Hub](https://hub.docker.com/v2/repositories/temporalio/server/tags?page_size=25&ordering=last_updated), [PyPI](https://pypi.org/pypi/temporalio/1.34.0/json)). Confidence high.
- Compose: the old `temporalio/docker-compose` repo is archived; use `samples-server/compose` (`docker-compose-postgres.yml`). It is documented as local-dev, with Helm for production ([README](https://raw.githubusercontent.com/temporalio/samples-server/main/compose/README.md)). Schema is applied by an admin-tools one-shot using `temporal-sql-tool`, then a namespace-create one-shot. Advanced visibility works on Postgres 12+ since 1.20, so no Elasticsearch ([visibility](https://docs.temporal.io/self-hosted-guide/visibility)). Confidence high. A minimal compose skeleton (Postgres 16, admin-tools, server, namespace job, UI, localhost-bound ports, named volume) was drafted by the research agent and should be verified against the sample scripts before use; one agent reported a variable typo in `create-namespace.sh` (low confidence, read the file).
- Patterns: signals, updates (with validators) and queries; human approval as signal or update plus `wait_condition` with a durable timeout ([HITL cookbook](https://docs.temporal.io/ai/cookbook/human-in-the-loop-python)); wait for `all_handlers_finished` before return; schedules replace cron ([schedules](https://docs.temporal.io/develop/python/schedules)); continue-as-new when suggested.
- Long activities: set start-to-close and a short heartbeat timeout; heartbeats carry cancellation and progress; sync activities with a thread pool executor and `subprocess.Popen` polling suit a CLI coder; dedicated task queue with `max_concurrent_activities` ([failure detection](https://docs.temporal.io/encyclopedia/detecting-activity-failures), [sync vs async](https://docs.temporal.io/develop/python/python-sdk-sync-vs-async)). The cancellation point is the heartbeat, so a coder that does not heartbeat cannot be cancelled.
- Observability: custom search attributes (Postgres limit: 10 Keyword per namespace), Prometheus and OTel in the Python runtime; mission control reads stage via visibility and detail via query, or keeps its own projection ([observability](https://docs.temporal.io/develop/python/observability)).
- Pitfalls: payload warn 256 KB, error 2 MB; history warn 10 MB / 10,240 events; keep transcripts out of payloads (claim-check pattern); shard count fixed at install; upgrades one minor at a time; Worker Versioning Pinned fits multi-day items ([defaults](https://docs.temporal.io/self-hosted-guide/defaults)). No official VM sizing or backup guidance; `pg_dump` of both DBs is the obvious approach (inference).
- Not verified: default namespace retention, official saga page, 1.32 and Python 1.34 release notes (GitHub API returned 403 for the agent).

#### CLI agents (fetched 2026-10-20)

- `agy` headless ([docs](https://antigravity.google/docs/cli/headless/)): `-p`, `--output-format text|json|stream-json`, `--json-schema`, `--model`, `--effort`, `-c/--continue`, `--conversation`, `--dangerously-skip-permissions`, `--print-timeout` (default 5 minutes), `--sandbox`. Statuses SUCCESS, ERROR, CANCELED, INTERRUPTED, INVALID, WAITING, RUNNING. Soft-deny exits 0 with a stderr notice, so exit 0 is not success. Our coder passes neither `--print-timeout` nor `--output-format` (`engines.py`), so agy may stop itself at 5 minutes before our 900 s cap (inference, needs a test). Exit code 3 for quota is only locally observed. Confidence high on flags.
- `agy` auth: Google sign-in, remote SSH paste-code flow, Gemini API key (needs `"modelProvider": "gemini"` in settings plus `GEMINI_API_KEY`), or ADC with `AGY_ADC_AUTH=true` ([install doc](https://antigravity.google/docs/cli/install)). File token storage in containers is buggy: [#479](https://github.com/google-antigravity/antigravity-cli/issues/479), [#950](https://github.com/google-antigravity/antigravity-cli/issues/950) (workaround `GEMINI_FORCE_FILE_STORAGE=true`, unset `DBUS_SESSION_BUS_ADDRESS`), [#1194](https://github.com/google-antigravity/antigravity-cli/issues/1194) (refreshed tokens never sync back). Medium confidence (user-filed issues).
- `agy` terms: [Terms §6](https://antigravity.google/terms) says using third-party software to access the service (example given: OpenClaw with Antigravity OAuth) is a breach, with suspension as the penalty. A forum reply dated 2026-10-08 says headless is for your own scripts and CI but orchestrating under a consumer login is unsupported and points to an API key ([thread](https://discuss.ai.google.dev/t/is-google-ai-pro-antigravity-cli-automation-with-codex-permitted/187241)); poster's staff role unverified. The repo already marks this unverified (`docs/final-report.md:51`). Confidence high that the text exists, low on how it applies.
- Claude Code: `-p`, `--output-format json|stream-json` with `total_cost_usd` and `usage`, `--max-turns`, `--max-budget-usd`, `--permission-mode`, `--allowedTools`, `--resume`, `--json-schema`; auth by API key or one-year `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`; subscription plans assume ordinary individual use and product builders should use API keys ([headless](https://code.claude.com/docs/en/headless), [authentication](https://code.claude.com/docs/en/authentication), [legal](https://code.claude.com/docs/en/legal-and-compliance)). Confidence high.
- Copilot CLI: `-p`, `--output-format=json` (JSONL), `--allow-tool`, `--deny-tool`, `--no-ask-user`, `--share`; auth by `COPILOT_GITHUB_TOKEN` or `GH_TOKEN` with a fine-grained PAT that has the "Copilot Requests" permission (classic `ghp_` unsupported); no documented turn cap or `-p` resume; billing by premium requests ([reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-programmatic-reference)). Confidence high.

Comparison:

| feature | agy | copilot | claude |
|---|---|---|---|
| headless | `-p` | `-p` + `--no-ask-user` | `-p` |
| structured output | json, stream-json, `--json-schema` | JSONL | json, stream-json, `--json-schema` |
| permissions | settings allow/ask/deny, `--mode` | `--allow-tool`, `--deny-tool` | `--permission-mode`, `--allowedTools` |
| resume | `-c`, `--conversation` | not documented | `--resume`, `--session-id` |
| Docker auth | API key, ADC, or token file (buggy) | fine-grained PAT env | API key or OAuth token env |
| usage visibility | `usage` in JSON | none documented | `total_cost_usd`, `usage` |
| caps | `--print-timeout` only | none documented | `--max-turns`, `--max-budget-usd` |

Note on tooling: the harness flagged `dangerously-skip-permissions` and `bypass-permissions` strings in two agent outputs. They are CLI flag names quoted from `engines.py` and the docs, not instructions.

## Code References

- `agents/sdlc_agents/machine.py:131`: pure `next_action`; `:145-171` `_guard`; `:368-400` `after_*` rules
- `agents/sdlc_agents/tick.py:201`: `run_tick(...)` takes every port; `:403` action dispatch; `:1364` release
- `agents/sdlc_agents/gates.py:130-178`: `verify_merge` (keep in full)
- `agents/sdlc_agents/ports.py:88-201`: all ports; `:178-182` thin `CodingEnginePort`
- `agents/sdlc_agents/foundry.py:331-364`: validate and repair loop (port the logic)
- `agents/sdlc_agents/sanitise.py:43-45`: `parse_json_strict` (needs fence extraction)
- `agents/sdlc_agents/definitions.py:571-595`: the 9 prompt agents and schemas
- `agents/sdlc_agents/coder/engines.py:157-166`: agy invocation; `:56-80` failure detection
- `agents/sdlc_agents/coder/runner.py:577-663`: engine fallback chain; `:682-787` scan, contain, scope
- `agents/sdlc_agents/coder/shell.py:93-168`: streaming abort-on-output kill with process group SIGKILL
- `agents/sdlc_agents/coder/sandbox.py:121-157`: link-safe root write into a user's home
- `agents/sdlc_agents/ledger/store.py:33-81`: `BranchStore` protocol and memory twin
- `agents/sdlc_agents/ledger/service.py:120-226`: `_commit` with CAS retry
- `agents/sdlc_agents/ledger/fold.py:29-60`: hard-coded agent roster
- `apps/control-center/js/schema.js:437-478`: `state.json` contract
- `apps/control-center/js/main.js:28-37`: `?data=` same-origin source
- `evals/test_replay.py:16-19`: evals coupling to `foundry.py`
- `docs/architecture.md`: contract; `docs/final-report.md:51`: ToS flagged unverified

## Recommendations

1. **Build like for like first, as a vertical slice.** One work item end to end (issue to PR) on docker compose: Temporal + Postgres, one `WorkItemWorkflow` per issue, activities for GitHub, a CLI LLM call and the coder. Reuse `machine.py`, `gates.py`, `state.py`, ledger, control center, gates, fakes.
2. **Make the CLI an interface from day one.** Extract `CliEngine` from `runner.py` before writing the activity, then add `agy` as the first adapter and a second adapter later. Require structured output (`stream-json` or `--json-schema`), classify from the terminal event not the exit code, add fence extraction plus up to two repair rounds.
3. **Settle auth before building on agy.** Default to the Gemini API key or ADC path for `agy`. Keep the consumer token only for local experiments. Wire the coder to read secrets from docker secrets.
4. **Add the human merge gate as the first extension, not a later one.** Replace `Kind.MERGE` with a workflow update that a human triggers (control center button or GitHub review), and put a human approval step on the spec. This matches Warp and removes the biggest contradiction.
5. **Keep state in two layers.** Temporal workflow state is the truth. Keep the ledger event log and fold unchanged. Phase 1 writes to the GitHub `state` branch via env token; phase 2 adds a Postgres `BranchStore`. Serve `state.json` and the control center from one nginx origin with `?data=state.json`.
6. **Monorepo layout (proposal).**
   ```
   apps/control-center/      as is
   apps/target-app/          from app/ (update agent-scope globs)
   factory/                  factory.yaml, agents/*/agent.md, automations/, runners/, scorers/, skills/
   services/foreman/         Temporal workflows
   services/workers/         activities: github, gates, llm-cli, coder
   services/ledger/          ledger + store_pg + state.json HTTP
   work-sources/github/      setup_repo, issue forms, webhook receiver
   simulated-human/          po/ + scripts/po
   evals/ ci/gates/ cd/
   deploy/compose/  deploy/azure-vm/
   ```
7. **Move prompts out of Python into the factory tree.** `definitions.py` prompts and schemas become `factory/agents/<n>/agent.md` plus a JSON schema, loaded by the worker. This delivers the Warp "factory definition" shape cheaply and unlocks scorers later.
8. **Isolate the coder.** Separate worker container, `cap_drop: ALL` plus the minimal set, internal network, allow-list proxy, pass proxy and CA variables in `agy_env`, keep Temporal unreachable from agent code.
9. **Defer for later phases:** Slack/Linear/Jira sources, webhook ingress, scorers, benchmarks, self-improvement PRs, Copilot and Claude adapters, Azure VM, Postgres store.
10. **Quick spikes to de-risk (each under an hour):** `agy --print-timeout 15m --output-format stream-json` on a long task; one prompt agent (`sdlc-triage`) through the CLI to measure parse failure rate; read the compose scripts and boot Temporal; fetch the `02-sdlc-issue-to-pr` example tree.

## Open Questions

- Which `agy` auth path is acceptable (API key, ADC, or personal token for local only)?
- Does "agents never merge" apply fully, including CD auto-promote?
- Where does CD staging run: self-hosted runner on the VM, or public URL?
- Stage reasoning engine: all stages through the CLI, or keep a direct model API for cheap stages (triage, req-gate)?
- Does the new repo stay in this repo's git history (new top-level dirs, move `app/`), or start as a fresh repo?
- Postgres ledger store in phase 1 or 2?
- How to surface CLI cost: calls, minutes, or provider-reported tokens (agy `usage` field is unverified)?
- Not verified in research: how the `metrics` branch is written; whether the control center tolerates a missing `environments.source`; agy image input for the ui-tester agent; Warp skill and harness schema pages.
