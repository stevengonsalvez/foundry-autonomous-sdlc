# Hosted-agent egress guardrail: an account RAI policy whose egressPolicy is a
# default-deny allow-list. Preview (api 2026-05-15-preview, no SLA). The policy
# binds to an agent version (rai_config), so a change takes effect only for new
# versions and new sessions. Measured under Enforced: the managed identity
# token and the model call work with no rule beyond the two Azure hosts listed
# in the root module. Telemetry and Application Insights ingestion under
# Enforced is NOT measured: do not assume it needs no rule.

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
        # Index prefix: truncated or dash-mapped host names cannot collide.
        rules = [
          for i, host in var.allowed_hosts : {
            name     = format("allow-%02d-%s", i, trimsuffix(substr(replace(host, ".", "-"), 0, 55), "-"))
            ruleType = "Fqdn"
            match    = { host = host }
            action   = { actionType = "Allow" }
          }
        ]
      }
    }
  }
}
