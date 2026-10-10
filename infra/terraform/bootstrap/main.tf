# Remote state for the stack in ../ : a resource group, a hardened storage
# account (Entra ID only, versioned, TLS 1.2, firewalled) and one container.
# Destroy this LAST, after the stack itself has been destroyed.

data "azurerm_client_config" "current" {}

resource "random_string" "suffix" {
  length  = 5
  lower   = true
  upper   = false
  numeric = true
  special = false
}

locals {
  tags = merge({
    project    = "foundry-sdlc-poc"
    purpose    = "terraform-state"
    managed_by = "terraform"
  }, var.tags)

  # Storage IP rules take bare addresses for single hosts; /32 is rejected.
  ip_rules = [for r in var.allowed_ip_ranges : trimsuffix(r, "/32")]

  storage_blob_data_contributor = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/ba92f5b4-2d11-453d-a403-e96b0029c9fe"
}

resource "azurerm_resource_group" "tfstate" {
  name     = "rg-${var.name_prefix}-tfstate"
  location = var.location
  tags     = local.tags
}

# tflint-ignore: azurerm_resources_missing_prevent_destroy # teardown is a documented second destroy; prevent_destroy would block it
resource "azurerm_storage_account" "tfstate" {
  #checkov:skip=CKV_AZURE_59:Operator runs Terraform from a laptop with no private endpoint; firewall default Deny plus IP allow-list plus Entra-only auth
  #checkov:skip=CKV_AZURE_33:Queue service is unused (state is blob only); azurerm 5.x has no queue_properties on this resource
  #checkov:skip=CKV_AZURE_206:LRS is enough for a PoC state file; blob versioning and soft delete cover accidental overwrites
  #checkov:skip=CKV2_AZURE_33:No private endpoint for the same reason as CKV_AZURE_59; firewall default Deny plus IP allow-list
  #checkov:skip=CKV2_AZURE_1:Microsoft-managed keys plus infrastructure double encryption; a CMK needs a Key Vault, out of PoC scope
  name                     = "st${var.name_prefix}tf${random_string.suffix.result}"
  resource_group_name      = azurerm_resource_group.tfstate.name
  location                 = azurerm_resource_group.tfstate.location
  account_kind             = "StorageV2"
  account_tier             = "Standard"
  account_replication_type = "LRS"

  # Entra ID only: no shared keys, no SFTP local users, OAuth in the portal.
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  local_user_enabled              = false
  sftp_enabled                    = false

  min_tls_version                   = "TLS1_2"
  https_traffic_only_enabled        = true
  infrastructure_encryption_enabled = true
  allow_nested_items_to_be_public   = false
  cross_tenant_replication_enabled  = false

  # Reachable only from allowed_ip_ranges (and trusted Azure services).
  public_network_access = "Enabled"
  network_rules {
    default_action = "Deny"
    bypass         = ["AzureServices"]
    ip_rules       = local.ip_rules
  }

  sas_policy {
    expiration_period = "00.01:00:00"
    expiration_action = "Block"
  }

  blob_properties {
    versioning_enabled = true

    delete_retention_policy {
      days = 30
    }

    container_delete_retention_policy {
      days = 30
    }
  }

  tags = local.tags
}

# tflint-ignore: azurerm_resources_missing_prevent_destroy # teardown is a documented second destroy; prevent_destroy would block it
resource "azurerm_storage_container" "tfstate" {
  #checkov:skip=CKV2_AZURE_21:Accepted gap, no read audit log sink in bootstrap (it outlives the stack's workspace); versioning records writes only
  name                  = var.container_name
  storage_account_id    = azurerm_storage_account.tfstate.id
  container_access_type = "private"
}

# The deployer reads and writes state (and takes the blob lease lock) with its
# Entra identity. Scoped to the container, not the account.
resource "azurerm_role_assignment" "deployer_state" {
  scope              = azurerm_storage_container.tfstate.id
  role_definition_id = local.storage_blob_data_contributor
  principal_id       = data.azurerm_client_config.current.object_id
}
