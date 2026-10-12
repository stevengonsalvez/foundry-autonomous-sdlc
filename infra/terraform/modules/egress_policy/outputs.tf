output "policy_id" {
  value       = azapi_resource.this.id
  description = "Full ARM ID of the policy; hosted agent versions reference it in rai_config."
}
