output "log_analytics_workspace_id" {
  value       = azurerm_log_analytics_workspace.poc.id
  description = "Log Analytics workspace resource ID."
}

output "application_insights_id" {
  value       = azurerm_application_insights.poc.id
  description = "App Insights resource ID (role assignment scope and tracing target)."
}

output "application_insights_name" {
  value       = azurerm_application_insights.poc.name
  description = "App Insights component name."
}

output "application_insights_connection_string" {
  value       = azurerm_application_insights.poc.connection_string
  sensitive   = true
  description = "Connection string for the Foundry tracing connection. Ingestion still needs an Entra token because local auth is off."
}
