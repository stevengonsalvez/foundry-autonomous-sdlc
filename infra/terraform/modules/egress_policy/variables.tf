variable "account_id" {
  type        = string
  description = "Foundry (AIServices) account resource ID the policy lives under."
}

variable "name" {
  type        = string
  default     = "sdlc-coder-egress"
  description = "Policy name (accounts/raiPolicies)."
}

variable "mode" {
  type        = string
  description = "Audit logs would-be denials and blocks nothing; Enforced refuses unlisted hosts with a proxy 403."

  validation {
    condition     = contains(["Audit", "Enforced"], var.mode)
    error_message = "mode must be Audit or Enforced."
  }
}

variable "allowed_hosts" {
  type        = list(string)
  description = "Exact host names the agent may reach (one Fqdn Allow rule each); everything else is denied."

  validation {
    condition     = length(var.allowed_hosts) > 0 && alltrue([for h in var.allowed_hosts : can(regex("^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$", h))])
    error_message = "allowed_hosts must be non-empty lowercase host names (no scheme, port, path or wildcard)."
  }
}
