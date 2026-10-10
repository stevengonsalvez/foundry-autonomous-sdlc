# foundry-autonomous-sdlc

A public, self-contained demonstration of an autonomous, test-driven software lifecycle run by Azure AI Foundry agents.

An issue is filed. Agents score and refine the requirement, research whether an agent can do the work, write failing tests first, a coding CLI agent running in a Foundry hosted agent builds until the tests pass, an independent agent reviews, the change merges and release notes are produced. No human step.

**Status: under construction.** This repository starts from the infrastructure and agent code of an earlier proof of concept. The demo app, orchestration, scenarios and dashboard are being built by the agents themselves; progress and decisions are in `docs/`.

## What is here

| Path | What |
|------|------|
| `infra/terraform/` | Terraform modules (Foundry, observability, budget, GitHub OIDC) and a remote-state bootstrap |
| `agents/` | `sdlc_agents` package: Foundry prompt agent definitions, schemas, output validation |
| `reference/actions-sandbox/` | The earlier GitHub Actions-driven version, kept as history and for comparison |
| `docs/poc-spec.md`, `docs/poc-findings.md` | Scope, measured results, costs and known gaps from the proof of concept |

## Principles

- No secrets in the repository. Credentials live in a vault and are read through managed identity.
- Tests are written and committed before the code that makes them pass.
- CI runs plain checks only; it never drives the agents.
- All content here is synthetic. No proprietary code or data.

## License

MIT
