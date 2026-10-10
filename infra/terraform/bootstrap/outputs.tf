output "resource_group_name" {
  value       = azurerm_resource_group.tfstate.name
  description = "Resource group holding the state account."
}

output "storage_account_name" {
  value       = azurerm_storage_account.tfstate.name
  description = "State storage account name."
}

output "container_name" {
  value       = azurerm_storage_container.tfstate.name
  description = "State container name."
}

output "backend_hcl" {
  value       = <<-EOT
    resource_group_name  = "${azurerm_resource_group.tfstate.name}"
    storage_account_name = "${azurerm_storage_account.tfstate.name}"
    container_name       = "${azurerm_storage_container.tfstate.name}"
    key                  = "foundry-sdlc-poc.tfstate"
    subscription_id      = "${var.subscription_id}"
    tenant_id            = "${data.azurerm_client_config.current.tenant_id}"
    use_azuread_auth     = true
  EOT
  description = "Paste-ready contents for ../backend.hcl (no secrets: Entra ID auth only)."
}
