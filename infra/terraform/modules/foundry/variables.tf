variable "name" {
  type        = string
  description = "Name stem shared by the stack, for example \"fsdlc-poc\"."
}

variable "name_suffix" {
  type        = string
  description = "Random suffix that keeps the account name and custom subdomain globally unique."

  validation {
    condition     = can(regex("^[a-z0-9]{3,8}$", var.name_suffix))
    error_message = "name_suffix must be 3 to 8 lowercase letters or digits."
  }
}

variable "subscription_id" {
  type        = string
  description = "Subscription that holds the account; used for role definition IDs and the quota lookup."

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be a GUID."
  }
}

variable "resource_group_name" {
  type        = string
  description = "Resource group that holds the Foundry account."
}

variable "location" {
  type        = string
  description = "Azure region for the account, project and quota lookup."
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Tags applied to every taggable resource."
}

variable "local_auth_enabled" {
  type        = bool
  default     = false
  description = "API keys on the Foundry account. False = Entra ID only (keyless)."
}

variable "model_candidates" {
  type = list(object({
    name     = string
    version  = string
    sku_name = string
    capacity = number # thousands of tokens per minute (1 = 1,000 TPM)
  }))
  description = "Ordered model preference list used by model_selection."

  validation {
    condition     = length(var.model_candidates) > 0
    error_message = "model_candidates must contain at least one model."
  }

  validation {
    condition     = alltrue([for m in var.model_candidates : m.capacity >= 1 && m.capacity <= 100])
    error_message = "Keep capacity between 1 and 100 (1k to 100k TPM). The TPM cap is a spend brake; the agents also enforce per-issue and total cost caps."
  }
}

variable "model_selection" {
  type        = string
  description = "A candidate name to pin that model, or \"auto\" to pick the first candidate whose regional quota limit covers its capacity. \"auto\" fails the plan if the quota lookup fails."

  validation {
    condition     = var.model_selection == "auto" || contains([for m in var.model_candidates : m.name], var.model_selection)
    error_message = "model_selection must be \"auto\" or one of the model_candidates names."
  }
}

variable "model_deployment_name" {
  type        = string
  description = "Stable deployment name that agents reference, independent of which model was selected."

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$", var.model_deployment_name))
    error_message = "model_deployment_name must be 2 to 64 letters, digits, '.', '_' or '-', starting with a letter or digit."
  }
}

variable "application_insights_id" {
  type        = string
  description = "App Insights resource the project traces into; also the scope of the project's Monitoring Metrics Publisher role."
}

variable "application_insights_connection_string" {
  type        = string
  sensitive   = true
  description = "App Insights connection string stored on the project tracing connection."
}

variable "assign_deployer_role" {
  type        = bool
  default     = false
  description = "Grant deployer_principal_id Foundry User on the account so it can create agents from a laptop."
}

variable "deployer_principal_id" {
  type        = string
  default     = null
  description = "Object ID of the principal running Terraform. Required when assign_deployer_role is true."

  validation {
    condition     = !var.assign_deployer_role || var.deployer_principal_id != null
    error_message = "deployer_principal_id is required when assign_deployer_role is true."
  }
}
