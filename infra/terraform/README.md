# Foundry SDLC PoC: Terraform

One resource group, public endpoints, keyless (Entra ID only), one low-TPM model
deployment, App Insights tracing, a budget with alerts, and a GitHub Actions
identity federated over OIDC. `terraform destroy` removes everything billable.

```
┌──────────────┐  OIDC   ┌───────────────────┐  Foundry User   ┌──────────────┐
│ GitHub       │────────▶│ UAMI id-*-github  │────────────────▶│ Project      │
│ Actions      │         │ (federated creds) │ (project scope) │ proj-sdlc    │
└──────────────┘         └───────────────────┘                 └──────┬───────┘
                                                                      │
┌──────────────┐  ProjectManagedIdentity conn  ┌───────────────────┐  │
│ App Insights │◀──────────────────────────────│ Foundry account   │◀─┘
│ + Log Anal.  │  Monitoring Metrics Publisher │ kind AIServices   │
└──────────────┘                               │ deployment 10k TPM│
                                               └───────────────────┘
All inside rg-<prefix>-<env>, plus a resource-group budget (alerts only).
```

## Layout

```
infra/terraform/
├── main.tf, variables.tf, outputs.tf   thin root: naming, RG, module wiring
├── providers.tf, versions.tf           provider config and pins
├── moved.tf                            one-off state moves (flat root -> modules)
├── backend.tf.example                  azurerm backend, activate after bootstrap
├── backend.hcl.example                 backend settings (generate from bootstrap)
├── .tflint.hcl                         tflint + azurerm ruleset, pinned
├── modules/
│   ├── foundry/        account, project, model deployment (pinned or quota-aware),
│   │                   App Insights tracing connection, project + deployer RBAC
│   ├── observability/  Log Analytics + workspace-based App Insights
│   ├── egress_policy/  sdlc-coder egress allow-list (account RAI policy, preview), off by default
│   ├── github-oidc/    UAMI, federated credentials, CI role assignments
│   └── budget/         RG budget + alerts
└── bootstrap/          separate root, local state: remote state storage
```

```
┌───────────┐ creates ┌───────────────────┐ holds state of ┌──────────────┐
│ bootstrap │────────▶│ st<prefix>tf<sfx> │◀───────────────│ root (stack) │
│ local tfst│         │ container tfstate │                │ modules/*    │
└───────────┘         └───────────────────┘                └──────────────┘
```

## Model selection

Default `model_selection = "gpt-5-mini"`: pinned, no quota lookup.

`model_selection = "auto"` opts in to reading
`Microsoft.CognitiveServices/locations/<region>/usages` at plan time and deploying
the first candidate whose quota **limit** (`OpenAI.<sku>.<model>`) covers its
capacity. On the trial subscription on 2026-10-09 this resolves to gpt-5-mini
in UK South. If the lookup call fails or returns an unexpected shape, the plan
fails. A candidate missing from the response counts as zero quota.

## Inputs

Create `terraform.tfvars` (git-ignored):

```hcl
subscription_id = "<subscription-id>"
github_owner    = "stevengonsalvez"
github_repo     = "foundry-sdlc-sandbox"
github_owner_id = 9320602    # immutable OIDC subjects (repos after 2026-07-15)
github_repo_id  = 1411081453
```

`github_allow_pull_request` (default `true`) controls the `pull_request`
federated credential. That credential is a recorded security gap (any same-repo
PR author can obtain a token, see docs/findings.md); set it `false` to remove it.

## Run

Lint and validate (no Azure access needed):

```bash
terraform fmt -recursive -check
terraform init -backend=false && terraform validate
terraform -chdir=bootstrap init -backend=false && terraform -chdir=bootstrap validate
tflint --init && tflint --recursive --config "$(pwd)/.tflint.hcl"   # tflint >= 0.54
checkov -d . --framework terraform
```

Apply (operator, `az login` on the trial subscription). Local state until
`backend.tf` exists; with it, use `terraform init -backend-config=backend.hcl`:

```bash
terraform init
terraform plan -out tfplan
terraform apply tfplan
```

Remote state: follow [bootstrap/README.md](bootstrap/README.md). Order matters:
bootstrap apply, then `terraform apply` of the stack (saves the module moves
into state), then `terraform init -migrate-state -backend-config=backend.hcl`.
Every plan along the way should read `0 to add, 0 to change, 0 to destroy`
(a plan before the first apply also lists the 15 pending moves).

## Destroy (two steps, in this order)

```bash
terraform destroy                       # 1. stack: RG, Foundry account (purged)
terraform -chdir=bootstrap destroy \
  -var-file=bootstrap.tfvars            # 2. state storage, only after step 1
```

Step 2 deletes the remote state and its versions. Do not run it while the
stack still exists. Afterwards remove `backend.tf` and `backend.hcl`, which
point at the deleted account.

## Known limits

- Budgets alert only; cost data can lag up to 72 hours on credit offers. The
  real spend brakes are the TPM cap and `terraform destroy`.
- Foundry account has a public endpoint (checkov `CKV_AZURE_134` skipped
  inline); access is Entra ID only.
- `prevent_deletion_if_contains_resources = false`: destroy also deletes
  anything created by hand in the RG. Intended.
- `moved.tf` can be deleted only after `terraform apply` has succeeded on every
  state that predates the modules. A plan alone does not record the moves;
  deleting it early would plan to destroy and recreate the stack.
