# TFLint config for the root, bootstrap/ and modules/.
# Run from infra/terraform (the absolute --config path is needed so every
# directory in --recursive mode uses this file):
#   tflint --init
#   tflint --recursive --config "$(pwd)/.tflint.hcl"
# Requires TFLint >= 0.54 (ruleset compatibility).

config {
  call_module_type = "local"
}

plugin "terraform" {
  enabled = true
  preset  = "recommended"
  version = "0.15.0"
  source  = "github.com/terraform-linters/tflint-ruleset-terraform"
}

plugin "azurerm" {
  enabled = true
  version = "0.32.0"
  source  = "github.com/terraform-linters/tflint-ruleset-azurerm"
}

rule "terraform_naming_convention" {
  enabled = true
}

rule "terraform_documented_variables" {
  enabled = true
}

rule "terraform_documented_outputs" {
  enabled = true
}

rule "terraform_standard_module_structure" {
  enabled = true
}

rule "terraform_unused_required_providers" {
  enabled = true
}
