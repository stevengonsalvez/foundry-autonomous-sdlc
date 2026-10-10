provider "azurerm" {
  subscription_id = var.subscription_id

  # Shared keys are disabled on the state account, so any data-plane call the
  # provider makes must use Entra ID.
  storage_use_azuread = true

  resource_providers_to_register = ["Microsoft.Storage"]

  features {}
}
