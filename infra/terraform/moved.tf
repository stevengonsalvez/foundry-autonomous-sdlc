# One-off state moves from the flat root to modules/ (no resource is
# recreated). Delete this file once every state that predates the module
# layout has been planned and applied with it.

moved {
  from = azurerm_log_analytics_workspace.poc
  to   = module.observability.azurerm_log_analytics_workspace.poc
}

moved {
  from = azurerm_application_insights.poc
  to   = module.observability.azurerm_application_insights.poc
}

moved {
  from = azurerm_cognitive_account.foundry
  to   = module.foundry.azurerm_cognitive_account.foundry
}

moved {
  from = azurerm_cognitive_account_project.sdlc
  to   = module.foundry.azurerm_cognitive_account_project.sdlc
}

moved {
  from = azurerm_cognitive_deployment.default
  to   = module.foundry.azurerm_cognitive_deployment.default
}

moved {
  from = azapi_resource.appinsights_connection
  to   = module.foundry.azapi_resource.appinsights_connection
}

moved {
  from = azurerm_role_assignment.project_foundry_user
  to   = module.foundry.azurerm_role_assignment.project_foundry_user
}

moved {
  from = azurerm_role_assignment.project_metrics_publisher
  to   = module.foundry.azurerm_role_assignment.project_metrics_publisher
}

moved {
  from = azurerm_role_assignment.deployer_foundry_user
  to   = module.foundry.azurerm_role_assignment.deployer_foundry_user
}

moved {
  from = azurerm_user_assigned_identity.github
  to   = module.github_oidc.azurerm_user_assigned_identity.github
}

moved {
  from = azurerm_federated_identity_credential.github_branch
  to   = module.github_oidc.azurerm_federated_identity_credential.github_branch
}

moved {
  from = azurerm_federated_identity_credential.github_pull_request
  to   = module.github_oidc.azurerm_federated_identity_credential.github_pull_request
}

moved {
  from = azurerm_federated_identity_credential.github_environment
  to   = module.github_oidc.azurerm_federated_identity_credential.github_environment
}

# Renamed as well as moved: the role assigned is Foundry User, not Agent Consumer.
moved {
  from = azurerm_role_assignment.github_agent_consumer
  to   = module.github_oidc.azurerm_role_assignment.github_foundry_user
}

moved {
  from = azurerm_role_assignment.github_metrics_publisher
  to   = module.github_oidc.azurerm_role_assignment.github_metrics_publisher
}

moved {
  from = azurerm_consumption_budget_resource_group.poc
  to   = module.budget.azurerm_consumption_budget_resource_group.poc
}
