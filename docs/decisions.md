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
