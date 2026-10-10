variable "name" {
  type        = string
  description = "Name stem shared by the stack, for example \"fsdlc-poc\"."
}

variable "name_suffix" {
  type        = string
  description = "Random suffix that keeps workspace and component names unique."

  validation {
    condition     = can(regex("^[a-z0-9]{3,8}$", var.name_suffix))
    error_message = "name_suffix must be 3 to 8 lowercase letters or digits."
  }
}

variable "resource_group_name" {
  type        = string
  description = "Resource group that holds the workspace and App Insights."
}

variable "location" {
  type        = string
  description = "Azure region."
}

variable "daily_quota_gb" {
  type        = number
  description = "Daily ingestion cap applied to both Log Analytics and App Insights."

  validation {
    condition     = var.daily_quota_gb > 0 && var.daily_quota_gb <= 5
    error_message = "daily_quota_gb must be greater than 0 and at most 5 (the PoC spend brake)."
  }
}

variable "retention_in_days" {
  type        = number
  default     = 30
  description = "Log Analytics retention. 30 days is included in the ingestion price."

  validation {
    condition     = var.retention_in_days >= 30 && var.retention_in_days <= 730
    error_message = "retention_in_days must be between 30 and 730."
  }
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Tags applied to every resource."
}
