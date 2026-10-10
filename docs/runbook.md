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

A GitHub fine-grained personal access token for `stevengonsalvez/foundry-autonomous-sdlc` only, with repository permissions: Contents read and write, Issues read and write, Pull requests read and write, Actions read and write, Checks read, Metadata read.

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

Inside the sandbox each job keeps `$HOME/jobs/<job_id>/state.json` and `$HOME/jobs/<job_id>/log` (secrets redacted). `$HOME` survives idle eviction. A job whose sandbox was evicted mid-run reports `failed` with reason `interrupted`; sending `start` again with the same job resumes from the pushed branch.

Last resort, if the session does not answer: disable the routine (above), then force-delete the coder, which terminates its sessions, and redeploy it. The redeployed agent gets a new identity, so rerun `roles`.

```bash
curl -s -X DELETE "$ENDPOINT/agents/sdlc-coder?api-version=v1&force=true" -H "Authorization: Bearer $TOKEN"
uv run --project agents python scripts/deploy_agents.py hosted --only sdlc-coder
uv run --project agents python scripts/deploy_agents.py roles
```

### Coder job outcomes

| status / reason | Meaning |
|-----------------|---------|
| `succeeded` | feature, bugfix: tests committed first and proven red, implementation green, branch pushed, PR open with `agent:pr`. revise: a new green commit on the PR. maintenance: repaired tests pushed to the PR branch. |
| `failed` / `tests-not-red` | The submitted tests passed already, or a test file failed to load. Nothing was pushed. |
| `failed` / `scope-violation` | The engine touched a path outside `allowed_paths` or a committed test file. The edit was reverted; `detail` lists the paths. |
| `failed` / `max-iterations` | Still red after `max_iterations` engine rounds. |
| `failed` / `engines-exhausted` | agy and the model loop both failed. agy does not exit on a missing or expired token (it prints "Authentication required" and waits for a browser login), so the coder watches its output and kills it on that message, or on a quota message (`quota`, `RESOURCE_EXHAUSTED`, `429`) before any edit, and moves to the model loop. Each agy call is limited to 600 seconds; a timeout without edits is retried once, then counts as a failure. |
| `failed` / `cost-cap` | Model loop spend for the job passed `max_model_usd`. |
| `failed` / `install-failed`, `branch-missing`, `branch-conflict`, `error` | Setup problems; `detail` has the cause. |
| `failed` / `interrupted` | The sandbox was evicted while the job ran. `start` with the same job resumes. |
| `timeout` / `deadline` | `deadline_s` elapsed. |
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

## 9. Commits from the coder

The coder hands the PAT to git only for clone, fetch and push, through `GIT_ASKPASS`: a script without the token, in a fresh root-only directory, deleted after each call, reading the token from that one git process's environment. The token never reaches `.git/config`, the remote URL or any log. agy runs as `agy -p "<prompt>" --mode accept-edits --sandbox` (edits only, shell commands denied). The coder creates the unprivileged user `agyuser` (`useradd -m -s /bin/bash agyuser`) and runs agy, `install_cmd` and `test_cmd` as that user, each with a complete environment built from nothing (`PATH`, `HOME=/home/agyuser`, `LANG`, `TERM`, `CI`, certificate and proxy settings; never the managed identity, Azure, Key Vault or GitHub variables). The privilege drop is the same as `setpriv --reuid --regid --clear-groups` with `env -i`. Measured in the hosted sandbox on 2026-10-10: as `agyuser`, `/proc/<pid>/environ` of root's processes (which hold `IDENTITY_HEADER`) is permission denied, and the managed identity endpoint (`IDENTITY_ENDPOINT`) answers 401 without that header, so with the scrubbed environment the managed identity, and through it Key Vault and the PAT, is unreachable from agy, npm and the tests. agy is installed in `/opt/agy/bin` (root-owned: `agyuser` runs it but cannot change it, and root never writes into `agyuser`'s home except the token file, created link-safely), its token is `/home/agyuser/.gemini/antigravity-cli/antigravity-oauth-token` (0600), node 22 is installed once per session in `/opt/node` (sha256-checked against `SHASUMS256.txt`, owned by root, world-readable and executable, never writable by `agyuser`), and the checkout is `/srv/sdlc-work/<job_id>/checkout`: `agyuser` owns the working tree, root keeps the top directory and `.git`. `npm ci`, the red check, every test run and the clean-install green check all run as `agyuser` in that checkout. Root alone clones, fetches and pushes, checks `.git/config` and `.git/hooks`, and scope-checks every diff. If `useradd` fails, agy, install and tests run as root with the same scrubbed environment. The job state, the status reply and the PR body record which (`agy_user` and `tests_user`; `Engine user:` and `Tests user:`). After every engine run, install and test run the coder rejects new symlinks, changes to `.git/config` or `.git/hooks`, branch switches and any change outside `allowed_paths`, including commits an engine made itself. Commits made in the sandbox are unsigned by design: there is no signing key there, and the branch ruleset deliberately has no signed-commit rule (adding one would block every agent push). Their author is `foundry-autonomous-sdlc` with the owner's GitHub noreply address (`<numeric id>+stevengonsalvez@users.noreply.github.com`, looked up at run time), or `noreply@users.noreply.github.com` when the lookup fails. Messages are conventional commits: `test: add failing tests for #N` first, then `feat:` or `fix:`; maintenance commits are `test: repair stale tests for #N`.

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

- If `useradd` fails, agy, install and tests run as root with the scrubbed environment: the job cannot run otherwise, and `agy_user: root` / `tests_user: root` in the status and PR body make it visible for review.
- Code under test runs as the same user as vitest and can therefore forge the JSON report: inherent to running tests; CI reruns every gate on the pushed commit and the reviewer agent reads the diff before any merge.
- The agy installer script is fetched over HTTPS from antigravity.google and run as root once per session: the same trust as installing the vendor CLI by hand; the binary is then root-owned and only executed as `agyuser`.
- `give_tree` changes ownership by path without dir-fd checks: every `agyuser` process is killed (and the kill verified) before it runs, so the tree cannot change underneath it.
- `install_cmd` and `test_cmd` run through a shell: job validation allows only plain words (letters, digits, spaces and `._/=:@,+%-`), so no job field can chain, substitute or redirect commands.

