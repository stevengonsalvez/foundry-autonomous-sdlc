output "client_id" {
  value       = azurerm_user_assigned_identity.github.client_id
  description = "Client ID for azure/login (not a secret)."
}

output "tenant_id" {
  value       = azurerm_user_assigned_identity.github.tenant_id
  description = "Tenant ID of the managed identity."
}

output "principal_id" {
  value       = azurerm_user_assigned_identity.github.principal_id
  description = "Object ID of the managed identity."
}

output "oidc_subjects" {
  value = tolist(concat(
    [azurerm_federated_identity_credential.github_branch.subject],
    azurerm_federated_identity_credential.github_pull_request[*].subject,
    azurerm_federated_identity_credential.github_environment[*].subject,
  ))
  description = "Subjects trusted by the identity. Must match the token sub claim exactly."
}
