locals {
  # Built-in role GUIDs. Names are avoided on purpose, Microsoft renames roles.
  role_ids = {
    secrets_officer = "b86a8fe4-44ce-4948-aee5-eccb2c155cd7"
    secrets_user    = "4633458b-17de-408a-b874-0445c86b69e6"
  }
}

# RBAC mode (no access policies). Public endpoint is a recorded demo decision:
# access is Entra ID only. Purge protection stays off so one destroy removes it.
# tflint-ignore: azurerm_resources_missing_prevent_destroy # teardown is one terraform destroy; soft delete (7 days) covers accidents
resource "azurerm_key_vault" "this" {
  #checkov:skip=CKV_AZURE_109:Demo decision recorded in docs/decisions.md, public endpoint with Entra-only RBAC
  #checkov:skip=CKV_AZURE_189:Same decision as CKV_AZURE_109
  #checkov:skip=CKV_AZURE_42:Recoverable via soft delete (7 days); purge protection stays off so one terraform destroy removes the demo
  #checkov:skip=CKV_AZURE_110:Purge protection off so terraform destroy leaves nothing behind (soft delete 7 days stays on)
  #checkov:skip=CKV2_AZURE_32:No private endpoint, private networking is out of scope
  name                = "kv-${var.name}-${var.name_suffix}"
  location            = var.location
  resource_group_name = var.resource_group_name
  tenant_id           = var.tenant_id
  sku_name            = "standard"

  rbac_authorization_enabled = true
  soft_delete_retention_days = 7
  purge_protection_enabled   = false

  tags = var.tags
}

resource "azurerm_role_assignment" "officer" {
  scope              = azurerm_key_vault.this.id
  role_definition_id = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/${local.role_ids.secrets_officer}"
  principal_id       = var.secrets_officer_principal_id
}

resource "azurerm_role_assignment" "readers" {
  for_each = var.secrets_reader_principal_ids

  scope                            = azurerm_key_vault.this.id
  role_definition_id               = "/subscriptions/${data.azurerm_client_config.current.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/${local.role_ids.secrets_user}"
  principal_id                     = each.value
  principal_type                   = "ServicePrincipal"
  skip_service_principal_aad_check = true
}

data "azurerm_client_config" "current" {}
