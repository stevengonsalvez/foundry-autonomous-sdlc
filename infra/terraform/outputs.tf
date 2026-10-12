output "resource_group_name" {
  value       = azurerm_resource_group.demo.name
  description = "Single resource group holding everything billable."
}

output "foundry_account_name" {
  value       = module.foundry.account_name
  description = "Foundry (AIServices) account name."
}

output "foundry_project_endpoint" {
  value       = module.foundry.project_endpoint
  description = "Foundry project endpoint used by the deploy scripts as FOUNDRY_PROJECT_ENDPOINT."
}

output "foundry_project_endpoints" {
  value       = module.foundry.project_endpoints
  description = "Endpoint map exported by the provider (cross-check against foundry_project_endpoint)."
}

output "model_deployment_name" {
  value       = module.foundry.model_deployment_name
  description = "Deployment name agents should reference (MODEL_DEPLOYMENT_NAME for the agents)."
}

output "selected_model" {
  value       = module.foundry.selected_model
  description = "Model, version, SKU and TPM capacity actually deployed."
}

output "azure_tenant_id" {
  value       = data.azurerm_client_config.current.tenant_id
  description = "Entra tenant id."
}

output "azure_subscription_id" {
  value       = var.subscription_id
  description = "Subscription the stack lives in."
}

output "key_vault_name" {
  value       = module.keyvault.name
  description = "Key Vault that holds the GitHub token and the agy credentials."
}

output "key_vault_uri" {
  value       = module.keyvault.vault_uri
  description = "Vault URI the agents read secrets from."
}

output "foundry_project_principal_id" {
  value       = module.foundry.project_principal_id
  description = "Project managed identity object id."
}

output "application_insights_name" {
  value       = module.observability.application_insights_name
  description = "App Insights resource connected to the project for tracing."
}

output "egress_policy_id" {
  value       = try(module.egress_policy[0].policy_id, "off")
  description = "Egress guardrail attached to sdlc-coder (EGRESS_POLICY_ID for the deploy script); the explicit marker \"off\" when coder_egress_mode is Off, never an empty string."
}
