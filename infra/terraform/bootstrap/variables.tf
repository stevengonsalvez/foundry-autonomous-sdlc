variable "subscription_id" {
  type        = string
  description = "Subscription that holds the state account (same as the stack)."

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be a GUID."
  }
}

variable "location" {
  type        = string
  default     = "uksouth"
  description = "Azure region for the state resource group and storage account."
}

variable "name_prefix" {
  type        = string
  default     = "fsdlc"
  description = "Short prefix for resource names. A random suffix keeps the storage account name globally unique."

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{2,10}$", var.name_prefix))
    error_message = "name_prefix must be 3 to 11 lowercase letters or digits, starting with a letter."
  }
}

variable "container_name" {
  type        = string
  default     = "tfstate"
  description = "Blob container that holds the state files."

  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9]|-[a-z0-9]){2,62}$", var.container_name))
    error_message = "container_name must be 3 to 63 lowercase letters, digits or single hyphens."
  }
}

variable "allowed_ip_ranges" {
  type        = list(string)
  description = "Public IPv4 addresses or CIDR ranges allowed through the storage firewall (the operator's egress IP, e.g. from `curl -s https://ifconfig.me`). Everything else is denied."

  validation {
    condition = length(var.allowed_ip_ranges) > 0 && alltrue([
      for r in var.allowed_ip_ranges :
      !strcontains(r, ":") &&
      can(cidrhost(strcontains(r, "/") ? r : "${r}/32", 0)) &&
      !endswith(r, "/31") &&
      !can(regex("^(10\\.|192\\.168\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.)", r))
    ])
    error_message = "allowed_ip_ranges must hold at least one public IPv4 address or CIDR range (no IPv6, no RFC1918 ranges, no /31; Azure Storage rejects them). Use `curl -4 -s https://ifconfig.me`."
  }
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Extra tags merged onto every resource."
}
