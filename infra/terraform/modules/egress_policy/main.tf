# Hosted-agent egress guardrail: an account RAI policy whose egressPolicy is a
# default-deny allow-list. Preview (api 2026-05-15-preview, no SLA). The policy
# binds to an agent version (rai_config), so a change takes effect only for new
# versions and new sessions. Platform connectivity (identity, telemetry) is
# allowed by the service separately and needs no rule here.

locals {
  # The content filters are Microsoft.Default's (Medium, blocking): this policy
  # changes egress only, not content safety.
  content_filters = flatten([
    for category in ["Hate", "Sexual", "Violence", "Selfharm"] : [
      for source in ["Prompt", "Completion"] : {
        name              = category
        source            = source
        severityThreshold = "Medium"
        blocking          = true
        enabled           = true
      }
    ]
  ])
}

resource "azapi_resource" "this" {
  type                      = "Microsoft.CognitiveServices/accounts/raiPolicies@2026-05-15-preview"
  name                      = var.name
  parent_id                 = var.account_id
  schema_validation_enabled = false # the preview egressPolicy is not in the provider schema yet

  body = {
    properties = {
      basePolicyName = "Microsoft.Default"
      mode           = "Blocking"
      contentFilters = local.content_filters
      egressPolicy = {
        description   = "sdlc-coder allow-list (docs/architecture.md, Egress)"
        mode          = var.mode
        defaultAction = "Deny"
        rules = [
          for host in var.allowed_hosts : {
            name     = substr(replace(host, ".", "-"), 0, 64)
            ruleType = "Fqdn"
            match    = { host = host }
            action   = { actionType = "Allow" }
          }
        ]
      }
    }
  }

  response_export_values = ["properties.egressPolicy.mode"]
}
