# Azure Container Apps Sandboxes spike

Status: done on 2026-10-12. All spike resources are torn down (see "Teardown").

**Verdict: conditional GO for phase 3.** Every step that could be run passed: the trial subscription creates sandboxes in seconds, the Python SDK works with a service principal, clone of a private repo works with the credential held only by the proxy, `npm ci` and the full vitest suite pass under Deny default egress, and denials are audited. One gate stays open: a `git push` with an injected write token is not proven (step 6), because no single-repo token was available. The push transport is proven (GitHub, not the proxy, answers `git-receive-pack` with 401), so the remaining risk is small, but it must be closed before the coder moves.

Scope: phase 3 of `docs/research/sandboxing-security-options.md` (branch `stevengonsalvez/sandbox-security`). One coder job inside a sandbox in UK South, explicit Deny default egress, allow only GitHub, npm and the model host, GitHub token injected by a `Transform` rule.

## Evidence table

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | Trial subscription can create a sandbox group and a sandbox | PASS | `Microsoft.App` was `NotRegistered`; `az provider register -n Microsoft.App` reached `Registered` in about 2 minutes. `sandboxGroups` lists UK South, api-versions `2026-07-01`, `2026-02-01-preview`. Group `sbg-spike` created in 2.9 s (`provisioningState: Succeeded`, `managementEndpoint: https://management.uksouth.azuredevcompute.io`). Sandbox `a100e32b-ba61-45b8-8902-591adcfb48a6` from public image `node-24` created in 0.9 s. No quota or preview gate hit. |
| 2 | Python SDK with `DefaultAzureCredential` | PASS (SDK, user and service principal); aca CLI not tried | `azure-containerapps-sandbox 0.1.0b4`, `azure-identity 1.26.0`. Control plane via `SandboxGroupManagementClient`, data plane via `SandboxGroupClient` (scope `https://dynamicsessions.io/.default`) after assigning `Container Apps SandboxGroup Data Owner`. Second session ran from a Linux host as service principal `sp-fsdlc-hetzner-agents` (env credential), same scripts, no change. 17 public images listed, including `node-22`, `node-24`, `claude`, `copilot`, `ubuntu`. |
| 3 | git clone over HTTPS through the credential-injecting proxy | PASS (clone of a private repo) | Secret `githubtoken` holds key `basic` = base64(`x-access-token:<token>`) and key `token`. Transform rule on host `github.com`: `Set Authorization`, `secretRef {secretId: githubtoken, secretKey: basic, format: "Basic {value}"}`. `git clone https://github.com/stevengonsalvez/aca-sandbox-spike-scratch.git` (PRIVATE) exited 0 with no credential in the sandbox: git's own trace shows no `Authorization` header sent by the client, `git-upload-pack` returned `HTTP/2 200`, `.git/config` has no auth, header or token entry. Negative control after the Transform rules were removed: `git ls-remote` of the same repo gets `HTTP/2 401`, `www-authenticate: Basic realm="GitHub"`, so the earlier clone succeeded because of the injection. The `format` field is free text, so storing the pre-encoded Basic value and using `Basic {value}` works. |
| 4 | node, `npm ci`, vitest of `app/` | PASS | In `/root/w/repo/app` under Deny default egress: `npm ci --no-audit --no-fund` exit 0, `added 382 packages in 7s`; `npx vitest run` exit 0, `Test Files 20 passed (20)`, `Tests 167 passed (167)`, `Duration 18.18s`. No denied egress during the run; the audit log shows `registry.npmjs.org` tarball GETs with `matchedRule: Host: registry.npmjs.org`. 1 vCPU, 2 GB was enough. |
| 5 | Deny default blocks an unlisted host, audit log shows it | PASS (partial: one host) | `curl https://example.com` returned 403 from the proxy; `egress-decisions` lists it under `denied` (`host: example.com, scheme: https, 2026-10-12T13:00:08Z`). Allowed entries carry `matchedRule`, e.g. `Host: azure.archive.ubuntu.com`. |
| 6 | Push of a scratch branch through the proxy | NOT PROVEN (transport PASS, authenticated push not run) | No single-repo write token was available, and the account-wide token was deliberately removed from Azure. Proven without a token: `git push origin spike/aca-push-probe` to the public repo `stevengonsalvez/foundry-autonomous-sdlc` sends `GET /info/refs?service=git-receive-pack` through the proxy and gets `HTTP/2 401`, `server: GitHub-Babel/3.0`, `www-authenticate: Basic realm="GitHub"`. GitHub answers, so the proxy allows the receive-pack endpoint. Not proven: the authenticated `POST git-receive-pack` with a pack body through the TLS-terminating proxy. |
| 7 | Cost | PASS within budget (data lags) | Cost Management query on `rg-sandbox-spike` returned no rows at about 14:00 UTC on 2026-10-12: usage had not been posted yet. Cost data lags by 8 to 24 hours, so the spike's own cost is not yet visible. The earlier session estimated about 0.05 USD. Measured footprint: one sandbox, 1 vCPU, 2 GiB, about 25 minutes running in total (12:59 to 13:09 and 14:03 to 14:20 UTC) (auto-suspend after 300 s idle), 100 MB received, 0.5 MB sent. `rg-fsdlcd-demo` month to date: 10.19 GBP. The resource group is now deleted, so this service principal can no longer query its scope; read the final figure at subscription scope tomorrow. |
| 8 | agy CLI with its credential not on disk | NOT RUN (design only) | See "agy with the credential off disk". |

## Findings

- **Deleting a secret that a Transform rule still references bricks the sandbox.** With the group secret `githubtoken` deleted while the sandbox was suspended, `POST .../resume` returned `500 InternalError "Secret 'githubtoken' not found."` after 444 s, and `set_egress_policy` on the stopped sandbox hung for over 600 s. `ensure_running()` in the SDK swallows the resume error and then times out, so the failure is silent. Recovery: upsert a placeholder secret under the same id (non-credential value), resume (1.0 s), remove the rules, delete the secret. Operating rule: rotate a secret by upsert, never by delete; delete sandboxes before deleting the secrets they reference.
- Suspended sandboxes keep memory and disk: after about one hour suspended, packages installed earlier (git) and the cloned repo were still there.
- `exec` on a suspended sandbox returns `409 GlobalSandboxNotRunning`; it does not auto-resume. Call `ensure_running()` first (now done in `scripts/spike/x.py`).
- The egress decision log is capped: one read held 50 allowed and 9 denied entries, so `npm ci` traffic overwrote older allows. Production audit needs streaming to Log Analytics, not polling this endpoint.
- Default traffic inspection is `Full` (the proxy terminates TLS). The sandbox trusts it via `/etc/ssl/certs/adc-egress-proxy-ca.crt`, `NODE_EXTRA_CA_CERTS`, `SSL_CERT_FILE` and `REQUESTS_CA_BUNDLE`.
- Host rules allow HTTPS only. Plain HTTP to an allowed host is still denied (403), and an advanced `Allow` rule did not change that. The image's apt mirror is `http://azure.archive.ubuntu.com`, so apt fails under Deny. Workaround used: temporarily allow `mirrors.edge.kernel.org` and rewrite the apt sources to HTTPS, then remove the rule. Production would need a custom disk image with git preinstalled.
- The `node-24` image has no git. It runs as `root`, Ubuntu 24.04.5, kernel 6.12.8, node v24.20.0, npm 10.9.2, 1 vCPU, about 2.2 GB RAM, 20 GB disk.
- Policy changes on a running sandbox take effect within seconds (`set_egress_policy`).
- `IDENTITY_ENDPOINT=http://100.64.100.2/msi/token` is present in the sandbox environment; it returned 401 because the group has no managed identity. Never give the group an identity that code inside could use.
- Secret id `gh` is rejected (`400 secretId: The input was not valid`); `githubtoken` works.
- Secrets can be read back by a data-plane owner (`peek_secret`), so the data-plane role must stay with the orchestrator, not the sandbox.

## agy with the credential off disk (step 8, design only)

Not run: agy needs either the owner's Google login (a token file it must read and refresh, which cannot be kept off disk) or an API key. The API key path fits the proxy:

1. Switch agy to a Gemini API key (Google AI Studio or Gemini Enterprise), as the Antigravity FAQ recommends for automated use.
2. Store the key as a group secret, for example `agykey`, key `value`.
3. Allow the model host and add a Transform rule on it: `Set x-goog-api-key` from `secretRef {secretId: agykey, secretKey: value, format: "{value}"}`.
4. If agy refuses to start without a key, give it a placeholder value in its environment; the proxy overwrites the header.

Unverified: whether headless agy accepts an API key at all, which host and header it uses (`generativelanguage.googleapis.com` and `x-goog-api-key` for AI Studio; Vertex uses OAuth bearer tokens, which would need `managedIdentityRef` instead), and whether it sends the key as a query parameter, which a header rule would not replace. Prove it with one `agy -p` call under Deny default egress, the Transform rule in place and the placeholder key in the environment.

## To close step 6

Stevie must supply a fine-grained personal access token with:

- Repository access: only `stevengonsalvez/aca-sandbox-spike-scratch` (the existing private throwaway repo).
- Permissions: Contents read and write (Metadata read is added automatically). Nothing else.
- Expiry: 1 day.

The token goes straight into the group secret (`s3_sandbox.py` reads it from `SPIKE_GH_TOKEN`), never into a file or the repo. The test is `git push origin spike/aca-push-probe` from the clone in the sandbox, then delete the branch and revoke the token. Recreating the spike needs someone with rights to create `rg-sandbox-spike` and assign `Container Apps SandboxGroup Data Owner` on it to the service principal, because the service principal cannot create role assignments.

## Teardown

Done on 2026-10-12 at about 14:20 UTC from the service principal:

- Sandbox `a100e32b-ba61-45b8-8902-591adcfb48a6` deleted (1.3 s); `list_sandboxes` then returned `[]`.
- Group secret `githubtoken`: the real token was deleted before this session; the placeholder used for recovery was deleted; `list_secrets` returned `[]`.
- Sandbox group `sbg-spike` deleted; `az resource list -g rg-sandbox-spike` returned nothing.
- Resource group `rg-sandbox-spike` deleted with `az group delete`; the role assignments on it went with it.
- Proof: `az resource list --tag purpose=sandbox-spike` returns `0` resources, `az group list --tag purpose=sandbox-spike` returns `[]`, `az resource list --resource-type Microsoft.App/sandboxGroups` returns `0`. Limit: the service principal only sees the resource groups it holds roles on; a subscription-wide check needs an owner login.

Left in place: GitHub repo `stevengonsalvez/aca-sandbox-spike-scratch` (PRIVATE, throwaway, not an Azure resource). Keep it for the step 6 retry, then delete it (`gh auth refresh -s delete_repo`, `gh repo delete`).

## Scripts

`scripts/spike/` (parameterised by env, no secrets): `common.py`, `s1_group.py`, `s3_sandbox.py`, `x.py` (resume if needed, then exec a command), `pol.py` (add or remove a host rule), `dec.py` (dump egress decisions).
