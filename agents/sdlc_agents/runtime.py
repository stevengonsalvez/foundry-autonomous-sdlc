"""
Wiring for the hosted orchestrator: environment to adapters to one tick.

Env:
    FOUNDRY_PROJECT_ENDPOINT  injected by the platform in hosted containers
    KEY_VAULT_URI             https://<vault>.vault.azure.net (holds the `github-pat` secret); set by
                              scripts/deploy_agents.py
    TICK_BUDGET_S             optional wall budget in seconds (default 240)
    LEDGER_MODE               hosted (events go to the sdlc-ledger agent), inline (the same ledger runs in this
                              process, the fallback) or off (default)

The agent authenticates with its own managed identity (DefaultAzureCredential); the PAT is read
from Key Vault on every invocation and never leaves the GitHub adapter.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sdlc_agents.clock import SystemClock
from sdlc_agents.foundry import FoundryClient
from sdlc_agents.github import GitHubClient
from sdlc_agents.keyvault import KeyVaultSecrets
from sdlc_agents.ledger.emitter import Emitter, HostedEmitter, InlineEmitter, NullEmitter
from sdlc_agents.ledger.service import Ledger
from sdlc_agents.ledger.store import GitHubBranchStore
from sdlc_agents.tick import run_tick

GITHUB_SECRET = "github-pat"  # noqa: S105 (the secret's name in Key Vault, not a value)
DEFAULT_BUDGET_S = 240


class ConfigError(RuntimeError):
    pass


def _default_credential() -> Any:
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential()


def run_once(env: Mapping[str, str], *, credential_factory: Callable[[], Any] = _default_credential) -> dict[str, Any]:
    """Build the adapters from `env`, run one tick and return its report as a dict."""
    endpoint = env.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    vault = env.get("KEY_VAULT_URI", "").strip()
    missing = [n for n, v in (("FOUNDRY_PROJECT_ENDPOINT", endpoint), ("KEY_VAULT_URI", vault)) if not v]
    if missing:
        raise ConfigError(f"missing environment: {', '.join(missing)}")
    try:
        budget_s = int(env.get("TICK_BUDGET_S", DEFAULT_BUDGET_S))
    except ValueError as exc:
        raise ConfigError("TICK_BUDGET_S must be an integer") from exc
    credential = credential_factory()
    secrets = KeyVaultSecrets(vault, credential)
    github = GitHubClient(secrets.get_secret(GITHUB_SECRET))
    foundry = FoundryClient(endpoint, credential)
    emitter = ledger_emitter(env.get("LEDGER_MODE", "off"), github, foundry)
    return run_tick(github, foundry, secrets, SystemClock(), budget_wall_s=budget_s, emitter=emitter).to_dict()


def ledger_emitter(mode: str, github: GitHubClient, foundry: FoundryClient) -> Emitter:
    """How this tick reaches the state-keeper: the hosted agent, the same code inline, or not at all."""
    mode = mode.strip().lower()
    if mode == "hosted":
        return HostedEmitter(foundry)
    if mode == "inline":
        return InlineEmitter(Ledger(GitHubBranchStore(github), SystemClock(), github=github, mode="inline"))
    if mode in ("", "off"):
        return NullEmitter()
    raise ConfigError(f"LEDGER_MODE must be hosted, inline or off, not {mode!r}")
