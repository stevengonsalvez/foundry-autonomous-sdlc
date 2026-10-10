# Azure AI Foundry agents across the SDLC: proof of concept findings

Date: 2026-10-09. Environment: personal Azure Free Trial subscription (200 USD credit, spending limit on), UK South. Code and data: a public, synthetic sandbox repo only. No proprietary code or data was used.

## Result

All four stage groups from the spec work end to end, triggered from GitHub Actions, using one `gpt-5-mini` deployment and five Foundry prompt agents. The whole stack stood up from `terraform apply` and costs about 0.01 to 0.02 USD per full run.

| Stage | Trigger | Agent | Result | Verified live |
|-------|---------|-------|--------|---------------|
| Issue triage and spec | label `agent:triage` | `sdlc-triage` | Labels, summary, acceptance criteria, tasks posted as a comment | yes |
| Code gen to draft PR | label `agent:implement` | `sdlc-codegen` | Draft PR editing the existing file, never merged | yes |
| PR review and tests | PR opened by owner | `sdlc-review` | Severity-tagged review comment | yes |
| CI failure triage | CI fails on a PR | `sdlc-ci-triage` | Root cause, evidence quotes, next step | yes |
| Release notes | manual dispatch with tag | `sdlc-release-notes` | Release body updated | yes |

Demo repo: https://github.com/stevengonsalvez/foundry-sdlc-sandbox (issue 1, PRs 6 and 7, release v0.1.0).

## Architecture

```
┌─────────┐   ┌───────────────┐   ┌──────────────────────┐
│ GitHub  │──▶│ Actions (OIDC)│──▶│ Foundry prompt agent │
│ event   │   │ owner-only    │   │ gpt-5-mini, UK South │
└─────────┘   └───────┬───────┘   └──────────┬───────────┘
     ▲                │ writes only here     │ text/JSON only
     └── comment / label / DRAFT PR ◀─────────┘
```

Agents return text or JSON. The Action fetches inputs and performs every GitHub write. The implement workflow is split into a generate job (Azure login, no write token) and a publish job (write token, no Azure) with an allow-list of `src/`, `tests/`, `docs/`.

## What the research changed in the original spec

| Spec assumption | What verification found | Action taken |
|-----------------|-------------------------|--------------|
| Foundry workflows chain the agents | Workflows are a preview portal feature that Microsoft retires on 2026-12-01 | GitHub Actions orchestrate prompt agents |
| Nano-class models | Quota is 0 for all nano models on the trial; `gpt-5-mini` has 500K TPM in UK South | `gpt-5-mini`, 10K TPM cap |
| Pay-as-you-go upgrade may be needed | Not needed for this stack | Spending limit stays on |
| Invoke-only identity for CI | `Foundry Agent Consumer` and a custom data-action role both returned an empty HTTP 403 on the project responses endpoint | `Foundry User` on the project scope (accepted gap) |
| Copilot has no unattended automation | GitHub Agentic Workflows and Fix with Copilot exist; Copilot cloud agent can use private-network runners | See comparison below |

Initial desk research was wrong in roughly a third of its load-bearing claims (stale models, invented terms, a Terraform block that fails `validate`), so every claim here was re-checked against live Microsoft and GitHub documentation and the Azure Retail Prices API on 2026-10-09. Treat unverified research as a draft.

## Cost

Measured token usage from workflow logs, priced at the Retail Prices API rates for `gpt-5-mini` Global Standard in UK South (0.25 USD per 1M input, 2.00 USD per 1M output).

| Stage | Input tokens | Output tokens | Approx USD per call |
|-------|--------------|---------------|---------------------|
| triage | about 550 | 300 to 1,000 | 0.001 |
| codegen (with source context) | about 6,700 | about 1,450 | 0.005 |
| review | about 7,500 | about 570 | 0.003 |
| ci-triage | about 850 | about 1,470 | 0.003 |
| release notes | about 550 | about 1,300 | 0.003 |

A full issue to release cycle is about 0.015 USD. Eight agent runs in the live demo used about 24K input and 8K output tokens, roughly 0.02 USD. Fixed infra with no traffic: nothing billable beyond log ingestion above the free 5 GB per month.

Guardrails in place: budget with 25, 50 and 75 percent alerts, 10K TPM deployment cap, 10 minute job timeouts, input and output token caps, owner-only triggers on a public repo, one resource group so `terraform destroy` removes everything. Note that budget alerts lag usage by up to about 72 hours and the cost APIs are not available on this offer type, so the TPM cap is the real brake. A 10K TPM cap still allows roughly 1 USD per hour of runaway spend.

## Copilot versus Foundry

Short version:

| Use | When |
|-----|------|
| Copilot | Code lives in GitHub and the goal is issue to PR, PR review, and IDE help. It is already licensed and has native sandboxing and PR integration. Do not rebuild it. |
| Foundry agents | You need model choice or bring-your-own model, UK data residency control, private networking, governance and tracing, or triggers and inputs outside GitHub (for example Azure DevOps, ServiceNow, Jira). |
| Both | Copilot for the developer loop; Foundry agents for headless policy, triage and reporting jobs that run without a developer. |

What the PoC showed honestly: a prompt-only `gpt-5-mini` agent needs the right context handed to it. The first codegen attempt received only the issue text and produced a new file and deleted 99 lines of tests. With source files in the prompt it produced a small correct edit to the real file. Quality is bounded by the cheap model and by the context the Action supplies, not by the platform.

## Gaps and follow-ups

- CI identity has `Foundry User` at project scope, so it could create agents in this one project. Find the exact missing data action and replace with a custom role (an empty 403 gave no hint).
- Public endpoint, no private networking (documented PoC decision).
- Pip dependencies are version pinned but not hash pinned.
- Agent PRs opened with `GITHUB_TOKEN` do not start workflows; the owner closes and reopens to run CI and review.
- Nano models need a quota request (aka.ms/oai/stuquotarequest, no published turnaround).
- Global Standard deployments are not UK-resident processing; use a regional Standard deployment for UK-only needs.
- Dependabot and Renovate opened unrelated PRs on the public sandbox. Remove or configure them.
- The sandbox ruleset requires PRs on `main`; the repo owner can bypass it.
- The `pull_request` federated credential (subject `repo:<owner>/<repo>:pull_request`) trusts any same-repo pull request. Anyone who can push a branch can edit the review workflow in their PR head and obtain a Foundry User token. This is acceptable only because the sandbox has a single owner and no collaborators. Fix options: scope the credential to a GitHub environment with required reviewers, or run the review from a default-branch `workflow_run` or `pull_request_target` workflow so the PR cannot change the code that holds the token.

## How to run and tear down

1. `az login` to the target subscription. Create the remote state store once: follow `infra/terraform/bootstrap/README.md` (it also lists the steps to move state across).
2. `cd infra/terraform`, copy the `terraform.tfvars` values (subscription id, GitHub owner, repo, numeric owner and repo ids), then `terraform init -backend-config=backend.hcl && terraform apply`. The stack is split into the `foundry`, `observability`, `github-oidc` and `budget` modules under `infra/terraform/modules`.
3. `cd agents && FOUNDRY_PROJECT_ENDPOINT=<output> uv run python -m sdlc_agents.create_agents`.
4. `scripts/sync-sandbox.sh` keeps the vendored `sdlc_agents` in the sandbox identical to `agents/`. Publish `sandbox/` to the GitHub repo, set the four repository variables from the Terraform outputs, and follow `sandbox/README.md`.
5. Tear down: `terraform destroy` in `infra/terraform`, then `terraform destroy -var-file=bootstrap.tfvars` in `infra/terraform/bootstrap`. Two destroys remove everything.

CI (`.github/workflows/infra-ci.yml`) runs terraform fmt, validate, tflint, checkov, both pytest suites, the sandbox sync check and actionlint on every PR.
