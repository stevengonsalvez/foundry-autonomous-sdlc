# Runbook

From a fresh clone to a running system, then day-to-day operation and teardown. Run every command from the repository root unless a step says otherwise. Commands are bash.

```
┌───────────┐   ┌───────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ az login  │──▶│ terraform │──▶│ secrets into │──▶│ deploy       │──▶│ routine      │
│ gh login  │   │ bootstrap │   │ Key Vault    │   │ agents (all) │   │ --enable     │
└───────────┘   │ + stack   │   └──────────────┘   └──────────────┘   └──────────────┘
                └───────────┘
```

## 1. Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Azure CLI | 2.80 or later | `az version` |
| Terraform | 1.9 or later | `terraform version` |
| uv | any recent | `uv --version` |
| GitHub CLI, authenticated as the repo owner | any recent | `gh auth status` |
| jq | any | `jq --version` |
| Antigravity CLI (`agy`), signed in on this machine | 1.3.3 or later | `test -s "$HOME/.gemini/antigravity-cli/antigravity-oauth-token" && echo present` |

The `agy` token file appears after the first interactive sign-in of the CLI on your machine. The hosted coder reuses that token from Key Vault; see "Plan-token terms" in `docs/findings.md` before reusing this pattern beyond the demo.

A GitHub fine-grained personal access token with repository permissions: Contents read and write, Issues read and write, Pull requests read and write, Actions read and write, Checks read, Metadata read. The token in use today is granted on all repositories of the account, not only this one (see "Reviewed and accepted"); the code only ever addresses `stevengonsalvez/foundry-autonomous-sdlc`.

## 2. Sign in

```bash
az login
az account show --query "{subscription:id, user:user.name}" -o table
gh auth login
```

## 3. Infrastructure

Remote state storage first (local state, kept in `infra/terraform/bootstrap`):

```bash
cd infra/terraform/bootstrap
cat > bootstrap.tfvars <<EOF
subscription_id   = "$(az account show --query id -o tsv)"
allowed_ip_ranges = ["$(curl -4 -s https://ifconfig.me)"]
EOF
terraform init
terraform plan -var-file=bootstrap.tfvars -out bootstrap.tfplan
terraform apply bootstrap.tfplan
cd ../../..
```

Then the stack, with its state in that storage:

```bash
cd infra/terraform
cat > terraform.tfvars <<EOF
subscription_id = "$(az account show --query id -o tsv)"
EOF
cp backend.tf.example backend.tf
terraform -chdir=bootstrap output -raw backend_hcl > backend.hcl
terraform init -backend-config=backend.hcl
terraform plan -out tfplan
terraform apply tfplan
cd ../..
```

The apply creates the resource group `rg-fsdlcd-demo`, the Foundry account and project, the `sdlc-default` model deployment (gpt-5-mini, 10k tokens per minute), Key Vault, App Insights and a 5 USD budget with alerts. Check the outputs the deploy script reads:

```bash
terraform -chdir=infra/terraform output
```

## 4. Secrets

Both secrets go into the stack's Key Vault. Terraform grants you `Key Vault Secrets Officer` on it. Neither value is ever passed on a command line.

```bash
KV=$(terraform -chdir=infra/terraform output -raw key_vault_name)
read -rs GITHUB_PAT
printf '%s' "$GITHUB_PAT" | az keyvault secret set --vault-name "$KV" --name github-pat --file /dev/stdin --output none
unset GITHUB_PAT
az keyvault secret set --vault-name "$KV" --name agy-cli-token \
  --file "$HOME/.gemini/antigravity-cli/antigravity-oauth-token" --output none
az keyvault secret list --vault-name "$KV" --query "[].name" -o tsv
```

`read -rs` waits for you to paste the PAT and press Enter; nothing is echoed. The last command must list `agy-cli-token` and `github-pat`.

## 5. Repository settings

Labels, Pages and Actions settings, then the branch ruleset with the six required checks:

```bash
python3 scripts/setup_repo.py --phase bootstrap --dry-run
python3 scripts/setup_repo.py --phase bootstrap
python3 scripts/setup_repo.py --phase protect
```

Run `protect` after the scaffold is on `main`: the ruleset requires pull requests. The ruleset must not require signed commits, because the coder's commits are unsigned (see section 9).

## 6. Deploy the agents

`scripts/deploy_agents.py` reads its configuration from `terraform output` (or from `FOUNDRY_PROJECT_ENDPOINT`, `KEY_VAULT_URI`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP` when set) and uses your `az login`. Every step is idempotent; rerun it after any change.

```bash
uv sync --project agents
uv run --project agents python scripts/deploy_agents.py --dry-run all
uv run --project agents python scripts/deploy_agents.py all
```

`all` runs, in order:

| Step | What it does |
|------|--------------|
| `connection` | Creates or updates the project connection `github-mcp` (category RemoteTool, auth CustomKeys, target `https://api.githubcopilot.com/mcp/`, key `Authorization: Bearer <github-pat>`). The PAT is read from Key Vault and never printed. |
| `prompt-agents` | Registers the prompt agent versions (`python -m sdlc_agents.create_agents`). |
| `hosted` | Zips and deploys `sdlc-orchestrator` (1 vCPU, 2Gi, idle timeout 2 minutes) and `sdlc-coder` (2 vCPU, 4Gi, idle timeout 30 minutes): `python_3_13`, `remote_build`, Invocations 2.0.0. Waits up to 900 seconds for status `active` and prints `error.message` on failure. An unchanged zip and definition reuse the existing version. |
| `roles` | Assigns `Key Vault Secrets User` on single secrets (orchestrator: `github-pat`; coder: `github-pat`, `agy-cli-token`) and `Foundry User` on the project to both hosted agents: the orchestrator calls the prompt agents and the coder, the coder's fallback engine calls the model. Role ids are resolved by name with `az role definition list`. |
| `routine` | Creates the routine `sdlc-tick` (cron `*/5 * * * *`, UTC, Invocations body `{"op":"tick"}` to `sdlc-orchestrator`) disabled. The spike routine `probe-tick` cannot be deleted yet; it is kept disabled. |

The idle timeout decides how long compute stays billed after the last request. The orchestrator's 2 minutes (the platform minimum) is shorter than the five minute tick, so its compute is released between ticks; the coder's 30 minutes keeps a running job alive between the orchestrator's status polls. Sizes, idle timeouts (2 to 60 minutes) and the wait can be overridden, for example:

```bash
uv run --project agents python scripts/deploy_agents.py hosted --only sdlc-coder --coder-cpu 1 --coder-memory 2Gi --coder-idle-minutes 45 --timeout 1200
```

Role assignments take a minute or more to propagate. Check the deployment and that the coder answers (two status calls for a job that does not exist; both must return 404 `unknown_job` in the same session), then start the loop:

```bash
uv run --project agents python scripts/deploy_agents.py status
uv run --project agents python scripts/deploy_agents.py smoke
uv run --project agents python scripts/deploy_agents.py routine --enable
```

`status` prints each agent's latest version, state and identity principal, both routines, and their last five runs. The first tick runs within five minutes of enabling.

## 7. Operating

### Health

```bash
uv run --project agents python scripts/deploy_agents.py status
gh issue list --repo stevengonsalvez/foundry-autonomous-sdlc --label stage:building
gh pr list --repo stevengonsalvez/foundry-autonomous-sdlc --label agent:pr
```

### Stop the loop

Disabling the routine stops new ticks; a coder job already running continues until it finishes, hits its deadline, or is cancelled.

```bash
uv run --project agents python scripts/deploy_agents.py routine --disable
```

### Inspect or cancel a coder job

The orchestrator records the coder's `job_id` and `session_id` in the issue's state comment. Set `ISSUE` to the issue number, then:

```bash
ISSUE=12
ENDPOINT=$(terraform -chdir=infra/terraform output -raw foundry_project_endpoint)
TOKEN=$(az account get-access-token --resource https://ai.azure.com --query accessToken -o tsv)
STATE=$(gh api --paginate "repos/stevengonsalvez/foundry-autonomous-sdlc/issues/$ISSUE/comments" \
  --jq '.[] | select(.user.login == "stevengonsalvez") | select(.body | startswith("<!-- sdlc-state:v1")) | .body' \
  | sed -n 2p)
JOB=$(jq -r .coder.job_id <<<"$STATE")
SESSION=$(jq -r .coder.session_id <<<"$STATE")
CODER="$ENDPOINT/agents/sdlc-coder/endpoint/protocols/invocations?api-version=v1&agent_session_id=$SESSION"

curl -s -X POST "$CODER" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"op\":\"status\",\"job_id\":\"$JOB\"}" | jq '{status, phase, reason, detail, iterations, engine, elapsed_s, pr, cost}'
```

Cancel it. The running engine or test command is killed, the job ends `cancelled`, and no push starts after the cancel is seen:

```bash
curl -s -X POST "$CODER" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"op\":\"cancel\",\"job_id\":\"$JOB\"}" | jq .
```

Follow the coder's container log live:

```bash
curl -N "$ENDPOINT/agents/sdlc-coder/sessions/$SESSION:logstream?api-version=v1" \
  -H "Authorization: Bearer $TOKEN" -H "Accept: text/event-stream"
```

Inside the sandbox each job keeps `$HOME/jobs/<job_id>/state.json` and `$HOME/jobs/<job_id>/log` (secrets redacted). `$HOME` survives idle eviction. A job whose sandbox was evicted mid-run reports `failed` with reason `interrupted`; sending `start` again with the same job resumes from the pushed branch. `state.json` is rewritten at least every 30 seconds while a job runs, so `stale_s` in `status` well above 30 means the job thread is stuck or gone. Memory, for diagnosing an out-of-memory kill (the sandbox has 4 GiB): the job log records the cgroup `memory.max` and `memory.peak` at job start and end, and after every child step (install, tests, typecheck, lint, each engine round) a line `memory <step>: peak group RSS <n> MiB, largest process <n> MiB`, sampled from `/proc` once a second while the step runs. Unhandled exceptions (job threads and requests) are printed with their traceback to stdout, so the logstream shows them.

Last resort, if the session does not answer: disable the routine (above), then force-delete the coder, which terminates its sessions, and redeploy it. The redeployed agent gets a new identity, so rerun `roles`.

```bash
curl -s -X DELETE "$ENDPOINT/agents/sdlc-coder?api-version=v1&force=true" -H "Authorization: Bearer $TOKEN"
uv run --project agents python scripts/deploy_agents.py hosted --only sdlc-coder
uv run --project agents python scripts/deploy_agents.py roles
```

### Coder job outcomes

| status / reason | Meaning |
|-----------------|---------|
| `succeeded` | Green means what CI's `test` job checks (without the build): `npm test` passes, then `npm run typecheck` and `npm run lint` pass in the workdir, run as `agyuser`; their result lines are in the job log, `green` and the PR body, and their errors (first 40, redacted) go into the next engine prompt. feature, bugfix: tests committed first and proven red, implementation green, branch pushed, PR open with `agent:pr`. revise: a new green commit on the PR. maintenance: repaired tests pushed to the PR branch. |
| `failed` / `tests-not-red` | The submitted tests already pass. Nothing was pushed. |
| `failed` / `tests-invalid` | A new test is broken rather than red: it fails with an error instead of an assertion (`ReferenceError`, `TypeError`, `SyntaxError`, "is not defined", "is not a function", a missing module or export, a timeout), its file fails to load, or vitest did not collect it; or, right after the test commit and before any engine runs, `npm run typecheck` or `npm run lint` reports an error in a new test file (`detail` lines `<path>(line,col): error TSxxxx: message`; errors only in other files are ignored at that step and block green later). `detail` lists the first error line per broken test, for the test designer. Only assertion failures (`AssertionError`, "expected ...", Testing Library "Unable to find") count as red. Nothing was pushed. |
| `failed` / `scope-violation` | The engine touched a path outside `allowed_paths` or a committed test file. The edit was reverted; `detail` lists the paths. |
| `failed` / `max-iterations` | Still red after `max_iterations` engine rounds. |
| `failed` / `engines-exhausted` | agy and the model loop both failed. agy does not exit on a missing or expired token (it prints "Authentication required" and waits for a browser login), so the coder watches its output and kills it on that message, or on a quota message (`quota`, `RESOURCE_EXHAUSTED`, `429`) before any edit, and moves to the model loop. Each agy call is limited to 600 seconds; a timeout without edits is retried once, then counts as a failure. |
| `failed` / `cost-cap` | Model loop spend for the job passed `max_model_usd`. |
| `failed` / `install-failed`, `branch-missing`, `branch-conflict`, `error` | Setup problems; `detail` has the cause. |
| `failed` / `sandbox-unavailable` | The unprivileged engine user could not be created; the coder never runs agy, install or tests as root, so it did nothing. |
| `failed` / `lease-held` | Another job already holds `agent-lease/<issue>`; this one did no work (reply to `start`, not persisted). |
| `failed` / `interrupted` | The sandbox was evicted while the job ran (a restarted server marks such jobs at once). `start` with the same job resumes. |
| `failed` / `internal-error` | An unexpected exception in the coder itself. `detail` has the redacted traceback tail, the same traceback is in the job log and on stdout (the platform logstream); the lease was released. A coder bug: read the traceback before retrying. |
| `failed` / `invalid-allowed-paths` | revise or maintenance: no `allowed_paths` entry matches a file at the head of the branch (`detail` names them). Fix the paths the orchestrator sent. |
| `timeout` / `deadline` | `deadline_s` elapsed. If the job was stuck, the watchdog (every 30 s heartbeat) records this 60 s past the deadline and cancels it, `detail` starting `watchdog:`. |
| `cancelled` | A `cancel` call stopped it. |

## 8. Cost caps

| Cap | Value | Enforced by |
|-----|-------|-------------|
| Per issue | 1.00 USD of model and coder compute | Orchestrator, label `escalated:cost-cap` |
| All work | New work halts at 4.50 USD total (`metrics.json` `totals.usd`) | Orchestrator |
| Monthly budget | 5 USD, alerts only, data lags up to 72 hours | Terraform budget on the resource group |
| Model throughput | 10k tokens per minute on `sdlc-default` | Model deployment capacity |
| Coder job | `max_iterations` 5, `deadline_s` 7200 (default and maximum: two hours of coder compute is about 0.54 USD against the 1 USD issue cap), model loop spend 0.50 USD | Coder runtime hard stops |
| Hosted compute | 0.10934 USD per vCPU-hour and 0.01298 USD per GiB-hour (UK South list price), billed while a session is active | Idle timeouts: orchestrator 2 minutes (0.1353 USD per active hour at 1 vCPU, 2 GiB; a one minute tick plus the 2 minute idle tail is about 0.007 USD), coder 30 minutes (0.2706 USD per active hour at 2 vCPU, 4 GiB) |

agy usage is billed to the Antigravity plan behind the token and is not metered by the demo.

## 9. How the coder isolates and checks its work

**Engine user (fail closed).** The coder creates the unprivileged user `agyuser` (`useradd -m -s /bin/bash agyuser`) and runs agy, `install_cmd` and `test_cmd` only as that user, each with an environment built from nothing (`PATH`, `HOME=/home/agyuser`, `LANG`, `TERM`, `CI`, certificate and proxy settings; never the managed identity, Azure, Key Vault or GitHub variables). The drop is the same as `setpriv --reuid --regid --clear-groups` with `env -i`. If the user cannot be created the job fails with `sandbox-unavailable`; nothing ever runs as root. Measured in the hosted sandbox on 2026-10-10: as `agyuser`, `/proc/<pid>/environ` of root's processes (which hold `IDENTITY_HEADER`) is permission denied and the managed identity endpoint answers 401 without that header.

**Layout.** node 22 is installed once per session in `/opt/node` (sha256-checked against `SHASUMS256.txt`), agy in `/opt/agy/bin`; both are root-owned, so `agyuser` runs them but cannot change them. The checkout is `/srv/sdlc-work/<job_id>/checkout`: `agyuser` owns the working tree, root keeps the top directory and `.git`. agy's token and `settings.json` live in `/home/agyuser/.gemini/antigravity-cli/` (0600), written link-safely by root.

**Engines, in order.**

| Engine | How it runs | Moves on when |
|--------|-------------|---------------|
| `agy` | `agy -p "<prompt>" --mode accept-edits` with the allow-list, no `--sandbox` (agy's own sandbox blocked every command, `SANDBOX_COMMAND_BLOCKED`, in job j-10-1; the engine user is the isolation) | always after exactly one round; the event says why (`engine-permission-denied`, `engine-no-progress`, or `committed`) |
| `agy-unrestricted` | `agy -p "<prompt>" --dangerously-skip-permissions`, no `--sandbox`, still as `agyuser`, same environment, settings rewritten, same scans and reaping; never constructed for root | after at most two rounds (the second continues from the first's edits with the failing output), a failure |
| `loop` | the model deployment `sdlc-default`; the coder writes the returned files itself, only inside `allowed_paths` | two rounds without a change, a failure |

The allow-list, rewritten by root before every agy call (its sha256 is logged): `ls`, `cat`, `head`, `tail`, `wc`, `grep`, read-only git (`status`, `diff`, `log`, `show`, `ls-files`), `npm test`, `npm run lint|typecheck|test|test:coverage` and `npx vitest run`, with arguments limited to plain words that cannot start with a dash plus a short list of harmless flags. Every commit is recorded in `engine_events` (`committed`, with its sha and engine) and listed in the PR body with the engine that produced it, for example `Engine: agy-unrestricted (agyuser, skip-permissions after allow-list denial)`. Each `agy` round is capped at 360 seconds (`AGY_RESTRICTED_CALL_TIMEOUT_S`) and each `agy-unrestricted` round at 900 (`AGY_UNRESTRICTED_CALL_TIMEOUT_S`), both within the job deadline; a timeout without edits is retried once, a timeout with edits keeps them and goes to the test run. Every round is recorded in `engine_events` as `round` with `seconds` (wall time), `timed_out` and `returncode`. Each round writes a debug log (`--log-file`, `agy-iter<N>.log`); the job log gets a redacted excerpt: the `CLI settings initialized` line, every `SANDBOX_COMMAND_BLOCKED` line and every line about permissions, denials, tool calls and commands (3000 characters at most). The coder creates empty `~/.bashrc` and `~/.profile` for `agyuser` (agy reads them before its first command).

**Checks root makes after every engine round, install and test run** (all `agyuser` processes are killed and the kill verified first; any hit fails the job with `scope-violation` before anything is pushed):

- `.git/config` and `.git/hooks` unchanged;
- no `.git` file or directory anywhere below the checkout root (a nested repository's own config could make root's git run a command); found ones are deleted;
- no new or retargeted symlink outside `node_modules`, and no symlink anywhere whose target is absolute, resolves outside the checkout or lands in a `.git`. Targets are resolved without following anything: the link's own folder must be real directories from the root, then the target is walked one component at a time with `lstat`, a link on the way is a violation and `..` never steps back over a link; as a second check the link's `realpath` must stay inside the checkout and outside `.git`. Links inside `node_modules` (npm workspace links such as `app/node_modules/@parcel/core -> ../../core`, `.bin` entries) are allowed when they pass that check; `node_modules` is gitignored, so they are never staged. Each entry is examined before anything is pruned, so a link merely named `node_modules` counts as outside and is caught; a real `node_modules` owned by `agyuser` is only checked one level deep (and inside `@scope` and `.bin` folders);
- every changed path inside `allowed_paths`, no existing test file, vitest config, `.gitattributes` or `.gitmodules` touched, nothing staged as a gitlink (mode 160000) or symlink (120000), the branch not switched; commits an engine made itself are undone first so their content is checked too;
- root's own git calls ignore submodules, use no attributes file (`core.attributesFile=/dev/null`, `GIT_ATTR_NOSYSTEM=1`), no hooks and no fsmonitor, and never re-add a staged gitlink.

**Pushing.** Root pushes exactly the commit it verified (`<sha>:refs/heads/<branch>`, refused if HEAD moved) after re-checking that commit's files and modes. A PR is reused only if it is the owner's and its head lives in this repository.

**One job per issue.** `start` for a new `job_id` first creates the ref `agent-lease/<issue>` through the GitHub API. If it already exists the reply is `{"status": "failed", "reason": "lease-held"}` and no work is done. The orchestrator deletes the lease when the job ends.

**Commits.** Unsigned by design: there is no signing key in the sandbox, and the branch ruleset deliberately has no signed-commit rule (adding one would block every agent push). The author is `foundry-autonomous-sdlc` with the owner's GitHub noreply address (looked up at run time) or `noreply@users.noreply.github.com`. Messages are conventional commits: `test: add failing tests for #N` first, then `feat:` or `fix:`; maintenance commits are `test: repair stale tests for #N`. The PAT reaches git only for clone, fetch and push, through `GIT_ASKPASS` (a token-free script in a fresh root-only directory, deleted after each call); it never reaches `.git/config`, the remote URL or a log.

## 10. Teardown

```bash
uv run --project agents python scripts/deploy_agents.py routine --disable
cd infra/terraform
terraform destroy
terraform -chdir=bootstrap destroy -var-file=bootstrap.tfvars
rm backend.tf backend.hcl
cd ../..
```

The first `destroy` deletes the resource group with the Foundry account (agents, routines, connection and deployment inside it), Key Vault and App Insights. The second deletes the state storage; run it only after the first has finished.

## Reviewed and accepted

Findings from the security review of the coder (2026-10-10) that remain by design, each with the reason:

- Code under test runs as the same user as vitest and can therefore forge the JSON report: inherent to running tests; CI reruns every gate on the pushed commit and the reviewer agent reads the diff before any merge.
- The agy installer script is fetched over HTTPS from antigravity.google and run as root once per session: the same trust as installing the vendor CLI by hand; the binary is then root-owned and only executed as `agyuser`.
- `give_tree` changes ownership by path without dir-fd checks: every `agyuser` process is killed (and the kill verified) before it runs, so the tree cannot change underneath it.
- agy runs without its own `--sandbox` and, after one allow-list round, with `--dangerously-skip-permissions` (owner decision D10; `--sandbox` blocked every command): the boundary is `agyuser` with an environment built from nothing, no root path at all (`sandbox-unavailable` without the user), and root's checks before every push, so agy can do no more than `npm test` already can.
- agy's command allow-list is guidance for the engine, not a security boundary: `npm test` already runs code agy wrote, as `agyuser`, so a determined engine can run anything `agyuser` can. The boundary is the unprivileged user, its environment built from nothing (no identity header, no Azure, Key Vault or GitHub values), no secrets on disk it can read, root-owned `.git`, node and agy, and root's scans and scope checks before every push. The list is kept tight (no `find`, plain-word arguments) only to keep the engine on task.
- `install_cmd` and `test_cmd` run through a shell: job validation allows only plain words (letters, digits, spaces and `._/=:@,+%-`), so no job field can chain, substitute or redirect commands.

Orchestrator findings (fail-open spend, trust boundary; 2026-10-10) that remain by design:

- A per-issue spend floor from `metrics.json` only covers objects still listed: if a human both strips an issue's pipeline labels and deletes its state comment, its per-issue figure restarts, but `totals.usd` (and so the 4.50 USD halt) never decreases, and the issue gets no further spend unless it is relabelled.
- The `checks` and `head` sections of the reviewer input are trusted: they hold only the head sha, the PR number, the six check names and GitHub's own conclusion values; branch names, titles, bodies, commits, diffs and logs are passed as untrusted data.
- MCP agents can ask `get_file_contents` for any repository the `github-mcp` PAT can read, which is every repository of the account: the orchestrator only narrows this (one read-only tool, a two to four call budget, a prompt rule naming this repository, schema validation and sanitising before anything is posted); it cannot technically prevent a cross-repository read.
- A coder status that cannot be read is billed as estimated time (wall clock since start, less 15 minutes of normal poll gap), which can over-count briefly; over-counting only stops spend earlier.
- The `github-mcp` connection carries the same fine-grained PAT, which covers all repositories of the account (not just this one) and can write. The connection sends `X-MCP-Readonly: true` (the GitHub MCP server's read-only mode) and the prompt agents may call only `get_file_contents`, on this repository by instruction; reads of other repositories are prevented only by that instruction and the read-only header. No human is in the loop to mint another token; the follow-up is a separate read-only PAT scoped to this repository for the connection.
- With no engine user (`useradd` failed) the coder does not run at all (`sandbox-unavailable`); there is no root fallback for agy, install or tests.

