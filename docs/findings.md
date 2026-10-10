# Findings

Every row is something we ran, with the evidence. Dates are 2026-10-10 unless stated. Stack: personal free-trial subscription, UK South, resource group `rg-fsdlcd-demo`, Foundry project `proj-sdlc`.

## Spike results (before building)

| Question | Result | Evidence |
|----------|--------|----------|
| Do hosted agents deploy from a zip on the free trial in UK South? | Yes | `create_version_from_code` with `python_3_13`, `remote_build`, Invocations protocol reached `status: active` in about 70 seconds. Response header `x-ms-region: UK South`. |
| What does the sandbox contain? | Debian 12, root, 1 vCPU, 8.6 GB persistent `$HOME` (`/home/session`), Python 3.13 at `/app/pythonenv3.13`. No `git`, `node`, `npm`, `uv`. `curl`, `wget`, `gcc`, `unzip` present. | Probe agent diagnostics output. |
| Does the sandbox have outbound internet? | Yes: github.com, api.github.com, antigravity.google, npm registry, PyPI all returned 200. | Probe `net` output. |
| Can the sandbox install tools? | `apt-get install git` works as root (git 2.39.5). `pip` inside the platform venv is broken (`cannot execute: required file not found`), so every Python dependency must be in the zip `requirements.txt`. | Probe commands. |
| Does `agy` (Antigravity CLI) run headless on Linux? | Yes. Linux amd64 build 1.3.3 installs with the official installer, auth is a token file at `~/.gemini/antigravity-cli/antigravity-oauth-token` (mode 600), non-interactive mode is `agy -p "<prompt>"`. Reply `PONG` in 6.9 s inside the hosted sandbox, 9 s in a local Linux container. | Local container run, then sandbox run. |
| Can the hosted agent read secrets from Key Vault without a key? | Yes. The agent has its own Entra identity (`instance_identity`), granted `Key Vault Secrets User` on two individual secrets. The agent exchanged its managed identity for a vault token and read the token over REST. | Sandbox run printed `token file bytes 1454` and agy authenticated. |
| Do Routines work on the trial? | Yes. A `schedule` trigger (cron, five-minute minimum) and a manual `dispatch_async` both invoked a hosted agent through the Invocations API; run status `Finished completed`. | `GET routines/probe-tick/runs`. |
| Can a routine be deleted? | Not yet. `DELETE` on a schedule routine returns `MissingConnectorGatewayArmId: schedule triggers cannot be deleted until ConnectorGateway provisioning completes`. Disable works. | HTTP 400 body. Stub routine left disabled and reused. |
| Do prompt agents on gpt-5-mini call the GitHub MCP server with a PAT? | Yes. A `CustomKeys` project connection (`Authorization: Bearer <PAT>`, category `RemoteTool`, target `https://api.githubcopilot.com/mcp/`) plus `MCPTool(require_approval="never", allowed_tools=[...])` read `README.md` from the repo. 1,466 input and 158 output tokens. | Spike output: `mcp_call get_file_contents completed`. |
| Is the Routines GitHub trigger usable unattended? | No. The `github_issue` trigger needs a GitHub connector connection that must be authorised through an OAuth consent URL in a browser, which is a human step. | Routines how-to, connector section. We poll with a schedule trigger instead. |
| What is the session model? | Session ids are issued by the platform (`x-agent-session-id` on the first call). Custom ids are rejected with `invalid_session_id`. Compute is deprovisioned after the idle timeout (2 to 60 minutes) and `$HOME` is restored on the next request. | HTTP 400 body and docs. |
| Can the sandbox run the coding CLI as an unprivileged user? | Yes. `useradd`, `su`, `runuser` and `setpriv` work. As that user, `/proc/1/environ` is permission denied, and the managed identity endpoint (`http://100.64.100.2/msi/token`, from `IDENTITY_ENDPOINT`) returns 401 without the secret `IDENTITY_HEADER`, which exists only in root's environment. `su` keeps the caller's environment, so the coder must pass an explicit scrubbed one. | Sandbox probe run, second deploy of the probe agent. |
| What does `agy -p` do when it has no valid login? | It does not exit. It prints `Authentication required. Please visit the URL to log in:` and blocks until killed (our 60 s timeout ended it with exit 124), with a missing token file and with an expired token alike. The coder must watch the output for that phrase, kill the process and fall back. | Sandbox probe run. |
| Headless permissions | `agy -p ... --mode accept-edits --sandbox` writes files and auto-denies shell commands (`a tool required the "command" permission that headless mode cannot prompt for`), so `--dangerously-skip-permissions` is not needed. | Local run in a throwaway repo. |
| Hosted agent compute price | Hosted vCPU 0.10934 USD per hour, hosted memory 0.01298 USD per GiB-hour, billed while a session is active. Azure later also billed the same sessions as Container Apps usage, see the spend finding below. | Azure Retail Prices API, UK South. |

## Decisions forced by the spikes

See `docs/decisions.md` for the full list. The short version: the orchestrator is a hosted agent (code) rather than a prompt agent, because gpt-5-mini cannot call functions or other agents, and merge gating must be deterministic.

## Plan-token terms (recorded decision)

The `agy` OAuth token is a personal login (its `auth_method` field is `consumer`). Running it from a cloud container may be a use the plan terms do not anticipate. The official install page we read states no policy on automated or CI use, and we did not find the plan terms themselves, so this is unverified. We use it for a bounded demo with low iteration counts, keep it in Key Vault, and the fallback chain does not depend on it: if agy is blocked or out of quota the coder falls back to an Agent Framework loop on gpt-5-mini, and failing that to a worker outside Foundry. Review the terms before reusing this pattern for anything beyond a demo.

## Findings from the live run

Things that only appeared once the real system ran, in the order they were hit. Each was fixed and has a regression test.

| Finding | Effect | Fix |
|---------|--------|-----|
| The model deployment was capped at 10 requests and 10K tokens per minute | A tool-using prompt agent got HTTP 429 | Raised to 50K TPM in Terraform |
| An MCP agent looped on `search_code` and directory listings, resending large tool output each step | HTTP 429 after about 40 s even at 50K TPM, because the hosted tool loop does not retry the throttled step | MCP limited to `get_file_contents`, hard budget of 2 reads in the prompt, the test designer gets pre-fetched file context. After: 4 to 5 s and 1.2K to 1.7K input tokens |
| Three failed feasibility calls (429) produced the verdict label `escalated:not-agent-suitable` on a well-formed feature | An infrastructure error changed an issue's verdict | Transient errors are retried or deferred and never count; persistent failures escalate as `escalated:agent-error` |
| Hosted agent zip rejected with `No Python dependency manifest found at the project root` although `requirements.txt` was at the root | First deploy failed | The zip builders wrote entry modes without the regular-file bit (`0o644 << 16`); `0o100644 << 16` is accepted |
| The test designer produced a test without importing `expect` (`ReferenceError: expect is not defined`) | The red check accepted a load-time error as red, so no implementation could ever pass | Red must be an assertion failure (coder and CI gate), designed tests are linted and sent back for repair |
| `agy -p` was soft-denied on shell commands even with an allow-list (settings loaded, per its debug log) and agy's own `--sandbox` blocked even its startup `cat ~/.bashrc` | Every coder round ended without edits after about 4 minutes | `--sandbox` dropped, the allow-list round is capped at one, then `agy --dangerously-skip-permissions` as the unprivileged user (owner decision D10) |
| When agy failed twice the model-loop fallback rewrote unrelated code | 126 tests, 3 files failed to load; nothing was pushed | Kept as the last resort only; scope checks and the clean reinstall catch it |
| A reviewer-driven hardening rejected the standard npm workspace links (`node_modules/@parcel/core -> ../../core`) as escapes | Every coder job failed at setup | Links inside `node_modules` are judged by their resolved target |
| Maintenance triage claimed a path that does not exist (`app/tests/parcel-page.test.tsx`) | The repair job had nothing valid to edit and pushed junk or nothing (PRs #27 and #33) | The orchestrator hands triage the real test file list and keeps only real paths, plus every test file the log shows failing |
| Repair covered the vitest files but not `app/e2e/tests/parcel-tracking.spec.ts`, which also asserted the old heading | e2e stayed red and PR #36 escalated `build-failed` although 7 of 8 e2e tests passed | Triage also claims every test file, `app/e2e` included, that contains text the diff removed from the app (PR #38 then passed 8 of 8 checks) |
| The reviewer applied tests-first ordering to a maintenance repair, where the owner's app change legitimately comes first | PR #38 was rejected with a high finding although `tdd-order` already exempts the label, and the stale rejection kept starting no-op revise jobs (attempt 6 of 8) | The reviewer gets a trusted `kind` section on maintenance PRs and a prompt exception; #38 was closed and the scenario re-run as #40 |
| The spend ledger said 1.86 USD while Azure Cost Management billed 4.80 USD (3.62 GBP) for the resource group | The first figure was an estimate from list prices; the real one is 2.6 times higher. Hosted sessions are metered twice, as Foundry 'Hosted vCPU/Memory Usage' (1.62 GBP) and as Container Apps 'Standard vCPU/Memory Active Usage' (1.88 GBP), and the sessions stay billed until they idle out after each job. Model tokens were only 0.13 GBP. The 4.50 USD halt therefore did not protect the 5 USD limit | The ledger now uses both meters (0.2318 USD per vCPU-hour, 0.0274 per GiB-hour), charges one idle tail per finished coder job, and the coder idle timeout drops from 30 to 10 minutes. Azure's own figure is the one to trust: query `Microsoft.CostManagement/query` as in the runbook |
| The coder published a crash as `failed` before releasing its lease | A retry started on seeing it could meet `lease-held`; one crash test was flaky in CI | The lease is released first |
| A coder session can disappear (`session_not_accessible`) | Its log is gone; issue #16 could not be diagnosed afterwards | Failed jobs leave a redacted coder-log comment on the issue, and a lost session restarts once |
| Security reviews of the coder found a nested-repo filter running as root, a symlink named `node_modules` slipping past the scan, a root fallback that failed open, and a lost `start` reply that could create a duplicate job | See `docs/runbook.md`, "Reviewed and accepted" | All closed test-first |

## Fresh clone reproduction (criterion 3)

A clone of the public repository was bootstrapped and applied into a separate resource group (`rg-fsdlcv-verify`, state in `rg-fsdlcv-tfstate`) with the commands in `docs/runbook.md`: `terraform apply` from clean created 15 resources (Foundry account and project with the `sdlc-default` deployment, Application Insights and Log Analytics, Key Vault, budget, role assignments) and a working Foundry project endpoint. `terraform destroy` then removed 15 and 5 resources and no `rg-fsdlcv-*` group was left.

## Evidence added during the run

Later sections are appended by the scenarios (issue to release traces, cost table, gate pass rates).
