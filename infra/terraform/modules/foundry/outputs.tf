output "account_id" {
  value       = azurerm_cognitive_account.foundry.id
  description = "Foundry (AIServices) account resource ID."
}

output "account_name" {
  value       = azurerm_cognitive_account.foundry.name
  description = "Foundry (AIServices) account name."
}

output "project_id" {
  value       = azurerm_cognitive_account_project.sdlc.id
  description = "Foundry project resource ID (scope for the CI identity's role)."
}

output "project_endpoint" {
  # Documented format: https://<resource-name>.services.ai.azure.com/api/projects/<project-name>
  value       = "https://${azurerm_cognitive_account.foundry.custom_subdomain_name}.services.ai.azure.com/api/projects/${azurerm_cognitive_account_project.sdlc.name}"
  description = "Foundry project endpoint."
}

output "project_endpoints" {
  value       = azurerm_cognitive_account_project.sdlc.endpoints
  description = "Endpoint map exported by the provider (cross-check against project_endpoint)."
}

output "model_deployment_name" {
  value       = azurerm_cognitive_deployment.default.name
  description = "Deployment name agents should reference."
}

output "selected_model" {
  value       = local.selected_model
  description = "Model, version, SKU and TPM capacity actually deployed."
}
