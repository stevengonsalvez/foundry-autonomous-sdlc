terraform {
  # Cross-variable validation (model_selection vs model_candidates) needs >= 1.9.
  required_version = ">= 1.9.0, < 2.0.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.9"
    }
    azapi = {
      source  = "Azure/azapi"
      version = "~> 2.13"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }

  # State is local until bootstrap/ has created the storage account. Then copy
  # backend.tf.example to backend.tf and migrate; see README.md.
}
