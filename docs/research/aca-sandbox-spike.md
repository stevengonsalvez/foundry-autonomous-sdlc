# Azure Container Apps Sandboxes spike (WIP)

Status: work in progress, handed over mid-run on 2026-10-12. No go or no-go yet. Azure resources are deliberately left running for the next session (see "Resources left running").

Scope: phase 3 of `docs/research/sandboxing-security-options.md` (branch `stevengonsalvez/sandbox-security`). One coder job inside a sandbox in UK South, explicit Deny default egress, allow only GitHub, npm and the model host, GitHub token injected by a `Transform` rule.

## Evidence table

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | Trial subscription can create a sandbox group and a sandbox | PASS | `Microsoft.App` was `NotRegistered`; `az provider register -n Microsoft.App` reached `Registered` in about 2 minutes. `sandboxGroups` lists UK South, api-versions `2026-07-01`, `2026-02-01-preview`. Group `sbg-spike` created in 2.9 s (`provisioningState: Succeeded`, `managementEndpoint: https://management.uksouth.azuredevcompute.io`). Sandbox `a100e32b-ba61-45b8-8902-591adcfb48a6` from public image `node-24` created in 0.9 s. No quota or preview gate hit. |
| 2 | Python SDK with `DefaultAzureCredential` | PASS (SDK); aca CLI not tried | `azure-containerapps-sandbox 0.1.0b4`, `azure-identity 1.26.0`. Control plane via `SandboxGroupManagementClient`, data plane via `SandboxGroupClient` (scope `https://dynamicsessions.io/.default`) after assigning `Container Apps SandboxGroup Data Owner` on the group to the signed-in user. 17 public images listed, including `node-22`, `node-24`, `claude`, `copilot`, `ubuntu`. |
| 3 | git clone over HTTPS through the credential-injecting proxy | PASS (clone of a private repo) | Secret `githubtoken` holds key `basic` = base64(`x-access-token:<token>`) and key `token`. Transform rule on host `github.com`: `Set Authorization`, `secretRef {secretId: githubtoken, secretKey: basic, format: "Basic {value}"}`. `git clone https://github.com/stevengonsalvez/aca-sandbox-spike-scratch.git` (PRIVATE) exited 0 with no credential in the sandbox: git's own trace shows no `Authorization` header sent by the client, `git-upload-pack` returned `HTTP/2 200`, `.git/config` has no auth, header or token entry. Answer to the paper's open question: the `format` field is free text, so storing the pre-encoded Basic value and using `Basic {value}` works. |
| 4 | node, `npm ci`, vitest of `app/` | NOT RUN | Repo cloned to `/root/w/repo` in the sandbox; next command is `npm ci && npx vitest run` in `/root/w/repo/app`. |
| 5 | Deny default blocks an unlisted host, audit log shows it | PASS (partial: one host) | `curl https://example.com` returned 403 from the proxy; `egress-decisions` lists it under `denied` (`host: example.com, scheme: https, 2026-10-12T13:00:08Z`). Allowed entries carry `matchedRule`, e.g. `Host: azure.archive.ubuntu.com`. |
| 6 | Push of a scratch branch through the proxy | NOT RUN | |
| 7 | Cost | NOT RUN | Baseline before the spike: 10.22 GBP actual cost this billing period (Cost Management query API), about 13.0 USD. |
| 8 | agy CLI with its credential not on disk | NOT RUN | |

## Findings so far

- Default traffic inspection is `Full` (the proxy terminates TLS). The sandbox trusts it via `/etc/ssl/certs/adc-egress-proxy-ca.crt`, `NODE_EXTRA_CA_CERTS`, `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE`.
- Host rules allow HTTPS only. Plain HTTP to an allowed host is still denied (403), and an advanced `Allow` rule did not change that. The image's apt mirror is `http://azure.archive.ubuntu.com`, so apt fails under Deny. Workaround used: temporarily allow `mirrors.edge.kernel.org` and rewrite the apt sources to HTTPS, then remove the rule. Production would need a custom disk image with git preinstalled.
- The `node-24` image has no git. It runs as `root`, Ubuntu 24.04.5, kernel 6.12.8, node v24.20.0, npm 10.9.2, 1 vCPU, about 2.2 GB RAM, 20 GB disk.
- Policy changes at runtime take effect within seconds (`set_egress_policy`).
- `IDENTITY_ENDPOINT=http://100.64.100.2/msi/token` is present in the sandbox environment; it returned 401 because the group has no managed identity. Never give the group an identity that code inside could use.
- Secret id `gh` is rejected (`400 secretId: The input was not valid`); `githubtoken` works.
- Secrets can be read back by a data-plane owner (`peek_secret`), so the data-plane role must stay with the orchestrator, not the sandbox.

## Resources left running

| Resource | Name | Notes |
|----------|------|-------|
| Resource group | `rg-sandbox-spike` (uksouth) | tag `purpose=sandbox-spike` |
| Sandbox group | `sbg-spike` | tag `purpose=sandbox-spike` |
| Sandbox | `a100e32b-ba61-45b8-8902-591adcfb48a6` | label `purpose=sandbox-spike`, `node-24`, 1000m CPU, 2048Mi, auto-suspend after 300 s (Memory mode) |
| Group secret | `githubtoken` | holds a GitHub OAuth token (repo scope); delete with the group |
| Role assignment | Container Apps SandboxGroup Data Owner on `sbg-spike` | goes away with the group |
| GitHub repo | `stevengonsalvez/aca-sandbox-spike-scratch` (PRIVATE) | throwaway; deleting it needs `gh auth refresh -s delete_repo` |

## Scripts

`scripts/spike/` (parameterised by env, no secrets): `common.py`, `s1_group.py`, `s3_sandbox.py`, `x.py` (exec a command), `pol.py` (add or remove a host rule), `dec.py` (dump egress decisions). See the handover in the PR for resume commands.
