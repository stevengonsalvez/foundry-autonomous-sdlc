"""
What the activities are bound to: the tick's ports plus the factory definition.

`build_from_env()` builds the real adapters for the foreman worker:

    GITHUB_PAT_FILE   file holding the GitHub token (required)
    FACTORY_CONFIG    factory.yaml (default factory/factory.yaml)
    AGY_TOKEN_FILE    agy login token file (required by CliFoundry.from_env)
    CODER_URL         coder service (optional, CliFoundry.from_env)
    LEDGER_URL        ledger-api base URL (optional; no ledger events without it)

Tests bind the same dataclass to the in-memory fakes in agents/tests.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sdlc_agents.clock import SystemClock
from sdlc_agents.github import GitHubClient
from sdlc_agents.ledger.emitter import Emitter
from sdlc_agents.ports import Budget, ClockPort, FoundryPort, GitHubPort

from sdlc_factory.config import FactoryConfig, load_factory
from sdlc_factory.http_emitter import HttpEmitter

DEFAULT_FACTORY_CONFIG = "factory/factory.yaml"


@dataclass
class FactoryDeps:
    github: GitHubPort
    foundry: FoundryPort
    clock: ClockPort
    budget: Budget          # the caps; each step runs on a fresh copy (run_tick mutates its Budget)
    emitter: Emitter | None
    config: FactoryConfig
    sleep: Callable[[float], None] = time.sleep


def budget_from(config: FactoryConfig) -> Budget:
    """D7: the factory.yaml call caps priced at callUsd are the tick's USD caps."""
    return Budget(usd_cap_issue=config.budget.issue_cap_usd(), usd_cap_total=config.budget.total_cap_usd())


def _github_token() -> str:
    path = os.environ.get("GITHUB_PAT_FILE", "").strip()
    if not path:
        raise ValueError("GITHUB_PAT_FILE is not set: it must name the file holding the GitHub token")
    try:
        token = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError(f"GITHUB_PAT_FILE {path}: cannot read: {exc.strerror or exc}") from None
    if not token:
        raise ValueError(f"GITHUB_PAT_FILE {path} is empty")
    return token


def build_from_env() -> FactoryDeps:
    token = _github_token()
    config = load_factory(os.environ.get("FACTORY_CONFIG") or DEFAULT_FACTORY_CONFIG)
    from sdlc_factory.cli_foundry import CliFoundry  # lazy: tests and workflow code never need agy

    ledger_url = os.environ.get("LEDGER_URL", "").strip()
    return FactoryDeps(
        github=GitHubClient(token),
        foundry=CliFoundry.from_env(),
        clock=SystemClock(),
        budget=budget_from(config),
        emitter=HttpEmitter(ledger_url) if ledger_url else None,
        config=config,
    )
