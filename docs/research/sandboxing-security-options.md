# Sandboxing and security options

Security and sandboxing review of the whole system, and a researched options paper for hardening the coder. Research and recommendation only: nothing in Azure, the workflows or the secrets was changed to write it.

Date 2026-10-12, repository commit `514b937`. Every claim carries a tag:

- **V** verified. Either seen in this repository at the cited `file:line` (commit `514b937`), or read in the linked primary source on 2026-10-12.
- **I** inferred. Reasoning from verified facts, a secondary source, or an absence. Each one says what would confirm it.

## Executive summary

**Recommendation: keep the coder on Foundry hosted agents and close the two holes that matter, both at roughly zero cost. Replace the account-wide PAT with a GitHub App that mints one-hour tokens scoped to this repository, and put a deny-by-default host allow-list on the coder's outbound traffic (the hosted-agent egress policy, preview), with agy moved from a personal login to a revocable API key. Treat Azure Container Apps Sandboxes as the phase 3 move, taken only after a spike proves it bills on the trial and that git works through its credential-injecting proxy. Do not build a VM, AKS cluster, firewall or third-party sandbox on this budget.**

Why this and not a bigger sandbox:

- The coder's isolation is already decent. Each hosted-agent session is a VM-isolated sandbox (V, [hosted agents](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents)), agy runs as an unprivileged user with an environment built from nothing, and the GitHub token never reaches that user (V, `agents/sdlc_agents/coder/engines.py:59-66`, `git_adapter.py:241-253`). Container escape is not the top risk.
- The real exposure is what a compromised step can reach: one PAT that writes to every repository of the account, a personal agy login readable by the engine user, and unrestricted egress to carry either away (V, `docs/runbook.md:26`, `runner.py:357-364`, no network resource in `infra/terraform/modules/`).
- Phases 1 and 2 cost nothing extra. A VM for OpenShell or Docker Sandboxes is about 0.111 USD per hour, Azure Firewall Basic about 0.395 USD per hour (V, Azure Retail Prices API, UK South), and Azure has already billed 13.02 USD of the 25 USD (V, `docs/decisions.md` D14). Only about 12 USD is left.

## What exists today

```
                 ┌──────────── Key Vault (public, RBAC) ────────────┐
                 │ github-pat (all repos, write)  agy-cli-token     │
                 └──────┬──────────────┬───────────────┬────────────┘
                        │ MI           │ MI            │ MI
┌──────────┐     ┌──────▼──────┐ ┌─────▼──────┐ ┌──────▼─────┐
│ Routine  │────▶│ orchestrator│▶│ sdlc-coder │ │ sdlc-ledger│
│ */5      │     │ hosted      │ │ hosted     │ │ hosted     │
└──────────┘     └──────┬──────┘ │ root: git  │ └──────┬─────┘
                        │        │ agyuser:   │        │ writes
                        │        │ agy, npm   │        ▼ branch state
             prompt agents + github-mcp (PAT) └─────┬──────┘
                                                    │ egress: anything
                                                    ▼ (no allow-list)
```

| Control | Evidence |
|---------|----------|
| agy, `npm ci` and tests run as `agyuser`, environment built from nothing (LANG, TERM, TMPDIR, PATH, HOME) | V, `coder/engines.py:59-66`, `coder/sandbox.py:42-58,188-193` |
| No root fallback: no engine user means `sandbox-unavailable` | V, `coder/sandbox.py:42-58`, `docs/architecture.md:156` |
| PAT reaches git only through `GIT_ASKPASS` in a 0700 temp dir, deleted after each network git call, never in argv or `.git/config` | V, `coder/git_adapter.py:241-253` |
| Managed identity endpoint returns 401 to `agyuser` (no `IDENTITY_HEADER`), `/proc/1/environ` denied | V, `docs/findings.md` (measured in the sandbox on 2026-10-10) |
| Every `agyuser` process killed before each root step | V, `coder/sandbox.py:72-88` |
| Before push: `.git/config` and hooks digest, symlink and nested-repo scan, scope check, pushes the exact verified sha | V, `coder/runner.py:637-659,735-742`, `git_adapter.py:123-130` |
| Agent branches may change `app/` only (coder, CI `agent-scope`, merge gate) | V, `coder/scope.py:113-124`, `gates.py`, `docs/architecture.md:189` |
| Owner-only triggers, nonce-wrapped untrusted text, schema-checked output | V, `machine.py:128-129`, `tick.py:336-340`, `foundry.py:272-279` |
| Caps: 3 USD per issue, halt at 22, budget alert at 25; coder deadline 7200 s | V, `docs/architecture.md:122`, `infra/terraform/variables.tf:89-92` |
| Key Vault: RBAC, soft delete 7 days, purge protection off, public | V, `infra/terraform/modules/keyvault/main.tf:24-26` |
| Foundry: public network access, local auth off | V, `infra/terraform/modules/foundry/main.tf:29-30` |
| Actions pinned to commit SHAs in `ci.yml`, `cd.yml`, `pages.yml`, `infra-ci.yml`, `gitguardian.yml`; no `azure/login` anywhere | V, grep of `.github/workflows/` |
| gitleaks in CI, GitGuardian full-history scan from main | V, `ci.yml`, `gitguardian.yml` |
| Control center: no `innerHTML`, links allow-listed to this repository, no token | V, `apps/control-center` `dom.js:10-22`, `safe.js:30-47` |

Two facts differ from the brief this review started from:

- **There is no GitHub OIDC to Azure any more.** The `github-oidc` Terraform module (and its `pull_request` federated credential) was removed in commit `42bc333`, and no workflow calls `azure/login` (V, `git show 42bc333`, grep). `infra/terraform/README.md:35,70-72` still describes it. A managed identity or federated credential created by an earlier apply may still exist in Azure (I; confirm with `az identity list -g rg-fsdlcd-demo` and `az identity federated-credential list`).
- **The PAT is fine-grained, not classic,** but granted on all repositories of the account with Contents, Issues, Pull requests and Actions write (V, `docs/runbook.md:26,337`).

## Threat model

Severity is the residual risk after current controls, for this public demo repository on a personal account.

| # | Asset | Threat | Current control | Residual risk | Severity |
|---|-------|--------|-----------------|---------------|----------|
| T1 | agy OAuth token (owner's Google login) | Prompt-injected or supply-chain code running as `agyuser` reads the token file and sends it out | Token stored 0600, owned by `agyuser` because agy must read it (V, `runner.py:357-364`). Tests run code agy wrote, so `agyuser` can run anything (V, `docs/runbook.md:328`). No egress control (V, absence) | Token and any refresh token leave; owner's Google account access persists until revoked (I) | **High** |
| T2 | Every repository of the owner | PAT abuse: writes or reads beyond this repo | Every client hard-codes this repo (V, `ports.py:13-14`, `github.py:83-84`, `job.py:127-128`). PAT never in `agyuser` reach (V) | Any root-side compromise, or the `github-mcp` connection, reaches all repos with write (V, `docs/runbook.md:337`) | **High** |
| T3 | Private repositories of the account | Injected text in a diff steers the reviewer (or feasibility, test-designer) to `get_file_contents` on a private repo, then quotes it into a public PR comment | One read-only tool, `X-MCP-Readonly`, prompt rule, markdown sanitised (V, `deploy_agents.py:366-369`, `definitions.py:43`, `sanitise.py:107-124`) | Model compliance is the only barrier; accepted in `docs/runbook.md:335` (V) | **High** |
| T4 | Network | Unrestricted egress from the coder carries T1 or repo data anywhere | None (V, Terraform has no network resources; D8) | Every exfiltration path is open | **High** (enabler for T1) |
| T5 | Owner's Google account and agy quota | Plan-token terms: automated use of a consumer login | Bounded demo, token in Key Vault (V, `docs/findings.md`, "Plan-token terms") | Antigravity FAQ: wrapping agy in third-party agents "is not supported under consumer plans"; terms clause 6 names suspension (V, [FAQ](https://antigravity.google/docs/faq/), [terms](https://antigravity.google/terms)) | **High** (account risk, not data) |
| T6 | `main` and the prod site | Reviewer approval is the only semantic gate before auto-merge; `app/` scope includes `package.json` scripts, lockfile, `.npmrc`, vite and eslint config that CI and CD execute | Six required checks, head-bound review marker, owner-only, ruleset with no bypass (V, `gates.py:147-153`, `docs/decisions.md` D4) | An approved but malicious build script ships to Pages (I) | **Medium** |
| T7 | Branches `state`, `metrics`, `deploy`, `agent-lease/*` | Any PAT holder rewrites the control center data or the prod site | Ruleset covers only `~DEFAULT_BRANCH` (V, `scripts/setup_repo.py:119`); `deploy` ruleset fails with 422 (V, `setup_repo.py:259-277`); coder forbids `main`, `master`, `HEAD`, `sdlc-lock`, `metrics` only (V, `coder/job.py:40`) | Root code in three agents and the MCP connection can write them; `agyuser` cannot (V) | **Medium** |
| T8 | CI secrets | `security.yml` (added in `eebdab9`) runs on `pull_request` with `GITGUARDIAN_API_KEY` in the job env, actions pinned by tag, gitleaks tarball unchecked, `ggshield` unpinned | Fork PRs get no secrets (V, [GITHUB_TOKEN reference](https://docs.github.com/en/actions/reference/github_token-reference)); agent branches cannot change `.github/` or root files (V, scope gate) | Same-repo PR jobs see the key; a moved tag runs third-party code with it (I). Contradicts D6 "Workflows never receive secrets" | **Medium** |
| T9 | Coder runtime | Supply chain at run time | Node sha256 checked against SHASUMS from the same origin, version floats on `latest-v22.x` (V, `toolchain.py:26,126-135`); agy installer run as root with no checksum (V, `toolchain.py:27`, accepted in runbook); `npm ci` from lockfile that agy can edit (V); hosted `requirements.txt` pinned without hashes (V) | A compromised installer runs as root once per session (I) | **Medium** |
| T10 | Coder job control | `agyuser` reaches the coder's own Invocations listener on localhost and posts `start` or `cancel` | None found in code (I, not confirmed) | Unconfirmed; check with `ss -ltnp` as `agyuser` in a session | **Medium if confirmed** |
| T11 | Foundry project | Public endpoint, RBAC misuse | Entra only, local auth off (V); agents have Foundry User at project scope, project MI and deployer at account scope (V, `foundry/main.tf:157-179`) | Hosted agent endpoint stays public even with VNet injection in preview (V, [virtual networks](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/virtual-networks)) | **Low** |
| T12 | Key Vault | Secret read beyond need | Agents hold `Key Vault Secrets User` per secret (V, `deploy_agents.py:441-453`); project MI holds it at vault scope (V, `infra/terraform/main.tf:76-78`, `keyvault/main.tf:32,40`); purge protection off (V) | Project MI reads every secret; a destroy is not recoverable after 7 days | **Low** |
| T13 | Azure subscription | Workflow credential trust (OIDC) | Module removed, no `azure/login` (V) | A leftover federated credential with a `pull_request` subject would let any same-repo PR mint an Azure token (I, check Azure) | **Low** (pending check) |
| T14 | Public issue comments, logs | Secrets in coder-log comments or stdout | Known-value, basic-auth, JSON and token-shape redaction, then a second pass before posting (V, `job.py:305-360`, `sanitise.py:127-141`) | Pure-hex strings are treated as not random (V, `job.py:329-331`), so a hex-encoded token passes into a public comment | **Low** |
| T15 | Container escape | Kernel or runtime exploit from `agyuser` | Per-session VM-isolated sandbox (V, [hosted agents](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents)); unprivileged user | Escape lands in a single-tenant session VM holding the PAT in root memory (I) | **Low** |
| T16 | Pages and control center | Content injection from issue, model or state text | Text nodes only, link allow-list, no token (V) | None found | **Low** |

What owner-only triggers change: issue text is written by the owner, so the realistic injection sources are dependencies (`npm ci`), repository content, model output and anything agy fetches from the web (I). That lowers the likelihood of T1 and T3, not their impact.

## Options matrix

Cost is against the roughly 12 USD left under the 25 USD cap. "Fits agy" means a CLI that needs git, node and HTTPS to a model API.

| Option | Isolation | Closes | Effort | Cost | Maturity | Lock-in | Fits agy | On Azure |
|--------|-----------|--------|--------|------|----------|---------|----------|----------|
| (g) GitHub App, one-hour single-repo tokens | n/a (credential) | T2, T3, T7 (with rulesets) | M | 0 | GA | Low | Yes | Yes |
| (g') Fine-grained PAT, this repo only | n/a | T2, part of T3 | S | 0 | GA | Low | Yes, but no Checks API | Yes |
| (c+f) Hosted-agent egress policy (FQDN, deny default) | Platform proxy | T4, most of T1 | S | 0 (I) | Preview, no SLA | High | Yes (I) | Yes |
| (b) Azure Container Apps Sandboxes | microVM, own kernel | T1, T2 in sandbox, T4, T15 | M | about 0.15 USD/h at 1 vCPU, 2 GiB (I) | Preview (GA claimed by InfoQ only) | High | Likely (I) | Yes, UK South |
| (c) Foundry managed VNet, approved outbound | VM sandbox plus firewall | T4 | M | FQDN rules add Azure Firewall charges | Preview CLI, cannot be disabled | High | Yes | Yes |
| (c) Foundry BYO VNet injection | VM sandbox in your subnet | T4, T11 partly | L, new account | AI Search Basic about 2.42 USD/day plus Cosmos, Storage, firewall | Preview | High | Yes | Yes |
| (d) ACA dynamic sessions, custom container | Hyper-V | T15 | M | Dedicated E16 nodes, about 2.24 USD/h (I) | Mixed | Medium | Egress only on or off | Yes |
| (f) In-container proxy plus iptables owner match | Same container | T4 | M | 0 | Untested here | Low | Yes, if `NET_ADMIN` exists (I) | Yes |
| (f) Azure Firewall Basic | Network | T4 | L | 0.395 USD/h, budget gone in about 30 hours | GA | Medium | Yes | Yes |
| (a) NVIDIA OpenShell on a D2s_v5 VM | Landlock, seccomp, per-binary egress, credential placeholders | T1, T4, partly T2 | M | 0.111 USD/h | v0.1.3, about 7 months old | Low | Yes, agy untested | Own VM only |
| (e) Docker Sandboxes (`sbx`) on a nested-virt VM | microVM, host proxy, sentinel credentials | T1, T4, T15 | S to M | 0.111 USD/h | Under 8 months | Medium | Via Shell agent | Own VM only |
| (e) AKS Pod Sandboxing (Kata) | Kata VM per pod | T15 | M to L | at least one Dsv5 node | GA (I) | Medium | Yes | AKS |
| (e) gVisor, Firecracker, microsandbox | Userspace kernel or microVM | T15, plus egress only with extra work | M to L | VM | Mature (gVisor, Firecracker), beta (microsandbox) | Low | Yes | Own VM only |
| (h) Vercel Sandbox | Firecracker | T1, T2, T4, T15 | M | about 7 USD for 40 jobs of 30 min (I); 2 h jobs need Pro | GA | High | Yes | No, external |
| (h) E2B | Firecracker | T1, T2, T4, T15 | M | about 3.3 USD for 40 jobs; Hobby sessions capped at 1 h | GA, brokering in beta | Medium (Apache-2.0 infra) | Yes | No, external |
| (h) Cloudflare Sandbox | microVM | T1, T2, T4, T15 | L (TypeScript Worker) | 5 USD plan plus usage | New | High | Yes | No |
| (h) Modal, Daytona | gVisor or VM; containers | T4, T15 | M | 3 to 5 USD | Daytona repo archived | High | Yes, but Modal has no credential brokering | No |

## Per-option notes

### (g) Replace the PAT with a GitHub App

- Installation tokens last one hour and can be narrowed at mint time to listed repositories and fewer permissions (V, [create an installation token](https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app)).
- The App JWT is RS256 with at most 10 minutes of life (V, [JWT](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app)). Key Vault signs RS256 (V, [Key Vault sign](https://learn.microsoft.com/en-us/rest/api/keyvault/keys/sign/sign?tabs=HTTP)), so the private key can be a non-exportable vault key and each agent only gets sign permission (I: the role name and digest handling still need a spike).
- Per caller tokens: coder gets contents and pull requests write on this repo; ledger gets contents write (for `state`) and read elsewhere; MCP gets contents read only. That removes T2 and narrows T3 to this public repo (I).
- With rulesets that restrict updates on `state`, `metrics`, `deploy` and `agent-lease/*` and put only the right App in the bypass list, a stolen coder token cannot rewrite them (V for the rule, [available rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets); I for the design).
- Rate limit improves: 5,000 per hour per installation, scaling up, instead of sharing the owner's 5,000 (V, [rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)).
- Unknown: whether the hosted MCP server at `api.githubcopilot.com/mcp/` accepts installation tokens. Its App-auth doc covers the local server only (V, [github-app-auth.md](https://raw.githubusercontent.com/github/github-mcp-server/main/docs/github-app-auth.md)). A one-hour token in a Foundry connection header also needs a refresher (I).
- Stopgap if the App slips: a fine-grained PAT with "Only select repositories" set to this repo (V, [managing PATs](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)). Fine-grained PATs cannot call the Checks API (V, same page), which the orchestrator reads, so a split is needed: a read-only single-repo PAT for MCP first, the App for the rest.
- New installation tokens are moving to a longer `ghs_` format; the redactor's token shapes must accept it (V, create token page).

### (c) and (f) Foundry hosted-agent egress controls

- An account-level policy with `defaultAction: Deny`, exact-host `Fqdn` rules and an Audit or Enforced mode; blocked calls get a proxy 403. API `2026-05-15-preview`, `azure-ai-projects>=2.2.0` (V, [Foundry blog, 2026-09-24](https://devblogs.microsoft.com/foundry/egress-controls-hosted-agent), single source).
- Explicitly "not intended for production use", no SLA, HTTP and HTTPS only (V, same post). No VNet or price mentioned (V); assumed free (I).
- The coder list would be roughly: `github.com`, `codeload.github.com`, `objects.githubusercontent.com`, `api.github.com`, `registry.npmjs.org`, `nodejs.org`, `antigravity.google`, the agy model host, the Key Vault host, `login.microsoftonline.com` and the Foundry endpoint (I; Audit mode will show the real list).
- It does not stop misuse of an allowed host. With github.com open, injected code can push to an attacker's repository using credentials planted in its input (I). The token being out of reach (T2 control) is what makes that harmless for the PAT; the agy token remains the exposure until it is an API key.
- Account level means orchestrator and ledger are covered too and need their own hosts (I; confirm whether per-agent scoping exists).
- Managed VNet ("allow only approved outbound") supports hosted agents in UK South, but FQDN rules add Azure Firewall charges and it cannot be disabled once on (V, [managed VNet](https://learn.microsoft.com/en-us/azure/foundry/how-to/managed-virtual-network)). Not on this budget.
- BYO VNet must be chosen when the account is created, needs a subnet delegated to `Microsoft.App/environments`, and the standard setup brings AI Search, Cosmos DB and Storage (V, [virtual networks](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/virtual-networks)). Not on this budget.

### (f) In-container proxy

- Stripe Smokescreen is a CONNECT proxy with a hostname ACL and a non-root image (V, [smokescreen](https://github.com/stripe/smokescreen)). Run it as a third user, force `agyuser` traffic to it with `iptables -m owner --uid-owner`, set `HTTPS_PROXY`.
- Needs `CAP_NET_ADMIN`, netfilter and the binary inside the hosted sandbox. Learn documents none of that (V, absence). A one-minute probe (`iptables -L`) settles it (I).
- Fallback only: the platform policy is simpler if it works.

### (b) Azure Container Apps Sandboxes

- What it is: microVM sandboxes in sandbox groups (`Microsoft.App/sandboxGroups`), "each sandbox runs in its own secure boundary with its own kernel" (V, [docs](https://sandboxes.azure.com/docs/sandboxes/)). Python SDK `azure-containerapps-sandbox` with `DefaultAzureCredential`, an `aca` CLI, Entra role "Container Apps SandboxGroup Data Owner" (V, [Python quickstart](https://sandboxes.azure.com/docs/sandboxes/quickstart/setup-python-sdk)).
- Egress: wildcard host, path, method and scheme rules, audit log of decisions, and a `Transform` rule with `secretRef` or `managedIdentityRef` that injects the credential at the proxy, so code in the sandbox never sees it (V, [egress](https://sandboxes.azure.com/docs/sandboxes/sandbox/egress)). This is the only Azure option that keeps the GitHub token and the agy key out of the sandbox entirely.
- The egress page says sandboxes have unrestricted outbound access when no policy is set; the VNet page and InfoQ say deny by default (V, conflict). Always set Deny explicitly.
- Regions include UK South (V, [regions](https://sandboxes.azure.com/docs/sandboxes/regions)). Snapshots, custom OCI disk images, public `node-24` images (V).
- Status: InfoQ reported GA on 2026-10-01 (V, [InfoQ](https://infoq.com/news/2026/10/container-apps-express-sandboxes)); Learn pages still say preview and the SDK is `0.1.0b4` (V). Treat as preview.
- Price: "same pay-per-second pricing as Consumption Plan" (V, [pricing](https://azure.microsoft.com/en-gb/pricing/details/container-apps/)); UK South active vCPU 0.000034 USD per second and memory 0.000004 USD per GiB-second (V, Retail API), about 0.15 USD per hour at 1 vCPU and 2 GiB (I). Free-trial eligibility and quota unknown (V, quotas page returned 404).
- InfoQ reports that hosted agents run on this same infrastructure, which would explain the double metering seen in D14 (V that InfoQ says it, I that it is true).
- Fit: hosted coder becomes a thin caller; agy, git and node run in the sandbox. Unverified: whether GitHub accepts the injected header for git over HTTPS (`format` such as `Bearer {value}`; git wants Basic with `x-access-token`), and whether agy runs with its key injected rather than on disk.

### (d) Azure Container Apps dynamic sessions

- Hyper-V isolation; egress is only `EgressDisabled` or `EgressEnabled`, no allow-list (V, [sessions](https://learn.microsoft.com/azure/container-apps/sessions), [ARM 2025-02-02-preview](https://learn.microsoft.com/en-us/azure/templates/microsoft.app/2025-02-02-preview/sessionpools)).
- If identity is enabled "any code or programs running in the session can create Microsoft Entra tokens" (V, [sessions usage](https://learn.microsoft.com/en-us/azure/container-apps/sessions-usage)).
- Custom container pools run on dedicated E16 instances billed on the Dedicated plan (V, [billing](https://learn.microsoft.com/en-us/azure/container-apps/billing)), about 2.24 USD per hour per node (I). Rejected: expensive, and agy needs egress on, which closes nothing.

### (a) NVIDIA OpenShell

- Repository [NVIDIA/OpenShell](https://github.com/NVIDIA/OpenShell), Apache-2.0, created 2026-02-24, latest stable v0.1.3 on 2026-10-09 (V, GitHub API). A sandbox runtime for coding agents: gateway, supervisor and YAML policy (V, [overview](https://docs.nvidia.com/openshell/latest/about/overview)).
- Isolation: Landlock on the filesystem, seccomp user-notification on TCP and DNS, non-root workload with no capabilities, every connection through the supervisor (V, [architecture](https://docs.nvidia.com/openshell/latest/about/architecture)).
- Policy: per-binary, per-host egress rules, hot-reloadable; credentials as placeholders (`openshell:resolve:env:KEY`) so the agent "never sees real credentials" (V, [policy schema](https://docs.nvidia.com/openshell/how-it-works/policies/schema.md)).
- Host: Docker Engine 28+ or Podman 5, Landlock ABI 3 (kernel 6.2+), or Kubernetes 1.29+; the VM driver needs KVM and is experimental (V, [support matrix](https://docs.nvidia.com/openshell/about/support-matrix.md)). Named agents: Claude Code, OpenCode, Codex, Copilot CLI; agy is not named (V).
- Cannot run inside a hosted-agent session: no Docker or Kubernetes API there (I). Needs a D2s_v5 VM (0.111 USD per hour on demand, 0.0198 spot, V, Retail API) plus someone to patch it. The Docker and Kubernetes drivers share the host kernel, so container escape is not closed (V).
- Verdict: the best policy model of the set and low lock-in, but it moves the coder off Foundry. Revisit if the project leaves the trial.

### (e) Docker Sandboxes, gVisor, Firecracker, Kata

- Docker Sandboxes (`sbx`): a microVM per sandbox with its own kernel and Docker daemon, deny-by-default host proxy, the real credential injected host-side and "never enters the VM" (V, [security](https://docs.docker.com/ai/sandboxes/security/)). Needs KVM, so a nested-virtualization VM; login is a browser OAuth flow and headless use is not documented (V). agy is not a listed agent; the Shell sandbox would carry it (V). v0.47.0 on 2026-10-05 (V, [sbx-releases](https://github.com/docker/sbx-releases)).
- gVisor: user-space kernel, systrap platform needs no virtualization, no egress filtering of its own (V, [google/gvisor](https://github.com/google/gvisor)). Whether the hosted sandbox allows the user namespaces rootless `runsc` needs is unknown (I).
- Firecracker v1.17.0 (2026-09-10) needs `/dev/kvm` and "does not perform any network traffic filtering" (V, [getting started](https://raw.githubusercontent.com/firecracker-microvm/firecracker/main/docs/getting-started.md)). Raw use is L effort.
- Kata 4.2.0 (2026-09-15) (V). AKS Pod Sandboxing runs Kata with Cloud Hypervisor on Azure Linux node pools with nested virtualization; Microsoft says it is compute isolation, not complete multitenancy, and needs network policy on top (V, [AKS pod sandboxing](https://learn.microsoft.com/en-us/azure/aks/use-pod-sandboxing)).
- Dsv5 lists nested virtualization as supported (V, [Dv5 series](https://learn.microsoft.com/en-us/azure/virtual-machines/dv5-dsv5-series)).
- Verdict: these close container escape, which is the lowest-ranked threat here, at the cost of a VM or cluster. Not now.

### (h) Third-party sandboxes

- Vercel Sandbox: Firecracker, domain allow-list by SNI, per-domain header transform so the token stays outside, London and Frankfurt regions; Hobby caps sessions at 45 minutes (V, [firewall](https://vercel.com/docs/vercel-sandbox/concepts/firewall), [pricing](https://vercel.com/docs/vercel-sandbox/pricing)).
- E2B: Firecracker, `allowOut` and `denyOut` with domains, credential fill in public beta (10 domains), Hobby has a one-time 100 USD credit and 1 hour sessions, Pro is 150 USD a month (V, [internet access](https://e2b.dev/docs/sandbox/internet-access), [pricing](https://e2b.dev/pricing)). Self-hostable under Apache-2.0 with KVM (V).
- Cloudflare Sandbox: the strongest brokering design (token held in the Worker, internet off in the container), but TypeScript only and a Worker to run (V, [clone a private repository](https://developers.cloudflare.com/sandbox/network/clone-a-private-repository/index.md)).
- Modal: Python native, beta domain allow-list, no credential brokering documented (V, [networking](https://modal.com/docs/guide/sandbox-networking)). Daytona: GitHub repository archived, last push 2026-07-24 (V, GitHub API). Runloop, Northflank: vendor or blog claims only (I).
- All cost a few dollars for this workload, but they move code and tokens to another vendor, add an account and a contract, and leave the Azure demo. Keep E2B or Vercel as the fallback if phase 3's Azure spike fails.

### Plan token (agy)

- The Antigravity FAQ: headless `agy -p` "is intended for direct scripting and CI workflows", but "wrapping `agy` inside third-party coding agents or applications ... is not supported under consumer plans" and recommends a Gemini Enterprise or Google AI Studio API key (V, [FAQ](https://antigravity.google/docs/faq/), undated).
- API-key mode: `"modelProvider": "gemini"` in `~/.gemini/antigravity-cli/settings.json` plus `GEMINI_API_KEY`; the page calls it suited to headless and CI runs (V, [install](https://antigravity.google/docs/cli/install/)). Latest CLI 1.3.3, 2026-10-10 (V, GitHub releases API).
- An API key is still readable by `agyuser`, but it is revocable, quota-cappable and not the owner's Google identity (I). Its model spend would count against `max_model_usd`; Gemini API prices were not researched here (open question).

## Phased adoption plan

```
Phase 0 hygiene ──▶ Phase 1 credentials ──▶ Phase 2 egress ──▶ Phase 3 Sandboxes spike
 S, 0 USD            M, 0 USD                S, 0 USD (I)        M, 1 to 3 USD (I)
 T7 T8 T9 T10 T13    T1(account) T2 T3 T5    T4, T1 exfil        T1 T2 fully, T15
```

| Phase | Work | Closes | Effort | Cost | Exit check |
|-------|------|--------|--------|------|------------|
| 0. Hygiene | Restrict `security.yml` to `push` (or move the GitGuardian key behind an environment), SHA-pin its actions, checksum gitleaks, pin `ggshield`. Add rulesets that restrict updates and deletions on `state`, `metrics`, `deploy`, `agent-lease/*`. Add `state`, `deploy`, `deploy/*` and `agent-lease/*` to the coder's forbidden branches. Pin node to an exact version and verify `SHASUMS256.txt.asc` with the release keys; pin agy by release asset sha256. Treat `package.json` scripts, the lockfile, `.npmrc` and build configs under `app/` like protected test files for agent branches. Redact long hex and base64 runs. Probe the localhost listener and `iptables` in one session. Check Azure for a leftover OIDC identity. Fix `infra/terraform/README.md`. | T7, T8, T9, T10, T13, T14, part of T6 | S (one or two days) | 0 | Each item has a regression test or a recorded probe output |
| 1. Credentials | GitHub App on this repo only, private key as a Key Vault RSA key used through sign; mint per-caller tokens with narrowed permissions; App in the ruleset bypass for `state` and `deploy` only. MCP connection gets a contents-read single-repo token (fine-grained PAT first, App token with a refresher once accepted). Move agy to API-key mode with a dedicated, quota-capped key. Revoke the all-repos PAT and the personal agy login. | T2, T3, T5, T1 impact | M (three to five days) | 0 for GitHub and Key Vault (I); Gemini API usage unknown | No secret in Key Vault can write outside this repo; `ghs_` accepted by MCP or the PAT fallback documented |
| 2. Egress | Hosted-agent egress policy in Audit mode for a week of ticks, read the decisions, then Enforced with exact hosts. If the policy is account-wide, include orchestrator and ledger hosts. Fallback if the preview is unavailable on the trial: in-container proxy, only if the phase 0 probe found `NET_ADMIN`. | T4, exfiltration half of T1 | S (one day plus the audit week) | 0 (I) | A probe request to an unlisted host from `agyuser` gets 403 |
| 3. Sandboxes spike | One coder job in Azure Container Apps Sandboxes: UK South, explicit Deny default, allow GitHub, npm, the model host; GitHub token and agy key injected by `Transform`. Prove clone, `npm ci`, vitest and push. Read the bill after 48 hours. Adopt only if it bills on the trial and git works through the proxy. | T1, T2 inside the sandbox, T15 | M (three to five days) | about 0.15 USD per active hour (I), 1 to 3 USD for the spike | Token absent from the sandbox filesystem and environment; the bill matches the estimate |

## Open questions

Logged rather than asked, per the brief.

1. Does the hosted MCP server accept GitHub App installation tokens, and can a Foundry connection header be refreshed hourly without redeploying agents?
2. Is the hosted-agent egress policy available on a free-trial subscription, is it per account or per agent, and does it cost anything?
3. Do Azure Container Apps Sandboxes bill and run on the trial, under what quota, and does the free monthly Container Apps grant apply?
4. Does git over HTTPS work with a proxy-injected `Authorization` header in Sandboxes (format is documented as `Bearer {value}`; GitHub git transport usually takes Basic)?
5. Does the hosted sandbox grant `CAP_NET_ADMIN`, user namespaces, Landlock or `/dev/kvm`? No Microsoft page says.
6. Can `agyuser` reach the coder's own Invocations listener on localhost without authentication (T10)?
7. Does a leftover managed identity or federated credential from the removed `github-oidc` module still exist in `rg-fsdlcd-demo`?
8. What does agy cost per job on a Gemini API key, and does it fit inside the 0.50 USD per-job model cap?
9. Does the owner, as repository admin, bypass a ruleset they are not listed on? GitHub docs did not say; test before relying on it.
10. GitHub's OIDC docs write the subject `pull_request`, Microsoft's write `pull-request` (both V). Only matters if OIDC returns; decode a real token first.

## What not to do

- Do not run agy, `npm ci` or tests as root, and do not give the coder's engine user any path to `IDENTITY_HEADER`. The unprivileged user is the boundary today.
- Do not treat agy's allow-list or permission mode as a security boundary; tests already run engine-written code (V, `docs/runbook.md:328`).
- Do not put the GitHub token or any Azure credential into a sandbox environment variable when moving to Sandboxes or a vendor; use the proxy injection or keep git on the root side.
- Do not open egress to wildcards such as `*.googleapis.com` or `*.github.com` when exact hosts work; every allowed host is an exfiltration path (V, Vercel, E2B and Cloudflare docs all say so).
- Do not deploy Azure Firewall, a managed VNet or BYO VNet on this trial. Firewall Basic uses the remaining budget in about 30 hours; managed VNet cannot be turned off; BYO VNet needs a new account and paid dependencies (V, pricing and Learn).
- Do not use ACA dynamic sessions custom containers here (dedicated E16 billing, egress only on or off), and do not enable session identity (any code in the session can mint Entra tokens).
- Do not go back to a classic PAT or widen the fine-grained PAT; and do not let any token in the coder reach `state` or `deploy` once rulesets exist.
- Do not rely on a sandbox product's documented default; set Deny explicitly and check the audit log (the Sandboxes docs disagree with themselves).
- Do not build on Daytona while its repository is archived.

## Sources

All fetched 2026-10-12.

| Area | Source |
|------|--------|
| Foundry hosted agents | [concepts](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents), [egress controls blog](https://devblogs.microsoft.com/foundry/egress-controls-hosted-agent), [managed VNet](https://learn.microsoft.com/en-us/azure/foundry/how-to/managed-virtual-network), [virtual networks](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/virtual-networks), [Build 2026 blog](https://devblogs.microsoft.com/foundry/hosted-agents-build26/) |
| Container Apps Sandboxes | [docs](https://sandboxes.azure.com/docs/sandboxes/), [egress](https://sandboxes.azure.com/docs/sandboxes/sandbox/egress), [regions](https://sandboxes.azure.com/docs/sandboxes/regions), [Python quickstart](https://sandboxes.azure.com/docs/sandboxes/quickstart/setup-python-sdk), [InfoQ 2026-10](https://infoq.com/news/2026/10/container-apps-express-sandboxes), [InfoQ 2026-06](https://infoq.com/news/2026/06/untrusted-ai-agents-sandboxes) |
| Dynamic sessions | [sessions](https://learn.microsoft.com/azure/container-apps/sessions), [usage](https://learn.microsoft.com/en-us/azure/container-apps/sessions-usage), [billing](https://learn.microsoft.com/en-us/azure/container-apps/billing) |
| Prices | [Azure Retail Prices API](https://prices.azure.com/api/retail/prices) (UK South: hosted agent, Container Apps, Firewall, D2s_v5) |
| OpenShell | [repo](https://github.com/NVIDIA/OpenShell), [overview](https://docs.nvidia.com/openshell/latest/about/overview), [policy schema](https://docs.nvidia.com/openshell/how-it-works/policies/schema.md), [support matrix](https://docs.nvidia.com/openshell/about/support-matrix.md) |
| microVM and kernels | [Docker Sandboxes security](https://docs.docker.com/ai/sandboxes/security/), [gVisor](https://github.com/google/gvisor), [Firecracker](https://github.com/firecracker-microvm/firecracker), [Kata](https://github.com/kata-containers/kata-containers), [AKS pod sandboxing](https://learn.microsoft.com/en-us/azure/aks/use-pod-sandboxing), [microsandbox](https://github.com/superradcompany/microsandbox) |
| Third-party sandboxes | [Vercel](https://vercel.com/docs/vercel-sandbox), [E2B](https://e2b.dev/docs/sandbox/internet-access), [Cloudflare](https://developers.cloudflare.com/sandbox/), [Modal](https://modal.com/docs/guide/sandbox-networking), [Daytona](https://www.daytona.io/docs/en/sandboxes/) |
| GitHub | [installation tokens](https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app), [App JWT](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app), [fine-grained PATs](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens), [ruleset rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets), [OIDC reference](https://docs.github.com/en/actions/reference/security/oidc), [secure use](https://docs.github.com/en/actions/reference/security/secure-use), [MCP App auth](https://raw.githubusercontent.com/github/github-mcp-server/main/docs/github-app-auth.md) |
| Azure identity | [Key Vault sign](https://learn.microsoft.com/en-us/rest/api/keyvault/keys/sign/sign?tabs=HTTP), [federated credential trust](https://learn.microsoft.com/en-us/entra/workload-id/workload-identity-federation-create-trust?pivots=identity-wif-apps-methods-azp) |
| Supply chain | [npm ci](https://docs.npmjs.com/cli/v11/commands/npm-ci), [node release verification](https://raw.githubusercontent.com/nodejs/node/main/README.md), [pip secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/), [Smokescreen](https://github.com/stripe/smokescreen) |
| agy | [FAQ](https://antigravity.google/docs/faq/), [terms](https://antigravity.google/terms), [install and auth](https://antigravity.google/docs/cli/install/), [plans](https://antigravity.google/docs/plans) |
| Prompt injection | [OWASP LLM01:2025](https://genai.owasp.org/llmrisk/llm01-prompt-injection/), [the lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/) |
