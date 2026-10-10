variable "subscription_id" {
  type        = string
  description = "Azure subscription to deploy into (the personal Free Trial subscription for the PoC)."

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be a GUID."
  }
}

variable "location" {
  type        = string
  default     = "uksouth"
  description = "Azure region for every resource. UK South lists Agent Service; on the trial subscription only gpt-5-mini has non-zero GlobalStandard quota there."
}

variable "name_prefix" {
  type        = string
  default     = "fsdlc"
  description = "Short prefix for resource names. A random suffix is appended to globally unique names."

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,10}$", var.name_prefix))
    error_message = "name_prefix must be 3 to 11 lowercase letters or digits, starting with a letter."
  }
}

variable "environment" {
  type        = string
  default     = "poc"
  description = "Environment tag and name segment."

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,7}$", var.environment)) && var.environment != "tfstate"
    error_message = "environment must be 2 to 8 lowercase letters or digits, starting with a letter, and not \"tfstate\" (that RG name belongs to bootstrap)."
  }
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Extra tags merged onto every taggable resource."
}

# ---------------------------------------------------------------------------
# Model deployment. Pinned by name by default; "auto" picks the first
# candidate with enough quota. Input validation lives in modules/foundry.
# ---------------------------------------------------------------------------

variable "model_candidates" {
  type = list(object({
    name     = string
    version  = string
    sku_name = string
    capacity = number # thousands of tokens per minute (1 = 1,000 TPM)
  }))
  description = "Ordered model preference list. Versions from the Foundry 'models sold directly by Azure' page, checked 2026-10-09."

  default = [
    { name = "gpt-5.4-nano", version = "2026-03-17", sku_name = "GlobalStandard", capacity = 10 },
    { name = "gpt-5-nano", version = "2025-08-07", sku_name = "GlobalStandard", capacity = 10 },
    { name = "gpt-5-mini", version = "2025-08-07", sku_name = "GlobalStandard", capacity = 10 },
  ]
}

variable "model_selection" {
  type        = string
  default     = "gpt-5-mini"
  description = <<-EOT
    A model_candidates name pins that model with no quota lookup (default: gpt-5-mini,
    the only candidate with GlobalStandard quota on the trial subscription in UK South).
    "auto" opts in to reading the subscription's regional quota
    (Microsoft.CognitiveServices/locations/usages) at plan time and deploying the first
    candidate whose quota limit is >= its capacity. With "auto", a failed or malformed
    quota lookup fails the plan. A candidate absent from the usages response counts as zero quota. The pinned name must be in model_candidates (validated in modules/foundry), so keep it there when overriding the list.
  EOT
}

variable "model_deployment_name" {
  type        = string
  default     = "sdlc-default"
  description = "Stable deployment name that agents reference, independent of which model was selected."
}

# ---------------------------------------------------------------------------
# GitHub OIDC federation
# ---------------------------------------------------------------------------

variable "github_owner" {
  type        = string
  description = "GitHub user or org that owns the sandbox repo."
}

variable "github_repo" {
  type        = string
  description = "Sandbox repository name (without owner)."
}

variable "github_owner_id" {
  type        = number
  default     = null
  description = "Numeric owner id. Set together with github_repo_id when the repo uses immutable OIDC subjects (default for repos created after 2026-07-15). Get it with: gh api repos/OWNER/REPO --jq .owner.id"
}

variable "github_repo_id" {
  type        = number
  default     = null
  description = "Numeric repository id. Get it with: gh api repos/OWNER/REPO --jq .id"
}

variable "github_default_branch" {
  type        = string
  default     = "main"
  description = "Branch whose workflows (issues, issue_comment, workflow_run, schedule, workflow_dispatch) may log in to Azure."
}

variable "github_allow_pull_request" {
  type        = bool
  default     = true
  description = "Add a federated credential for the pull_request subject (needed by the PR review stage). SECURITY GAP: any same-repo PR author can obtain a token; set false to remove it (see docs/findings.md)."
}

variable "github_environment" {
  type        = string
  default     = null
  description = "Optional GitHub environment name. When a job declares an environment, the OIDC subject becomes environment:<name>."
}

# ---------------------------------------------------------------------------
# Cost guardrails
# ---------------------------------------------------------------------------

variable "budget_amount" {
  type        = number
  default     = 100
  description = "Monthly resource-group budget in the billing currency (USD). Alerts lag usage by up to about 72 hours on pay-as-you-go style offers, so keep it well under the 200 USD credit."
}

variable "budget_alert_thresholds" {
  type        = list(number)
  default     = [25, 50, 75]
  description = "Actual-cost alert thresholds as percent of budget_amount (spec: 25/50/75)."
}

variable "budget_contact_emails" {
  type        = list(string)
  default     = []
  description = "Extra recipients for budget alerts. Subscription Owners are always notified via contact_roles."
}

variable "log_daily_quota_gb" {
  type        = number
  default     = 0.15
  description = "Log Analytics daily ingestion cap. 0.15 GB/day keeps a month under the 5 GB free ingestion tier."
}

variable "foundry_local_auth_enabled" {
  type        = bool
  default     = false
  description = "API keys on the Foundry account. False = Entra ID only (keyless)."
}

variable "assign_deployer_roles" {
  type        = bool
  default     = true
  description = "Grant the principal running Terraform the Foundry User role on the Foundry account so it can create agents from a laptop."
}
