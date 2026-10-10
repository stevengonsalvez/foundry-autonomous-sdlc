variable "name" {
  type        = string
  description = "Budget name."
}

variable "resource_group_id" {
  type        = string
  description = "Resource group the budget tracks."
}

variable "amount" {
  type        = number
  description = "Monthly budget in the billing currency."

  validation {
    condition     = var.amount > 0
    error_message = "amount must be greater than 0."
  }
}

variable "alert_thresholds" {
  type        = list(number)
  description = "Actual-cost alert thresholds as percent of amount. A 100% forecast alert is always added."

  validation {
    condition     = length(var.alert_thresholds) <= 4 && alltrue([for t in var.alert_thresholds : t > 0 && t <= 1000])
    error_message = "Use at most 4 thresholds (Azure allows 5 notifications including the forecast one), each between 0 and 1000 percent."
  }
}

variable "contact_emails" {
  type        = list(string)
  default     = []
  description = "Extra alert recipients. Subscription Owners are always notified via contact_roles."

  validation {
    condition     = alltrue([for e in var.contact_emails : can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", e))])
    error_message = "contact_emails must be email addresses."
  }
}
