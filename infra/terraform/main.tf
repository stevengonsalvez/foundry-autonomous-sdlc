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
    project     = "foundry-sdlc-poc"
    environment = var.environment
    managed_by  = "terraform"
  }, var.tags)
}

# Single resource group: one destroy removes everything billable.
resource "azurerm_resource_group" "poc" {
  name     = "rg-${local.base}"
  location = var.location
  tags     = local.tags
}

module "observability" {
  source = "./modules/observability"

  name                = local.base
  name_suffix         = local.suffix
  resource_group_name = azurerm_resource_group.poc.name
  location            = azurerm_resource_group.poc.location
  daily_quota_gb      = var.log_daily_quota_gb
  tags                = local.tags
}

module "foundry" {
  source = "./modules/foundry"

  name                = local.base
  name_suffix         = local.suffix
  subscription_id     = var.subscription_id
  resource_group_name = azurerm_resource_group.poc.name
  location            = azurerm_resource_group.poc.location
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

module "github_oidc" {
  source = "./modules/github-oidc"

  name                = local.base
  subscription_id     = var.subscription_id
  resource_group_name = azurerm_resource_group.poc.name
  location            = azurerm_resource_group.poc.location
  tags                = local.tags

  github_owner          = var.github_owner
  github_repo           = var.github_repo
  github_owner_id       = var.github_owner_id
  github_repo_id        = var.github_repo_id
  github_default_branch = var.github_default_branch
  allow_pull_request    = var.github_allow_pull_request
  github_environment    = var.github_environment

  foundry_project_id      = module.foundry.project_id
  application_insights_id = module.observability.application_insights_id
}

module "budget" {
  source = "./modules/budget"

  name              = "budget-${local.base}"
  resource_group_id = azurerm_resource_group.poc.id
  amount            = var.budget_amount
  alert_thresholds  = var.budget_alert_thresholds
  contact_emails    = var.budget_contact_emails
}
