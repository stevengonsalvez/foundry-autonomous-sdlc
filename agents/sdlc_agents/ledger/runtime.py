"""
Wiring for the hosted ledger: environment to adapters to one Ledger.

Env:
    FOUNDRY_PROJECT_ENDPOINT   injected by the platform (model summaries on the project deployment)
    KEY_VAULT_URI              vault holding `github-pat`; the ledger writes only branch `state` with it
    FOUNDRY_MODEL_DEPLOYMENT   deployment for summaries (default sdlc-default)
    AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP   enable the billed-spend read (needs Cost Management Reader)
    LEDGER_SUMMARIES           `off` turns the model summaries off (default on)

The agent authenticates with its own managed identity. Stdlib plus azure-identity (already pinned).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sdlc_agents.clock import SystemClock
from sdlc_agents.github import GitHubClient
from sdlc_agents.keyvault import KeyVaultSecrets
from sdlc_agents.ledger.billing import AzureBilling
from sdlc_agents.ledger.service import Ledger
from sdlc_agents.ledger.store import GitHubBranchStore
from sdlc_agents.ledger.summary import ModelSummariser
from sdlc_agents.runtime import GITHUB_SECRET, ConfigError, _default_credential

AI_SCOPE = "https://ai.azure.com/.default"
DEFAULT_DEPLOYMENT = "sdlc-default"


def build_ledger(env: Mapping[str, str], *, credential_factory: Callable[[], Any] = _default_credential) -> Ledger:
    endpoint = env.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    vault = env.get("KEY_VAULT_URI", "").strip()
    missing = [n for n, v in (("FOUNDRY_PROJECT_ENDPOINT", endpoint), ("KEY_VAULT_URI", vault)) if not v]
    if missing:
        raise ConfigError(f"missing environment: {', '.join(missing)}")
    credential = credential_factory()
    github = GitHubClient(KeyVaultSecrets(vault, credential).get_secret(GITHUB_SECRET))
    subscription, group = env.get("AZURE_SUBSCRIPTION_ID", "").strip(), env.get("AZURE_RESOURCE_GROUP", "").strip()
    billing = AzureBilling(credential, subscription, group) if subscription and group else None
    summariser = None
    if env.get("LEDGER_SUMMARIES", "on").lower() != "off":
        summariser = ModelSummariser(
            endpoint,
            env.get("FOUNDRY_MODEL_DEPLOYMENT", DEFAULT_DEPLOYMENT),
            token_provider=lambda: credential.get_token(AI_SCOPE).token,
        )
    return Ledger(
        GitHubBranchStore(github), SystemClock(), github=github, billing=billing, summariser=summariser, mode="hosted"
    )
