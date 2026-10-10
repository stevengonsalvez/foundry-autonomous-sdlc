# Resource-group budget. Alerts only: budgets notify, they do not stop spend.

resource "azurerm_consumption_budget_resource_group" "poc" {
  name              = var.name
  resource_group_id = var.resource_group_id
  amount            = var.amount
  time_grain        = "Monthly"

  time_period {
    # Must be the first of a month. Computed once, then frozen.
    start_date = formatdate("YYYY-MM-'01T00:00:00Z'", timestamp())
  }

  dynamic "notification" {
    for_each = var.alert_thresholds
    content {
      enabled        = true
      threshold      = notification.value
      operator       = "GreaterThanOrEqualTo"
      threshold_type = "Actual"
      contact_roles  = ["Owner"]
      contact_emails = var.contact_emails
    }
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThanOrEqualTo"
    threshold_type = "Forecasted"
    contact_roles  = ["Owner"]
    contact_emails = var.contact_emails
  }

  lifecycle {
    ignore_changes = [time_period[0].start_date]
  }
}
