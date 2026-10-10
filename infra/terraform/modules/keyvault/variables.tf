variable "name" {
  type        = string
  description = "Name stem shared by the stack, for example \"fsdlcd-demo\"."
}

variable "name_suffix" {
  type        = string
  description = "Random suffix that keeps the vault name globally unique."

  validation {
    condition     = can(regex("^[a-z0-9]{3,8}$", var.name_suffix))
    error_message = "name_suffix must be 3 to 8 lowercase letters or digits."
  }
}

variable "resource_group_name" {
  type        = string
  description = "Resource group that holds the vault."
}

variable "location" {
  type        = string
  description = "Azure region."
}

variable "tenant_id" {
  type        = string
  description = "Entra tenant that owns the vault."
}

variable "secrets_officer_principal_id" {
  type        = string
  description = "Principal that loads secrets (the operator running Terraform). Gets Key Vault Secrets Officer."
}

variable "secrets_reader_principal_ids" {
  type        = map(string)
  default     = {}
  description = "Named principals that only read secrets (for example the Foundry project identity). Map keys must be known at plan time."
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Tags applied to every resource."
}
