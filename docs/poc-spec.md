# Specification: Azure AI Foundry Agents SDLC Proof of Concept

**Generated from:** interview (no plan file; inline request)
**Interview date:** 2026-10-08
**Version:** 1.0

## Executive Summary

Stand up a reproducible Azure AI Foundry environment (Terraform) on a personal Azure free account with 200 USD credit, and prove structure and capability of Foundry Agent Service across the software development lifecycle. Agents are triggered from GitHub, run on the cheapest viable models, and act with human-in-loop authority only. The output also tells an enterprise reader what Foundry gives out of the box versus what GitHub Copilot already covers.

```
┌─────────┐   ┌────────────┐   ┌──────────────────┐
│ GitHub  │──▶│ Action /   │──▶│ Foundry Agent    │
│ issue/PR│   │ OIDC to Az │   │ Service+workflows│
└─────────┘   └────────────┘   └────────┬─────────┘
     ▲                                  │
     └──── comment / label / draft PR ◀─┘

Dev IDE: Copilot (untouched, separate lane)
```

## Objectives

### Primary Goals
- Reference IaC: `terraform apply` from a clean subscription to a working Foundry project, plus `terraform destroy` to remove all billable resources.
- SDLC agent PoC on Foundry Agent Service with Foundry workflows, covering four stage groups below.
- Clear picture of where Foundry agents sit next to GitHub Copilot.

### Success Metrics
- [ ] End-to-end demo on a sample repo: issue to spec to draft PR to review and tests to CI triage to release notes, triggered from GitHub.
- [ ] Cost per run measured (tokens and USD per stage, from tracing), projected to a team of N developers.
- [ ] Capability and gap matrix: Foundry out of the box vs needs custom code vs Copilot already covers.
- [ ] Clean-to-working `terraform apply` reproducible by anyone with a subscription, with README.

## Scope

### In Scope
| Stage group | Agent behaviour |
|-------------|-----------------|
| Issue triage + spec | Label issue, write acceptance criteria and task breakdown |
| Code gen to PR | Propose patch, open DRAFT PR on sandbox repo |
| PR review + test gen | Review diff, comment risks, write tests for changed code |
| CI triage + docs/release notes | Explain failed workflow logs, generate changelog from merged PRs |

- Terraform for Foundry resource, project, model deployments, identity, RBAC, budget.
- GitHub Actions workflows with OIDC federation to Azure.
- Tracing and cost measurement per run.

### Out of Scope
- Proprietary code or data. Public or synthetic repos only (a personal subscription is outside any corporate tenant).
- Private networking (VNet, private endpoints). Documented as a known gap for production.
- Auto-merge or any agent write beyond draft PRs, comments and labels.
- Code-first orchestration with Microsoft Agent Framework (not chosen this round).
- Paid tools: Bing grounding, paid AI Search tier.

### Future Considerations
- Copilot overlaps more than first assumed (cloud agent, code review, Agentic Workflows preview, Fix with Copilot). See the Copilot versus Foundry section in docs/findings.md. Foundry value is model choice, headless non-GitHub triggers, governance and tracing, not issue-to-PR.
- Code-first orchestration comparison against Foundry workflows.
- Foundry agents exposed to Copilot via MCP.
- Private networking and BYO storage/search for a production shape.
- Real, sanitised enterprise code, after sign-off.

## Technical Requirements

### Architecture
Foundry Agent Service prompt agents, chained by GitHub Actions (workflow_dispatch / repository_dispatch). Agents take a prompt and return structured text; the Action fetches diffs and logs and performs all GitHub writes. Foundry workflows are NOT used: Microsoft retires them on 2026-12-01 (Microsoft Learn workflow page, checked 2026-10-09). GitHub is the trigger and the sink. Copilot remains the IDE tool and is not integrated; it is a separate lane in the comparison.

### Components
| Component | Purpose | Technology |
|-----------|---------|------------|
| Infra | Reproducible environment | Terraform (azurerm/azapi; verify Foundry resource coverage) |
| Foundry resource + project | Host agents, models, tracing | Azure AI Foundry |
| Model deployments | Cheap inference | gpt-5-mini GlobalStandard in uksouth, 50K TPM (only cheap model with quota on the trial). Nano models (gpt-5.4-nano, gpt-5-nano) need a quota request; optional |
| Prompt agents | SDLC stages | Foundry Agent Service prompt agents, invoked via azure-ai-projects>=2.3.0 or REST responses API |
| Trigger/sink | Events in, comments and draft PRs out | GitHub Actions, GitHub App or fine-scoped token |
| Auth | Keyless access | Managed identity, Entra RBAC, GitHub OIDC |
| Observability | Cost and trace per run | Foundry tracing with Application Insights (verify free allowance) |
| Cost control | Budget and caps | Azure budget, low TPM quota per deployment |

### Integrations
- GitHub to Azure: Actions with OIDC federated credential, no stored Azure secrets.
- Azure to GitHub: write-back via a least-privilege GitHub App or fine-grained token held outside the repo (verify the cleanest keyless option).

### Performance Requirements
- None. Intelligence and latency are explicitly not the goal.

### Security Requirements
- Identity-first: managed identity, Entra RBAC, OIDC, zero API keys in GitHub secrets where the platform allows.
- Public endpoints accepted for PoC; record the gap.
- Branch protection on the sandbox repo so agents cannot push to protected branches or merge.

## Constraints & Dependencies

### Technical Constraints
- Free account credit is 200 USD and expires 30 days after signup; spending limit is ON (hard cap). No Pay-As-You-Go upgrade needed: the trial already has gpt-5-mini quota (500K TPM, matches Microsoft Tier 0 table).
- Entra roles: Foundry User to create and run agents, Foundry Agent Consumer to invoke only. Not Azure AI Developer. local_auth_enabled = false.
- A 50K TPM cap still allows roughly 6 USD/hour of runaway spend: also set Actions timeouts, concurrency limit and max_output_tokens.
- Application Insights: first 5 GB/month free in UK South.
- Low TPM quota on every deployment to prevent runaway loops.
- Single resource group per environment so one destroy removes everything billable.

### External Dependencies
- Azure subscription with quota for the chosen model in a supported region.
- GitHub org or personal account for the sandbox repo and Actions minutes.
- Terraform provider support for the Foundry resources needed.

### Timeline Constraints
- Do everything now, no phased milestones. Credit expiry is the hard outer bound; check the signup date.

## Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Credit burned by agent loop | High | Med | Low TPM quota, budget alerts at 25/50/75%, destroy script |
| Terraform lacks coverage for a Foundry resource | Med | Med | Use azapi for gaps, note in gap matrix |
| Foundry workflows retire 2026-12-01 | Med | High | Not used; Actions orchestrate prompt agents |
| Free account model quota or region limits | Med | Med | Check quota before design; pick region accordingly |
| Code-gen stage low quality on nano models | Low | High | Expected; goal is structure. Allow mini for that stage |
| Credit expiry mid-project | High | Low | Check signup date; avoid dependence on expiring resources for the write-up |
| Alerts do not stop spend | Med | Med | Rely on TPM caps and destroy, not alerts alone |

## Decisions Made

### Key Trade-offs
- **Decision:** Deliverable is reference IaC plus SDLC PoC.
  **Alternatives considered:** learning sandbox only, decision paper only, all three.
  **Rationale:** repeatable structure is what an enterprise can reuse.
- **Decision:** Copilot lane is separate; Foundry agents are GitHub-triggered.
  **Alternatives considered:** MCP exposure to Copilot, side-by-side only.
  **Rationale:** clean split (Copilot = human-in-loop IDE, Foundry = automated pipeline), least plumbing.
- **Decision:** Terraform.
  **Alternatives considered:** Bicep + azd, portal first.
  **Rationale:** user choice; likely aligns with enterprise platform tooling. Costs: provider coverage for new Foundry resources may need azapi.
- **Decision:** Public or synthetic repos only.
  **Rationale:** personal subscription, no IG/security exposure.
- **Decision (revised 2026-10-09):** Foundry Agent Service prompt agents orchestrated by GitHub Actions. Foundry workflows rejected (retire 2026-12-01); Agent Framework deferred.
  **Rationale:** verified research shows workflows are a preview portal feature being retired; gpt-5-mini cannot use function/OpenAPI/A2A tools, so agents are prompt-in/text-out and the Action does fetch and write.
- **Decision (revised 2026-10-09):** gpt-5-mini GlobalStandard, uksouth, 50K TPM, one deployment for all stages (about 0.06 USD per full four-stage run). gpt-4o-mini, gpt-4.1-nano/mini deprecated; o4-mini retires 2026-11-19. Global Standard is not UK-resident; UK-only processing would need a Standard regional deployment (production note).
- **Decision:** Identity-first security, no private networking.
- **Decision:** Agents limited to comments, labels, draft PRs; human merges.
- **Decision:** Guardrails: budget alerts, low TPM quota, single RG destroy, skip paid tools.

### Deferred Decisions
- Nano model quota: request via aka.ms/oai/stuquotarequest only if gpt-5-mini is insufficient; no turnaround time published.
- GitHub write-back mechanism (App vs fine-grained token): decide in research.
- Code-first comparison: deferred to a later round.

## Implementation Notes

### Priority Order
1. Research: current Foundry Agent Service, workflows, tracing, free-tier and Terraform coverage; verify model pricing and quota.
2. Terraform baseline: resource group, Foundry resource and project, model deployments with low TPM, budget, identity/RBAC.
3. GitHub OIDC plus sandbox repo with branch protection.
4. Stages in order of risk: issue triage + spec, PR review + test gen, CI triage + docs/release notes, code gen to draft PR.
5. Tracing, cost per run, capability and gap matrix, README.

### Technical Debt Accepted
- Public endpoints and no private networking: PoC only, documented.

## Open Questions

- [ ] Account signup date, to compute credit expiry.
- [x] Region/quota: uksouth, gpt-5-mini 500K TPM (measured with az 2026-10-09).
- [ ] Confirm by real deployment that gpt-5-mini needs no extra registration.
- [ ] Where does the sandbox repo live (personal org, name)?
- [ ] Which sample codebase and language for the demo repo?
- [ ] Which GitHub write-back auth is cleanest?

---

*This specification was generated through systematic interview of the plan author.*
