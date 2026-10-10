provider "azurerm" {
  subscription_id = var.subscription_id

  # azurerm 5.x registers no resource providers by default
  # (resource_provider_registrations = "none"). Register only what this
  # configuration uses.
  resource_providers_to_register = [
    "Microsoft.CognitiveServices",
    "Microsoft.Consumption",
    "Microsoft.Insights",
    "Microsoft.KeyVault",
    "Microsoft.ManagedIdentity",
    "Microsoft.OperationalInsights",
  ]

  features {
    cognitive_account {
      # Default is already true; stated explicitly because a soft-deleted
      # account keeps its name reserved for 48 hours.
      purge_soft_delete_on_destroy = true
    }

    resource_group {
      # Application Insights creates a smart-detection action group that
      # Terraform does not manage. Allow destroy to remove the whole group so
      # one `terraform destroy` removes everything billable.
      prevent_deletion_if_contains_resources = false
    }
  }
}

provider "azapi" {
  subscription_id = var.subscription_id
}
