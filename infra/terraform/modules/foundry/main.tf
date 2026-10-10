locals {
  # Built-in role definition IDs. Use GUIDs, not names: the Foundry roles were
  # renamed (Azure AI User -> Foundry User) and Microsoft advises GUIDs in code.
  role_definition_ids = {
    foundry_user                 = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/53ca6127-db72-4b80-b1b0-d745d6d5456d"
    monitoring_metrics_publisher = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/3913510d-42f4-4e42-8a64-420c390055eb"
  }
}

# ---------------------------------------------------------------------------
# Foundry account (kind AIServices) and project
# ---------------------------------------------------------------------------

resource "azurerm_cognitive_account" "foundry" {
  #checkov:skip=CKV2_AZURE_22:Microsoft-managed keys; a CMK needs a Key Vault and key rotation, out of PoC scope
  #checkov:skip=CKV_AZURE_134:PoC decision recorded in docs/findings.md, public endpoint with Entra-only auth (local_auth_enabled defaults to false)
  name                = "aif-${var.name}-${var.name_suffix}"
  location            = var.location
  resource_group_name = var.resource_group_name
  kind                = "AIServices"
  sku_name            = "S0"

  # Required for projects and for Entra ID auth (Agent Service).
  custom_subdomain_name      = "aif-${var.name}-${var.name_suffix}"
  project_management_enabled = true

  # PoC decision: public endpoint (gap recorded). Access is Entra ID only
  # unless local_auth_enabled is switched on, so the endpoint alone grants nothing.
  public_network_access_enabled = true
  local_auth_enabled            = var.local_auth_enabled

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

resource "azurerm_cognitive_account_project" "sdlc" {
  name                 = "proj-sdlc"
  cognitive_account_id = azurerm_cognitive_account.foundry.id
  location             = var.location
  display_name         = "SDLC agents PoC"
  description          = "Foundry Agent Service SDLC proof of concept (triage, code gen, review, CI triage)."

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

# No capability host: basic agent setup uses Microsoft-managed storage when
# none exists. Standard (BYO Cosmos DB, Storage, AI Search) setup needs
# azapi_resource for accounts/capabilityHosts and projects/capabilityHosts.

# ---------------------------------------------------------------------------
# Model deployment: pinned by default, quota-aware selection on "auto"
# ---------------------------------------------------------------------------

# Regional quota for this subscription. Read-only GET, only when "auto". A
# failed lookup fails the plan; nothing falls back silently.
data "azapi_resource_action" "model_usages" {
  count = local.auto_select ? 1 : 0

  type                   = "Microsoft.CognitiveServices/locations@2025-06-01"
  resource_id            = "/subscriptions/${var.subscription_id}/providers/Microsoft.CognitiveServices/locations/${var.location}"
  action                 = "usages"
  method                 = "GET"
  response_export_values = ["value"]
}

locals {
  auto_select = var.model_selection == "auto"

  # Usage names look like "OpenAI.GlobalStandard.gpt-5-mini". Deliberately no
  # try(): a response without .value must error, not read as "zero quota".
  quota_limits = local.auto_select ? {
    for u in data.azapi_resource_action.model_usages[0].output.value :
    u.name.value => u.limit
  } : {}

  # Select on the quota LIMIT, not limit - currentValue. Our own deployment
  # consumes quota, so remaining quota changes after apply; the limit does not.
  # This keeps the selection stable across plans (no replace churn).
  eligible_models = [
    for m in var.model_candidates : m
    if local.auto_select
    ? lookup(local.quota_limits, "OpenAI.${m.sku_name}.${m.name}", 0) >= m.capacity
    : m.name == var.model_selection
  ]

  model_selected_ok = length(local.eligible_models) > 0
  selected_model    = local.model_selected_ok ? local.eligible_models[0] : var.model_candidates[0]
}

resource "azurerm_cognitive_deployment" "default" {
  name                 = var.model_deployment_name
  cognitive_account_id = azurerm_cognitive_account.foundry.id

  model {
    format  = "OpenAI"
    name    = local.selected_model.name
    version = local.selected_model.version
  }

  sku {
    name     = local.selected_model.sku_name
    capacity = local.selected_model.capacity
  }

  # Avoid silent version bumps (model block changes force replacement).
  version_upgrade_option = "OnceCurrentVersionExpired"

  lifecycle {
    precondition {
      condition     = local.model_selected_ok
      error_message = "No model candidate has quota >= its capacity in ${var.location}. Request quota, change location, lower capacity, or pin model_selection."
    }
  }
}

# ---------------------------------------------------------------------------
# Tracing: project connection to Application Insights, keyless
#   (azurerm has account-level connection resources only; project-level
#   connections need azapi. Pattern from microsoft-foundry/foundry-samples
#   infrastructure-setup-terraform/20-user-assigned-identity/code/monitor.tf)
# ---------------------------------------------------------------------------

resource "azapi_resource" "appinsights_connection" {
  type                      = "Microsoft.CognitiveServices/accounts/projects/connections@2025-09-01"
  name                      = "appinsights-tracing"
  parent_id                 = azurerm_cognitive_account_project.sdlc.id
  schema_validation_enabled = false

  body = {
    properties = {
      category      = "AppInsights"
      target        = var.application_insights_id
      authType      = "ProjectManagedIdentity"
      isSharedToAll = false
      metadata = {
        ApiType                             = "Azure"
        ResourceId                          = var.application_insights_id
        ApplicationInsightsConnectionString = var.application_insights_connection_string
      }
    }
  }
}

# ---------------------------------------------------------------------------
# RBAC for the project identity and the human deployer
# ---------------------------------------------------------------------------

# Project managed identity: Foundry User on the account (Microsoft's minimum
# assignment for agents) and keyless trace ingestion into App Insights.
resource "azurerm_role_assignment" "project_foundry_user" {
  scope                            = azurerm_cognitive_account.foundry.id
  role_definition_id               = local.role_definition_ids.foundry_user
  principal_id                     = azurerm_cognitive_account_project.sdlc.identity[0].principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

resource "azurerm_role_assignment" "project_metrics_publisher" {
  scope                            = var.application_insights_id
  role_definition_id               = local.role_definition_ids.monitoring_metrics_publisher
  principal_id                     = azurerm_cognitive_account_project.sdlc.identity[0].principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

# Human operator: Owner has no Foundry data actions, so add Foundry User.
resource "azurerm_role_assignment" "deployer_foundry_user" {
  count = var.assign_deployer_role ? 1 : 0

  scope              = azurerm_cognitive_account.foundry.id
  role_definition_id = local.role_definition_ids.foundry_user
  principal_id       = var.deployer_principal_id
}
