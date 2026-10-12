# Thin root: naming, the single resource group, and module wiring.

data "azurerm_client_config" "current" {}

resource "random_string" "suffix" {
  length  = 5
  lower   = true
  upper   = false
  numeric = true
  special = false
}

locals {
  suffix = random_string.suffix.result
  base   = "${var.name_prefix}-${var.environment}"

  tags = merge({
    project     = "foundry-autonomous-sdlc"
    environment = var.environment
    managed_by  = "terraform"
  }, var.tags)
}

# Single resource group: one destroy removes everything billable.
# Never reuse the earlier proof-of-concept group; this stack is independent.
resource "azurerm_resource_group" "demo" {
  name     = "rg-${local.base}"
  location = var.location
  tags     = local.tags
}

module "observability" {
  source = "./modules/observability"

  name                = local.base
  name_suffix         = local.suffix
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location
  daily_quota_gb      = var.log_daily_quota_gb
  tags                = local.tags
}

module "foundry" {
  source = "./modules/foundry"

  name                = local.base
  name_suffix         = local.suffix
  subscription_id     = var.subscription_id
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location
  local_auth_enabled  = var.foundry_local_auth_enabled
  tags                = local.tags

  model_candidates      = var.model_candidates
  model_selection       = var.model_selection
  model_deployment_name = var.model_deployment_name

  application_insights_id                = module.observability.application_insights_id
  application_insights_connection_string = module.observability.application_insights_connection_string

  assign_deployer_role  = var.assign_deployer_roles
  deployer_principal_id = data.azurerm_client_config.current.object_id
}

module "keyvault" {
  source = "./modules/keyvault"

  name                = local.base
  name_suffix         = local.suffix
  resource_group_name = azurerm_resource_group.demo.name
  location            = azurerm_resource_group.demo.location
  tenant_id           = data.azurerm_client_config.current.tenant_id
  tags                = local.tags

  secrets_officer_principal_id = data.azurerm_client_config.current.object_id
  secrets_reader_principal_ids = {
    foundry_project = module.foundry.project_principal_id
  }
}

module "budget" {
  source = "./modules/budget"

  name              = "budget-${local.base}"
  resource_group_id = azurerm_resource_group.demo.id
  amount            = var.budget_amount
  alert_thresholds  = var.budget_alert_thresholds
  contact_emails    = var.budget_contact_emails
}

# Egress allow-list for sdlc-coder (scripts/deploy_agents.py attaches it). Hosts
# come from the coder's code: git and the GitHub API, npm, the Node and agy
# downloads, apt, and this stack's Foundry and Key Vault endpoints. agy's own
# API hosts are not known up front, hence Audit by default: read the would-deny
# decisions of a real job before switching to Enforced (docs/runbook.md).
module "egress_policy" {
  source = "./modules/egress_policy"
  count  = var.coder_egress_mode == "Off" ? 0 : 1

  account_id = module.foundry.account_id
  mode       = var.coder_egress_mode
  allowed_hosts = distinct(concat([
    "github.com",
    "api.github.com",
    "registry.npmjs.org",
    "nodejs.org",
    "deb.debian.org",
    "antigravity.google",
    "antigravity-cli-auto-updater-974169037036.us-central1.run.app",
    trimprefix(module.foundry.account_endpoint, "https://"),
    trimsuffix(trimprefix(module.keyvault.vault_uri, "https://"), "/"),
  ], var.coder_egress_extra_hosts))
}
