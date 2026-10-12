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
  description = "Audit blocks nothing and its decisions are not yet observable; Enforced refuses unlisted hosts with a proxy 403 and denies all plain HTTP, even to listed hosts."

  validation {
    condition     = contains(["Audit", "Enforced"], var.mode)
    error_message = "mode must be Audit or Enforced."
  }
}

variable "allowed_hosts" {
  type        = list(string)
  description = "Exact host names the agent may reach (one Fqdn Allow rule each); everything else is denied."

  validation {
    # Dotted labels of letters, digits and inner dashes; the last label starts with a letter, so IP literals
    # (1.2.3.4) and "a..b" are rejected, as are schemes, ports, paths and wildcards.
    condition = (
      length(var.allowed_hosts) > 0 && length(var.allowed_hosts) <= 100 &&
      alltrue([for h in var.allowed_hosts : length(h) <= 253 && can(regex("^([a-z0-9]([a-z0-9-]*[a-z0-9])?[.])+[a-z]([a-z0-9-]*[a-z0-9])?$", h))])
    )
    error_message = "allowed_hosts must be non-empty lowercase DNS names (no IP literal, empty label, scheme, port, path or wildcard)."
  }
}
