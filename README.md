# Engineering Software Factory

An issue goes in. Agents score the requirement, check an agent can do it, write failing tests first, build until they pass, get an independent review, clear the CI gates, merge and release. A human only sees what the factory could not decide. The demo app is a parcel tracker; the factory is the point.

There are **two ways to run the same factory**. They share the app, the state machine, the gates, the ledger event schema and the control center. They differ in what runs the agents and where it lives.

<p align="center">
  <img src="docs/media/two-approaches.svg" alt="Two approaches side by side: Azure native with Azure AI Foundry hosted agents, and the independent factory with Temporal and a CLI agent on docker compose. Shared parts underneath." width="100%" />
</p>

| | A. Azure native | B. Independent factory |
|---|---|---|
| Orchestration | Foundry hosted orchestrator agent on a routine timer | Temporal workflows and a 60 second Schedule |
| Agents | Azure AI Foundry models (9 prompt agents) and a hosted coder | A CLI agent (Antigravity `agy` first, Copilot or Claude Code next) in a sandbox |
| Ledger | git branch `state` (`events.jsonl`, `state.json`) | Dolt, a git-style SQL database, behind `ledger-api` |
| Control center | GitHub Pages, read only | Same UI behind nginx, read only |
| Secrets and infra | Key Vault, Terraform | Docker secrets as files, `docker compose` |
| Cost model | Pay per Foundry call | Your CLI plan quota, tracked as calls and minutes |
| Runs on | Your Azure subscription | Any Docker host: a laptop now, an Azure VM next |
| Start here | [`docs/runbook.md`](docs/runbook.md) | [`docs/factory-runbook.md`](docs/factory-runbook.md) |

Pick **A** when the platform is Azure and you want managed agents. Pick **B** for portability, a private Azure DevOps variant, other CLIs, or when you want workflow history and retries from Temporal.

## Approach B: the independent factory

### How it fits together

<p align="center">
  <img src="docs/media/factory-architecture.svg" alt="Architecture of the independent factory on docker compose: Temporal and Postgres, the foreman worker, the coder sandbox behind an egress proxy, ledger-api with Dolt, and the nginx mission control." width="100%" />
</p>

| Component | Where | What it does |
|---|---|---|
| Temporal 1.31 and Postgres 16 | `deploy/compose` | Durable workflows, the `github-poll` Schedule, retries, timeouts, human gate signals |
| `worker-foreman` | `services/sdlc_factory` | One `WorkItemWorkflow` per issue. Each step runs the existing tick, gates and state machine for that one issue |
| coder | `services/sdlc_factory/coder_service.py` | HTTP service that runs `agy` as two unprivileged users: `agyuser` for builds and tests, `agyagent` for prompt agents. One coder job at a time |
| egress proxy | `deploy/compose/proxy` | Squid allow-list. The coder network has no direct internet |
| `ledger-api` and Dolt | `services/sdlc_factory/ledger_*.py` | Events in, `state.json` and `issues.json` out. One Dolt commit per write |
| Mission control | `apps/control-center` | The same read-only UI. It reads only `state.json` and `issues.json` |
| Factory definition | `factory/` | `factory.yaml`, one `agent.md` plus a JSON schema per agent, automations, runners. Shaped like Warp Factories |

### What happens to one issue

<p align="center">
  <img src="docs/media/work-item-lifecycle.svg" alt="Work item lifecycle: intake and triage, spec with feasibility and test design, implement with TDD and scope gates, review, merge and release. A revision loop returns request-changes to the coder." width="100%" />
</p>

Choices live in `factory/factory.yaml`: the engine per stage, `humanGates` for spec and merge, and the call and minute budget. Auto-merge is on in this deployment.

### Proven on real GitHub

<p align="center">
  <img src="docs/media/live-proof.svg" alt="Live proof: five paths run on real GitHub with real agy, nine bugs found only by live runs and fixed, and the items still open." width="100%" />
</p>

Details, evidence and the known gaps are in [`docs/factory-v1-status.md`](docs/factory-v1-status.md).

### Run it

```bash
cd deploy/compose
cp .env.example .env                 # then set the generated credentials, see secrets/README.md
docker compose up -d --build         # FACTORY_MODE=fake for a no-secrets dry run
./smoke.sh                           # 35 checks in fake mode
```

Mission control is at `http://127.0.0.1:18080` and the Temporal UI at `http://127.0.0.1:18233`. To open mission control privately from other machines on your tailnet:

```bash
sudo tailscale serve --bg --https=18443 http://127.0.0.1:18080
```

Going live (real GitHub, real agy, real merges) is a deliberate step: follow the checklist in [`docs/factory-runbook.md`](docs/factory-runbook.md). Turn on branch protection on the target repo first.

### Not built yet

Scorers and benchmarks, an Azure VM deployment, an Azure DevOps variant, a second CLI adapter, webhook work sources, and the simulated product owner intake (a stub).

---

## Approach A in detail: Azure native

The rest of this README describes the original Azure AI Foundry version, with its live demo, scenario traces, gates and safety model.

## Live demo

- App: <https://stevengonsalvez.github.io/foundry-autonomous-sdlc/>
- Control center (every ticket from backlog to prod with cost per ticket, gates, environment hops, agent health, escalations, flow metrics, the questions-back trail, and Azure's billed spend next to the ledger's estimate): <https://stevengonsalvez.github.io/foundry-autonomous-sdlc/control-center/>
- App evolution showcase (visual timeline across releases): <https://stevengonsalvez.github.io/foundry-autonomous-sdlc/history/>
- Staging (the build waiting for smoke and soak): <https://stevengonsalvez.github.io/foundry-autonomous-sdlc/staging/>
- Metrics dashboard (cycle time per stage, defect owner and resolution time, cost per issue, gate pass rates): <https://stevengonsalvez.github.io/foundry-autonomous-sdlc/dashboard/>
- Traces of every scenario, from issue to release: [`docs/evidence.md`](docs/evidence.md)
- Final report with the success criteria and their evidence: [`docs/final-report.md`](docs/final-report.md)

### Control center

<p align="center">
  <a href="https://stevengonsalvez.github.io/foundry-autonomous-sdlc/control-center/">
    <img src="docs/proof/control-center-board-desktop.png" alt="Control center board hero: delivery flow matrix with Delivery lens and Type grouping, live tickets from backlog to production" width="100%" />
  </a>
</p>
<p align="center">
  <sub><b>Hero:</b> Delivery flow matrix showing real tickets from backlog to production across feature, bug, and maintenance lanes. <a href="https://stevengonsalvez.github.io/foundry-autonomous-sdlc/control-center/">Open live control center &rarr;</a></sub>
</p>

| | | |
|---|---|---|
| <a href="https://stevengonsalvez.github.io/foundry-autonomous-sdlc/control-center/#/ticket/93"><img src="docs/proof/control-center-ticket-desktop.png" alt="Ticket view with stage strip, gates table and timeline" width="100%" /></a><br />**Ticket detail (#93)**: Stage strip, verification gates, and event timeline | <a href="https://stevengonsalvez.github.io/foundry-autonomous-sdlc/control-center/#/environments"><img src="docs/proof/control-center-environments-desktop.png" alt="Environments view with staging and production hops" width="100%" /></a><br />**Environments**: Live staging and production hops with target deployments | <a href="https://stevengonsalvez.github.io/foundry-autonomous-sdlc/control-center/#/cost"><img src="docs/proof/control-center-cost-desktop.png" alt="Cost view with ledger estimate and Azure billed spend" width="100%" /></a><br />**Cost**: Ledger estimate versus Azure billed spend, billing cap, and meters |
| <a href="https://stevengonsalvez.github.io/foundry-autonomous-sdlc/control-center/#/agents"><img src="docs/proof/control-center-agents-desktop.png" alt="Agent health and activity status" width="100%" /></a><br />**Agents**: Health status and ledger invocation metrics for all 11 agents | <a href="https://stevengonsalvez.github.io/foundry-autonomous-sdlc/control-center/#/escalations"><img src="docs/proof/control-center-escalations-desktop.png" alt="Escalations view with resolved items" width="100%" /></a><br />**Escalations (live)**: Live queue showing 0 open and 19 resolved incidents | <a href="https://stevengonsalvez.github.io/foundry-autonomous-sdlc/control-center/#/flow"><img src="docs/proof/control-center-flow-desktop.png" alt="Flow metrics view with cycle times" width="100%" /></a><br />**Flow metrics**: Stage cycle times, lead time breakdown, and defect resolution |
| <a href="https://stevengonsalvez.github.io/foundry-autonomous-sdlc/control-center/#/trail"><img src="docs/proof/control-center-trail-desktop.png" alt="Review and questions-back trail" width="100%" /></a><br />**Review trail**: Questions-back history and independent review decisions | <a href="https://stevengonsalvez.github.io/foundry-autonomous-sdlc/control-center/"><img src="docs/proof/control-center-board-mobile.png" alt="Mobile delivery flow board" width="100%" /></a><br />**Mobile board**: Responsive delivery flow matrix at 390px mobile viewport | <a href="https://stevengonsalvez.github.io/foundry-autonomous-sdlc/control-center/"><img src="docs/proof/control-center-board-cost-desktop.png" alt="Board with Cost lens" width="100%" /></a><br />**Cost lens**: Board matrix with Cost lens highlighting budget cap usage |
| <a href="https://stevengonsalvez.github.io/foundry-autonomous-sdlc/control-center/"><img src="docs/proof/control-center-board-gates-desktop.png" alt="Board with Gates lens" width="100%" /></a><br />**Gates lens**: Board matrix with Gates lens highlighting verification criteria | <a href="https://stevengonsalvez.github.io/foundry-autonomous-sdlc/control-center/"><img src="docs/proof/control-center-board-group-agent-desktop.png" alt="Board grouped by agent" width="100%" /></a><br />**Agent grouping**: Delivery flow matrix grouped by autonomous agent swimlane | <a href="https://stevengonsalvez.github.io/foundry-autonomous-sdlc/control-center/"><img src="docs/proof/control-center-board-group-outcome-desktop.png" alt="Board grouped by outcome" width="100%" /></a><br />**Outcome grouping**: Delivery flow matrix grouped by release outcome status |
| <img src="docs/proof/control-center-escalations-fixture.png" alt="Fixture shot: open escalation queue" width="100%" /><br />**Fixture: Escalation queue**: Historical test fixture showing open escalations with triage steps and reasons | <img src="docs/proof/control-center-environments-fixture.png" alt="Fixture shot: rollback and failure history" width="100%" /><br />**Fixture: Rollback history**: Historical test fixture showing deployment failures and rollback events | <img src="docs/proof/control-center-stale-banner-fixture.png" alt="Fixture shot: spend halt banner and stale snapshot alert" width="100%" /><br />**Fixture: Spend halt banner**: Historical test fixture showing spend limit halt banner and stale snapshot alert |

<p align="center">
  <img src="docs/media/hero.svg" alt="Autonomous SDLC motion header: live topology network and 4 delivery flow lanes for feature, bug, escalation, and rollback" width="100%" />
</p>

An issue is filed. Agents on Azure AI Foundry score and refine the requirement, judge whether an agent can do the work, write failing tests first, build until the tests pass, review independently, merge and release. No human step. This repository is the demonstration, and every claim below links to a command you can run or a trace you can click.

## How the app evolved

See the visual timeline across releases on the [**App Evolution Showcase**](https://stevengonsalvez.github.io/foundry-autonomous-sdlc/history/).

<p align="center">
  <a href="https://stevengonsalvez.github.io/foundry-autonomous-sdlc/history/">
    <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/releases/v0.1.0/home-desktop.png" alt="v0.1.0: Home page at launch" width="31%" />
  </a>
  <a href="https://stevengonsalvez.github.io/foundry-autonomous-sdlc/history/">
    <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/releases/v0.3.1/home-desktop.png" alt="v0.3.1: Update the home page heading copy" width="31%" />
  </a>
  <a href="https://stevengonsalvez.github.io/foundry-autonomous-sdlc/history/">
    <img src="https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/releases/v0.4.0/parcel-found-desktop.png" alt="v0.4.0: Show how many tracking events a parcel has" width="31%" />
  </a>
</p>
<p align="center">
  <sub><b>Left:</b> v0.1.0 (home page) &nbsp;|&nbsp; <b>Center:</b> v0.3.1 (heading copy) &nbsp;|&nbsp; <b>Right:</b> v0.4.0 (tracking events) | <a href="https://stevengonsalvez.github.io/foundry-autonomous-sdlc/history/">Explore interactive history &rarr;</a></sub>
</p>

## System topology

<p align="center">
  <img src="docs/media/topology.svg" alt="Animated system topology of the autonomous SDLC connecting GitHub, Routine timer, Orchestrator, Prompt agents, Coder, CI gates, Continuous Deployment, Ledger, and Control Center" width="100%" />
</p>

## Real execution scenarios

The animations below are built from authentic recorded traces in branch `origin/state` (`events.jsonl` and `state.json`). Timings are compressed for demonstration (actual wall-clock runtimes: 2m to 18m). Pure vector animated SVGs with GIF fallbacks in `docs/media/`.

<details open>
<summary><b>Scenario 1: Feature happy path (Issue #24, PR #29, Release v0.3.0)</b></summary>

Requirement scored, bounced below 80, refined by simulated product owner to 90, feasibility confirmed, TDD failing test committed first (`c0f5713`), implemented until green (`fcc6f1e`), approved by independent review, all 6 CI checks green, staged, smoke and 10-minute soak verified, released to prod. Total cost: $0.0816 USD.

<p align="center">
  <img src="docs/media/scenario-feature.svg" alt="Scenario 1 animation: feature happy path from intake through simulated refinement, TDD red commit, green build, review, and production soak to release" width="100%" />
</p>

</details>

<details open>
<summary><b>Scenario 2: Bug with failing regression test first (Issue #25, PR #26, Release v0.1.1)</b></summary>

Bug triaged automatically (severity s3, owner api), requirement scored 83, failing regression test committed first (`6816a92`), fix committed (`a132025`), reviewed and verified across 6 gates, released. Total cost: $0.0368 USD.

<p align="center">
  <img src="docs/media/scenario-bug.svg" alt="Scenario 2 animation: bug with failing regression test committed first before the fix, clearing 6 CI gates to release" width="100%" />
</p>

</details>

<details open>
<summary><b>Scenario 3: Vague requirement and not-agent-suitable escalation (Issue #17)</b></summary>

Initial requirement scored below 80 and bounced, simulated product owner clarifies scope, feasibility agent evaluates against repository contracts and judges not suitable (requires live production secrets, DNS/firewall changes, vendor agreement). Cleanly halted on the coral escalation path for human operator with zero rogue code edits. Total cost: $0.0153 USD.

<p align="center">
  <img src="docs/media/scenario-escalation.svg" alt="Scenario 3 animation: vague requirement bounced for refinement, evaluated by feasibility agent, and escalated in coral tone to human operator" width="100%" />
</p>

</details>

<details open>
<summary><b>Scenario 4: Continuous deployment smoke fail and rollback (PR #46 / Run 38180836579)</b></summary>

Merged commit `8137c60` deployed to `/staging/`. Playwright smoke test fails on staging. Automated rollback immediately restores previous healthy production build (`641cb02`). Ticket flagged with label `escalated:deploy-failed`. Production root remains untouched with zero downtime.

<p align="center">
  <img src="docs/media/scenario-rollback.svg" alt="Scenario 4 animation: continuous deployment smoke test failure on staging triggering automated rollback and ticket escalation" width="100%" />
</p>

</details>

## What it shows

| Problem | What this repo does about it |
|---------|------------------------------|
| Test design and evidence are manual and slow | Agents write the tests first, then build; every PR carries its red and green output |
| Poor requirement quality derails humans and agents | A scoring gate (80 percent) sends vague issues back with questions; a labelled simulated product owner answers |
| Triage is pass-the-parcel | A triage agent assigns severity and an owner; resolution time is charted |
| Bugs rarely become tests | Every bug gets a failing regression test before the fix |
| Mock APIs and contract tests come late | The app has an OpenAPI carrier contract, a mock server and contract tests |
| Test automation rots | A maintenance flow repairs a deliberately stale test |
| No golden path for Foundry agents | Terraform modules, a bootstrap, a deploy script and a runbook |

## Documentation

| Doc | What |
|-----|------|
| [`docs/architecture.md`](docs/architecture.md) | Contracts: agents, state machine, labels, ledger events and state |
| [`docs/decisions.md`](docs/decisions.md) | Design decisions and the alternatives rejected |
| [`docs/findings.md`](docs/findings.md) | Measured facts and problems found while running it |
| [`docs/evidence.md`](docs/evidence.md) | Issue to release traces for every scenario |
| [`docs/final-report.md`](docs/final-report.md) | Success criteria and their evidence |
| [`docs/control-center-report.md`](docs/control-center-report.md) | Control center, continuous deployment and ledger build report |
| [`docs/cd.md`](docs/cd.md) | Staging, smoke, soak, promote and rollback |
| [`docs/runbook.md`](docs/runbook.md) | Bootstrap, deploy, operate, tear down |
| [`docs/research/sandboxing-security-options.md`](docs/research/sandboxing-security-options.md) | Security review, threat model and sandboxing options for the coder, with a phased plan |
| [`docs/research/foundry-evaluations.md`](docs/research/foundry-evaluations.md), [`docs/research/foundry-evaluations-demo.md`](docs/research/foundry-evaluations-demo.md) | Agent evaluations research, options matrix, proof run against demo project, and options demo walkthrough |
| [`docs/app-spec.md`](docs/app-spec.md) | Spec of the parcel tracker demo app |
| [`docs/poc-spec.md`](docs/poc-spec.md), [`docs/poc-findings.md`](docs/poc-findings.md) | The earlier Actions-driven proof of concept: spec and findings |
| [`docs/explainer/`](docs/explainer/README.md) | Visual explainer of the whole system |
| [`docs/proof/`](docs/proof/) | Screenshots of the app, dashboard and control center, including the live runs |
| [`apps/control-center/README.md`](apps/control-center/README.md), [`PRODUCT.md`](apps/control-center/PRODUCT.md), [`DESIGN.md`](apps/control-center/DESIGN.md), [`RESEARCH-flowtron.md`](apps/control-center/RESEARCH-flowtron.md) | Control center usage, product brief, design system, UI research |
| [`dashboard/README.md`](dashboard/README.md) | Metrics dashboard |
| [`agents/README.md`](agents/README.md), [`app/README.md`](app/README.md) | Agents package and demo app |
| [`infra/terraform/README.md`](infra/terraform/README.md), [`bootstrap`](infra/terraform/bootstrap/README.md) | Terraform stack and remote-state bootstrap |
| [`reference/actions-sandbox/README.md`](reference/actions-sandbox/README.md) | The earlier Actions sandbox, kept for comparison |

Live repository views: [issues](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/issues), [pull requests](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/pulls), [releases](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/releases), [Actions runs](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/actions), [the `state` branch](https://github.com/stevengonsalvez/foundry-autonomous-sdlc/tree/state) (`state.json` and `events.jsonl` written by the ledger).

## The gates

Every agent PR must pass seven required checks on the exact head commit before the orchestrator may merge it, and GitHub enforces the same seven server side (branch ruleset `main-gates`, no bypass actors):

| Check | Passes when |
|-------|-------------|
| `test` | lint, typecheck, unit, component and contract tests pass |
| `coverage` | line coverage is at least 80 percent |
| `e2e` | Playwright tests pass |
| `gitleaks` | no secrets in the PR range |
| `tdd-order` | the first commit is tests only, the tests fail for the right reason (an assertion, not a load error), and later commits do not edit them |
| `agent-scope` | an agent branch only touches `app/` |
| `evals` | deterministic replay of recorded requirement-gate outputs matches golden expectations |

On top of that the orchestrator requires a review marker from the independent review agent for the same head commit, owner authorship, a cost under the cap, and that every changed file is under `app/`.

## Safety model in one table

| Risk | Control |
|------|---------|
| A stranger files an issue to spend money | Only issues and PRs by the repo owner are acted on |
| Prompt injection through issue text | All issue, PR and file text is delimited untrusted data; outputs are schema checked and sanitised; labels, paths and commands are allow-listed |
| The coding CLI is tricked into stealing secrets | It runs as an unprivileged user with an environment built from nothing; the GitHub token exists only in short-lived git subprocesses owned by the coder process; checkouts are scanned for links, nested repos and out-of-scope paths before every push |
| The coding CLI or the code it runs sends data to, or pulls from, an arbitrary host | Optional and off by default (preview): an egress policy on the coder's hosted agent version, a default-deny allow-list of exact hosts, switched by `coder_egress_mode`. Enforced was measured to refuse unlisted HTTPS hosts and all plain HTTP, but no real coder job has run behind it, so it stays off until that gate is passed ([`docs/runbook.md`](docs/runbook.md) section 9). Audit blocks nothing and its decisions are not yet observable. It limits destinations, not misuse of allowed hosts: a `git push` or `npm publish` to an allowed host still works |
| Runaway spend | 3 USD per issue, 32 USD halt and 35 USD total (fail closed), 2 hour coder deadline, minimum idle timeouts. The ledger's estimate undercounts hosted compute, so the control center shows Azure's billed figure beside it (see the cost view and `docs/runbook.md`, "Spend finding") |
| A bad release reaches users | Staging first, Playwright smoke on the live staging URL, a 10 minute soak, then the same artifact is promoted; any failure restores the artifact prod already serves and flags the ticket |
| Secrets in the repo | None. Credentials live in Key Vault; gitleaks runs in CI and over full history before every push, and GitGuardian ([`gitguardian.yml`](.github/workflows/gitguardian.yml)) scans the full history on every push to `main` and weekly. Its key is only readable by workflows that run from `main`, never by a pull request |

Design decisions are in [`docs/decisions.md`](docs/decisions.md), measured facts and the problems found while running it are in [`docs/findings.md`](docs/findings.md), the contracts are in [`docs/architecture.md`](docs/architecture.md).

## Layout

| Path | What |
|------|------|
| [`app/`](app/) | The parcel tracker: `core`, `carrier-mock` (OpenAPI), `api`, `web` (React, Vite), `e2e` (Playwright) |
| [`agents/`](agents/) | Orchestrator logic, prompt agent definitions, the coder runtime and the hosted agent entry points |
| [`evals/`](evals/) | Offline requirement-gate replay and mutation tests (blocking CI gate) |
| [`infra/terraform/`](infra/terraform/) | Foundry, Key Vault, observability and budget modules, plus a remote-state bootstrap |
| [`scripts/`](scripts/) | Deploy script, repo setup, merge gate scripts, scenario runner, evidence collector, Pages assembly |
| [`dashboard/`](dashboard/) | The static metrics dashboard |
| [`apps/control-center/`](apps/control-center/) | The read-only control center (8 views, no build, no token) |
| [`agents/sdlc_agents/ledger/`](agents/sdlc_agents/ledger/) | The state-keeper: events, ticket model, fold, reconcile, branch writer; hosted as `sdlc-ledger` or run inline |
| [`scripts/cd/`](scripts/cd/), [`.github/workflows/cd.yml`](.github/workflows/cd.yml) | Continuous deployment: staging, smoke, soak, promote or rollback (see [`docs/cd.md`](docs/cd.md)) |
| [`scenarios/`](scenarios/) | The four scripted scenarios |
| [`reference/`](reference/) | The earlier Actions-driven version, kept for comparison |

## Run it yourself

Everything is in [`docs/runbook.md`](docs/runbook.md): sign in, `terraform apply` from clean, load two secrets into Key Vault, deploy the agents, enable the routine, file the scenario issues with `scripts/run_scenarios.py`. A fresh clone was bootstrapped, applied and destroyed this way: see "Fresh clone reproduction" in the findings.

## Principles

- No secrets in the repository. Tests are committed before the code that makes them pass. CI never drives agents. All content is synthetic.

## License

MIT
