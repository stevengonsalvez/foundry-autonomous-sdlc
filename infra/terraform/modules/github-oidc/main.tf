# Identity for GitHub Actions: user-assigned managed identity + OIDC federated
# credentials. Lives in the stack's resource group, so destroy removes it. No
# Entra app registration and no azuread provider needed.

locals {
  # Built-in role definition IDs (GUIDs, not names; see the foundry module).
  role_definition_ids = {
    foundry_user                 = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/53ca6127-db72-4b80-b1b0-d745d6d5456d"
    monitoring_metrics_publisher = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/3913510d-42f4-4e42-8a64-420c390055eb"
  }

  # GitHub repos created after 2026-07-15 emit immutable subjects:
  #   repo:OWNER@OWNER_ID/REPO@REPO_ID:...
  repo_segment = var.github_repo_id == null ? "${var.github_owner}/${var.github_repo}" : "${var.github_owner}@${var.github_owner_id}/${var.github_repo}@${var.github_repo_id}"
  issuer       = "https://token.actions.githubusercontent.com"
  audience     = "api://AzureADTokenExchange"
}

resource "azurerm_user_assigned_identity" "github" {
  name                = "id-${var.name}-github"
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = var.tags
}

# Credentials are chained with depends_on: Entra rejects concurrent
# federated-credential writes on the same managed identity.
resource "azurerm_federated_identity_credential" "github_branch" {
  name                      = "github-${var.github_default_branch}"
  user_assigned_identity_id = azurerm_user_assigned_identity.github.id
  issuer                    = local.issuer
  audience                  = [local.audience]
  subject                   = "repo:${local.repo_segment}:ref:refs/heads/${var.github_default_branch}"
}

# SECURITY GAP: any same-repo PR author can obtain a token via this credential; see "Gaps and follow-ups" in docs/findings.md.
resource "azurerm_federated_identity_credential" "github_pull_request" {
  count = var.allow_pull_request ? 1 : 0

  name                      = "github-pull-request"
  user_assigned_identity_id = azurerm_user_assigned_identity.github.id
  issuer                    = local.issuer
  audience                  = [local.audience]
  subject                   = "repo:${local.repo_segment}:pull_request"

  depends_on = [azurerm_federated_identity_credential.github_branch]
}

resource "azurerm_federated_identity_credential" "github_environment" {
  count = var.github_environment == null ? 0 : 1

  name                      = "github-env-${var.github_environment}"
  user_assigned_identity_id = azurerm_user_assigned_identity.github.id
  issuer                    = local.issuer
  audience                  = [local.audience]
  subject                   = "repo:${local.repo_segment}:environment:${var.github_environment}"

  depends_on = [
    azurerm_federated_identity_credential.github_branch,
    azurerm_federated_identity_credential.github_pull_request,
  ]
}

# ---------------------------------------------------------------------------
# RBAC (least privilege that still lets CI register agent versions)
# ---------------------------------------------------------------------------

# GitHub identity: Foundry User on the PROJECT scope only (no account or RG
# scope). Narrower options failed live on 2026-10-09: Foundry Agent Consumer
# only allows endpoints/interact (published agent endpoints) and a custom role
# with AIServices agents/responses plus OpenAI responses/chat actions still
# returned an empty HTTP 403 on POST /openai/v1/responses. Foundry User is
# Microsoft's documented role for running agents. Accepted PoC gap: CI can also
# create agents in this one project. Follow-up: find the exact missing data
# action and replace this with a custom role.
resource "azurerm_role_assignment" "github_foundry_user" {
  scope                            = var.foundry_project_id
  role_definition_id               = local.role_definition_ids.foundry_user
  principal_id                     = azurerm_user_assigned_identity.github.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

# GitHub identity may send runner-side OpenTelemetry spans with Entra auth.
resource "azurerm_role_assignment" "github_metrics_publisher" {
  scope                            = var.application_insights_id
  role_definition_id               = local.role_definition_ids.monitoring_metrics_publisher
  principal_id                     = azurerm_user_assigned_identity.github.principal_id
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}
