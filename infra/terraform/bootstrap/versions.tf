terraform {
  required_version = ">= 1.9.0, < 2.0.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.9"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }

  # Local state on purpose: this config creates the remote backend, so it
  # cannot live in it. Keep terraform.tfstate in this folder (git-ignored).
}
