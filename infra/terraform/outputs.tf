output "resource_group_name" {
  value       = azurerm_resource_group.poc.name
  description = "Single resource group holding everything billable."
}

output "foundry_account_name" {
  value       = module.foundry.account_name
  description = "Foundry (AIServices) account name."
}

output "foundry_project_endpoint" {
  value       = module.foundry.project_endpoint
  description = "Set as GitHub variable FOUNDRY_PROJECT_ENDPOINT."
}

output "foundry_project_endpoints" {
  value       = module.foundry.project_endpoints
  description = "Endpoint map exported by the provider (cross-check against foundry_project_endpoint)."
}

output "model_deployment_name" {
  value       = module.foundry.model_deployment_name
  description = "Deployment name agents should reference (GitHub variable MODEL_DEPLOYMENT_NAME)."
}

output "selected_model" {
  value       = module.foundry.selected_model
  description = "Model, version, SKU and TPM capacity actually deployed."
}

output "azure_client_id" {
  value       = module.github_oidc.client_id
  description = "GitHub variable AZURE_CLIENT_ID for azure/login (not a secret)."
}

output "azure_tenant_id" {
  value       = module.github_oidc.tenant_id
  description = "GitHub variable AZURE_TENANT_ID."
}

output "azure_subscription_id" {
  value       = var.subscription_id
  description = "GitHub variable AZURE_SUBSCRIPTION_ID."
}

output "github_oidc_subjects" {
  value       = module.github_oidc.oidc_subjects
  description = "Subjects trusted by the GitHub identity. Must match the token sub claim exactly."
}

output "application_insights_name" {
  value       = module.observability.application_insights_name
  description = "App Insights resource connected to the project for tracing."
}
