# Workspace-based Application Insights with a capped daily ingestion.

resource "azurerm_log_analytics_workspace" "poc" {
  name                = "log-${var.name}-${var.name_suffix}"
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = "PerGB2018"
  retention_in_days   = var.retention_in_days
  daily_quota_gb      = var.daily_quota_gb
  tags                = var.tags
}

resource "azurerm_application_insights" "poc" {
  name                = "appi-${var.name}-${var.name_suffix}"
  location            = var.location
  resource_group_name = var.resource_group_name
  workspace_id        = azurerm_log_analytics_workspace.poc.id
  application_type    = "other"

  # Keyless ingestion: telemetry must be sent with an Entra token
  # (Monitoring Metrics Publisher), not the instrumentation key alone.
  local_authentication_enabled = false
  daily_data_cap_in_gb         = var.daily_quota_gb

  tags = var.tags
}
