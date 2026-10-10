variable "name" {
  type        = string
  description = "Name stem shared by the stack, for example \"fsdlc-poc\"."
}

variable "subscription_id" {
  type        = string
  description = "Subscription used to build built-in role definition IDs."

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be a GUID."
  }
}

variable "resource_group_name" {
  type        = string
  description = "Resource group that holds the managed identity."
}

variable "location" {
  type        = string
  description = "Azure region for the managed identity."
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Tags applied to the managed identity."
}

variable "github_owner" {
  type        = string
  description = "GitHub user or org that owns the repository."

  validation {
    condition     = can(regex("^[A-Za-z0-9](?:[A-Za-z0-9_-]{0,38})$", var.github_owner))
    error_message = "github_owner must be a valid GitHub user or org name."
  }
}

variable "github_repo" {
  type        = string
  description = "Repository name (without owner)."

  validation {
    condition     = can(regex("^[A-Za-z0-9._-]{1,100}$", var.github_repo))
    error_message = "github_repo must be a valid GitHub repository name."
  }
}

variable "github_owner_id" {
  type        = number
  default     = null
  description = "Numeric owner id, for immutable OIDC subjects. Set together with github_repo_id."
}

variable "github_repo_id" {
  type        = number
  default     = null
  description = "Numeric repository id, for immutable OIDC subjects. Set together with github_owner_id."

  validation {
    condition     = (var.github_repo_id == null) == (var.github_owner_id == null)
    error_message = "Set both github_owner_id and github_repo_id (immutable subjects) or neither (legacy name-based subjects)."
  }
}

variable "github_default_branch" {
  type        = string
  description = "Branch whose workflows may log in to Azure."

  validation {
    condition     = length(var.github_default_branch) > 0 && !strcontains(var.github_default_branch, ":")
    error_message = "github_default_branch must be non-empty and must not contain ':'."
  }
}

variable "allow_pull_request" {
  type        = bool
  description = "Create the pull_request federated credential. It is a recorded security gap: any same-repo PR author can obtain a token."
}

variable "github_environment" {
  type        = string
  default     = null
  description = "Optional GitHub environment name. When a job declares an environment, the OIDC subject becomes environment:<name>."

  validation {
    condition     = var.github_environment == null ? true : length(var.github_environment) > 0
    error_message = "github_environment must be null or a non-empty name."
  }
}

variable "foundry_project_id" {
  type        = string
  description = "Foundry project resource ID; the only scope where the identity gets Foundry User."
}

variable "application_insights_id" {
  type        = string
  description = "App Insights resource ID; scope of the identity's Monitoring Metrics Publisher role."
}
