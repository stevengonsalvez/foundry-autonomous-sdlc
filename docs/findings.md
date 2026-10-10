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

## Decisions forced by the spikes

See `docs/decisions.md` for the full list. The short version: the orchestrator is a hosted agent (code) rather than a prompt agent, because gpt-5-mini cannot call functions or other agents, and merge gating must be deterministic.

## Plan-token terms (recorded decision)

The `agy` OAuth token is a personal login (its `auth_method` field is `consumer`). Running it from a cloud container may be a use the plan terms do not anticipate. The official install page we read states no policy on automated or CI use, and we did not find the plan terms themselves, so this is unverified. We use it for a bounded demo with low iteration counts, keep it in Key Vault, and the fallback chain does not depend on it: if agy is blocked or out of quota the coder falls back to an Agent Framework loop on gpt-5-mini, and failing that to a worker outside Foundry. Review the terms before reusing this pattern for anything beyond a demo.

## Evidence added during the run

Later sections are appended by the scenarios (issue to release traces, cost table, gate pass rates).
