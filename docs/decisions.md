# Decisions

Newest at the bottom. Each entry says what was decided, why, and what would reverse it.

## D1. Fresh Azure stack, separate state

New resource group `rg-fsdlcd-demo` and a new remote-state account (`rg-fsdlcd-tfstate`) with prefix `fsdlcd`. The earlier proof-of-concept group `rg-fsdlc-poc` and its state are not touched. Reverse if: never; the two must stay independent.

## D2. The orchestrator is a hosted agent in code, not a prompt agent

Foundry prompt agents on gpt-5-mini cannot call functions or other agents (the model's tool support table marks them unsupported; confirmed in the earlier proof of concept), so a prompt agent cannot invoke the specialist agents or the coder. Merge gating must also be deterministic: a prompt-injected model must not be able to merge. So the orchestrator is a hosted agent whose state machine is ordinary tested code; Routines wake it; it calls the prompt agents and the coder. The GitHub MCP tool is used where a model does the reading (feasibility, test design, review). Reverse if: a model with function calling and enough quota becomes available, then a prompt agent could own the loop.

## D3. Poll with a schedule trigger instead of the `github_issue` trigger

The `github_issue` trigger needs a GitHub OAuth consent in a browser, a human step, and fires only on opened and closed. A `*/5` schedule covers every transition without a human. Cost: up to five minutes latency per step.

## D4. Gates are enforced three times

Server side by the branch ruleset (six required checks, no bypass actors), in CI by the check scripts, and in the orchestrator by an explicit pre-merge check on the head sha. The review marker is bound to the head sha so a later push invalidates the approval.

## D5. Auto-merge with a merge commit

Squash merging would erase the commit order evidence on `main`. The tests-first check runs on the PR, and a merge commit keeps `test:` before `feat:` visible in history afterwards.

## D6. Only the repo owner can trigger spend

The repo is public. Issues and PRs from anyone else are ignored by the orchestrator and receive no agent calls. Workflows never receive secrets.

## D7. The coder edits files; code does everything else

`agy` only edits the working tree. Cloning, test commits, red/green checks, scope checks, pushing and opening the PR are code, so the process is reproducible and the CLI can be swapped (agy, then a model loop, then an outside worker) without changing the guarantees.

## D8. Public endpoints, Entra-only auth

Key Vault and Foundry keep public network access with RBAC and Entra ID only (no keys). Private networking is out of scope for the demo.

## D9. Dependencies for hosted agents are pinned in `requirements.txt` and resolved remotely

`pip` inside the platform venv is broken, and a zip is limited to 250 MB. `remote_build` resolves the pinned requirements in the cloud. The 214 MB agy binary is downloaded at run time inside the sandbox, never bundled.

## D10. The coding CLI runs with edit-only permissions, never with permissions skipped

Issue text is untrusted, and the coder sandbox can reach the managed identity that reads the GitHub token from Key Vault. Running the CLI with `--dangerously-skip-permissions` would let a prompt injection turn into shell access and token theft. We tested `agy -p ... --mode accept-edits --sandbox` headless: it edits files, and every shell command is auto-denied. The CLI needs no shell because our code runs the tests and feeds failures back. Defence in depth: the CLI process gets a scrubbed environment (no identity, Azure, Foundry, Key Vault or GitHub variables), the PAT exists only inside short-lived git subprocesses owned by the coder process, the CLI runs as an unprivileged user where the sandbox allows it, and after every run the checkout is scanned for symlinks, out-of-scope paths and changes under `.git`. The one credential the CLI can read is its own login token, which it needs by design; the residual risk is its exposure to a hostile prompt, reduced by owner-only issues, requirement and feasibility screening, scope checks and the review agent. Model-loop fallback edits are path-checked with resolved containment and symlink rejection. Reverse if: agy gains a first-class allow-list for specific shell commands, then tests could run inside it.

Update (owner decision, 2026-10-10): in the first live runs agy's shell commands were soft-denied even with an allow-list in `settings.json`, so it could not explore the repo. The coder now tries the allow-list first and, only when agy is denied or makes no progress, retries the same job with `--dangerously-skip-permissions` as the unprivileged `agyuser`. That is acceptable because the allow-list was never the security boundary: `npm test` already runs agent-written code as `agyuser`. The boundary is the separate user, an environment built from nothing, no readable secrets apart from agy's own login, root-owned `.git`, node and agy binaries, and root's scans before every push. The skip flag is never used when the coder had to fall back to running as root.

## D11. A separate state-keeper agent writes the data plane the control center reads

`sdlc-ledger` is a hosted agent in code (same pattern as D2) that is the only writer of branch `state`. Code derives every number; a model only writes a one line summary and its output is dropped if it adds a number, link or markup. Rejected: a prompt agent on a routine (cannot hold state or write git deterministically), plain code inside the orchestrator as the default (couples the dashboard's data to the tick and its failures). Kept as the fallback: `LEDGER_MODE=inline` runs the same class inside the orchestrator with the same schema, for when the hosted agent breaks the spend cap or cannot scale to zero. Reverse if: the hosted agent's bill per call is larger than the value of the isolation.

## D12. Pages serves prod at the root and staging under `/staging/` from branch `deploy`

GitHub Pages deploys one artifact, so staging and prod cannot be deployed independently. Branch `deploy` holds both built apps and `deploy.json`; `pages.yml` is the only deployer and renders what `deploy` says; `cd.yml` changes `deploy` and waits. A release is promoted by copying the already smoke tested staging artifact (the app build is path agnostic, hash router, relative base), never by rebuilding. Rollback restores the artifact prod already serves. Details in `docs/cd.md`.

## D13. The control center reads GitHub, holds no token and writes nothing

Data arrives by unauthenticated reads of `raw.githubusercontent.com` (30 s, but that CDN caches for up to 300 s, measured) and, as budget allows, the GitHub API (60 requests per hour per IP, cached 60 s). New issues are shown from the public issue list as "waiting for ledger" so a ticket is visible within about a minute even though the orchestrator ticks every five. Rejected: a token in the browser, a backend, an Actions workflow with Azure credentials that wakes the ledger on every issue event (CI and Pages keep the rule that they hold no Azure credential).

## D14. Spend after the cap was found to be exceeded

Azure billed 13.02 USD for the resource group by 2026-10-11, against the 5 USD cap the first run reported as met at 4.80 USD (billing lag). No human was available to re-authorise spend, so this work added no orchestrator tick, no coder job and no model call beyond the ledger's summaries, kept the routine disabled, and bounded the ledger to cents (0.25 vCPU, 0.5 GiB, 2 minute idle, a handful of calls). The ledger's compute is metered, recorded and shown; the billed-versus-ledger gap is shown in the cost view rather than hidden. Reverse if: the owner raises the cap, then run the live scenarios again with the routine enabled.
