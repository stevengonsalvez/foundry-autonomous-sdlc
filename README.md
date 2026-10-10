# foundry-autonomous-sdlc

An issue is filed. Agents on Azure AI Foundry score and refine the requirement, judge whether an agent can do the work, write failing tests first, build until the tests pass, review independently, merge and release. No human step. This repository is the demonstration, and every claim below links to a command you can run or a trace you can click.

```
┌──────────┐ every 5 min ┌──────────────────┐ Responses  ┌────────────────────────┐
│ GitHub   │◀───────────▶│ sdlc-orchestrator│───────────▶│ prompt agents          │
│ issues   │  labels,    │ hosted agent     │            │ req-gate, feasibility, │
│ PRs      │  merges,    │ (Routine wakes   │            │ test-designer, PO,     │
│ checks   │  releases   │  it)             │            │ reviewer, triage, notes│
└────▲─────┘             └────────┬─────────┘            └────────────────────────┘
     │ opens its own PR           │ Invocations
     │                   ┌────────▼─────────┐
     └───────────────────│ sdlc-coder       │  git, node, agy CLI, tests,
                         │ hosted agent     │  typecheck and lint until green
                         └──────────────────┘
CI is plain tests and gates. It never drives an agent.
```

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

## Live demo

- App: <https://stevengonsalvez.github.io/foundry-autonomous-sdlc/>
- Metrics dashboard (cycle time per stage, defect owner and resolution time, cost per issue, gate pass rates): <https://stevengonsalvez.github.io/foundry-autonomous-sdlc/dashboard/>
- Traces of every scenario, from issue to release: [`docs/evidence.md`](docs/evidence.md)
- Final report with the success criteria and their evidence: [`docs/final-report.md`](docs/final-report.md)

## The gates

Every agent PR must pass six required checks on the exact head commit before the orchestrator may merge it, and GitHub enforces the same six server side (branch ruleset `main-gates`, no bypass actors):

| Check | Passes when |
|-------|-------------|
| `test` | lint, typecheck, unit, component and contract tests pass |
| `coverage` | line coverage is at least 80 percent |
| `e2e` | Playwright tests pass |
| `gitleaks` | no secrets in the PR range |
| `tdd-order` | the first commit is tests only, the tests fail for the right reason (an assertion, not a load error), and later commits do not edit them |
| `agent-scope` | an agent branch only touches `app/` |

On top of that the orchestrator requires a review marker from the independent review agent for the same head commit, owner authorship, a cost under the cap, and that every changed file is under `app/`.

## Safety model in one table

| Risk | Control |
|------|---------|
| A stranger files an issue to spend money | Only issues and PRs by the repo owner are acted on |
| Prompt injection through issue text | All issue, PR and file text is delimited untrusted data; outputs are schema checked and sanitised; labels, paths and commands are allow-listed |
| The coding CLI is tricked into stealing secrets | It runs as an unprivileged user with an environment built from nothing; the GitHub token exists only in short-lived git subprocesses owned by the coder process; checkouts are scanned for links, nested repos and out-of-scope paths before every push |
| Runaway spend | 1 USD per issue, 4.50 USD total (fail closed), 2 hour coder deadline, minimum idle timeouts |
| Secrets in the repo | None. Credentials live in Key Vault; gitleaks runs in CI and over full history before every push |

Design decisions are in [`docs/decisions.md`](docs/decisions.md), measured facts and the problems found while running it are in [`docs/findings.md`](docs/findings.md), the contracts are in [`docs/architecture.md`](docs/architecture.md).

## Layout

| Path | What |
|------|------|
| `app/` | The parcel tracker: `core`, `carrier-mock` (OpenAPI), `api`, `web` (React, Vite), `e2e` (Playwright) |
| `agents/` | Orchestrator logic, prompt agent definitions, the coder runtime and the hosted agent entry points |
| `infra/terraform/` | Foundry, Key Vault, observability and budget modules, plus a remote-state bootstrap |
| `scripts/` | Deploy script, repo setup, merge gate scripts, scenario runner, evidence collector, Pages assembly |
| `dashboard/` | The static metrics dashboard |
| `scenarios/` | The four scripted scenarios |
| `reference/` | The earlier Actions-driven version, kept for comparison |

## Run it yourself

Everything is in [`docs/runbook.md`](docs/runbook.md): sign in, `terraform apply` from clean, load two secrets into Key Vault, deploy the agents, enable the routine, file the scenario issues with `scripts/run_scenarios.py`. A fresh clone was bootstrapped, applied and destroyed this way: see "Fresh clone reproduction" in the findings.

## Principles

- No secrets in the repository. Tests are committed before the code that makes them pass. CI never drives agents. All content is synthetic.

## License

MIT
