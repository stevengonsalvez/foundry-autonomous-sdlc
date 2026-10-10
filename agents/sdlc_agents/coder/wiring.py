"""
Composition root for the hosted coder: real adapters behind the runner's ports.

Environment (set by scripts/deploy_agents.py, FOUNDRY_PROJECT_ENDPOINT injected by the platform):
KEY_VAULT_URI, FOUNDRY_PROJECT_ENDPOINT, FOUNDRY_MODEL_DEPLOYMENT (default sdlc-default).
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sdlc_agents.clock import SystemClock
from sdlc_agents.coder import sandbox
from sdlc_agents.coder.engines import AgyEngine, ModelLoopEngine, ResponsesClient
from sdlc_agents.coder.git_adapter import SubprocessGit
from sdlc_agents.coder.job import JobStore, Redactor
from sdlc_agents.coder.runner import CoderDeps, CoderService, EngineContext
from sdlc_agents.coder.toolchain import NODE_DIR, Toolchain
from sdlc_agents.cost import HOSTED_GIB_USD_PER_HOUR, HOSTED_VCPU_USD_PER_HOUR
from sdlc_agents.github import GitHubClient
from sdlc_agents.keyvault import KeyVaultSecrets
from sdlc_agents.ports import OWNER, CodingEnginePort
from sdlc_agents.transport import HttpRequest, Transport, urllib_transport

AI_SCOPE = "https://ai.azure.com/.default"
DEFAULT_DEPLOYMENT = "sdlc-default"


def owner_user_id(pat: str, *, transport: Transport = urllib_transport) -> int | None:
    """The repo owner's numeric GitHub id, for the noreply commit address. None on any failure."""
    try:
        resp = transport(HttpRequest("GET", f"https://api.github.com/users/{OWNER}",
                                     {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"}))
        value = json.loads(resp.body).get("id") if resp.status == 200 else None
    except (OSError, ValueError, AttributeError):
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def compute_usd_per_hour(env: Mapping[str, str]) -> float:
    """Hosted list price for this agent's size (HOSTED_CPU, HOSTED_MEMORY such as "4Gi", set at deploy)."""
    try:
        cpu = float(env.get("HOSTED_CPU", "0"))
        gib = float(env.get("HOSTED_MEMORY", "0Gi").removesuffix("Gi"))
    except ValueError:
        return 0.0
    return cpu * HOSTED_VCPU_USD_PER_HOUR + gib * HOSTED_GIB_USD_PER_HOUR


def build_service(env: Mapping[str, str] = os.environ, *, credential: Any = None) -> CoderService:
    home = Path(env.get("HOME") or Path.home())
    if credential is None:
        from azure.identity import DefaultAzureCredential  # deferred: heavy import, absent in unit tests

        credential = DefaultAzureCredential()
    deployment = env.get("FOUNDRY_MODEL_DEPLOYMENT", DEFAULT_DEPLOYMENT)
    responses = ResponsesClient(env["FOUNDRY_PROJECT_ENDPOINT"], deployment,
                                token_provider=lambda: credential.get_token(AI_SCOPE).token)

    def engines(ctx: EngineContext) -> list[CodingEnginePort]:
        chain: list[CodingEnginePort] = []
        if ctx.agy_binary is not None:
            run_as = ctx.run_as
            prepare = (lambda checkout: sandbox.give_tree(checkout, run_as)) if run_as is not None else None
            agy = {"home": ctx.agy_home, "run_as": run_as, "cancel": ctx.cancel, "prepare": prepare,
                   "dirty": ctx.dirty, "before_call": ctx.refresh_agy_settings, "log_dir": ctx.agy_log_dir,
                   "round_no": ctx.round_no}
            chain.append(AgyEngine(ctx.agy_binary, **agy))
            if run_as is not None and run_as.uid != 0:
                chain.append(AgyEngine(ctx.agy_binary, unrestricted=True, **agy))
        chain.append(ModelLoopEngine(responses, allowed_paths=ctx.spec.allowed_paths, protected=ctx.protected,
                                     tests_only=ctx.tests_only, failing=ctx.failing, workdir=ctx.spec.workdir))
        return chain

    deps = CoderDeps(
        home=home,
        secrets=KeyVaultSecrets(env["KEY_VAULT_URI"], credential),
        github=GitHubClient,
        git=lambda author, cancel: SubprocessGit(author=author, cancel=cancel),
        engines=engines,
        toolchain=Toolchain(home, node_dir=NODE_DIR),
        clock=SystemClock(),
        owner_user_id=owner_user_id,
        engine_user=sandbox.ensure_agy_user,
        compute_usd_per_hour=compute_usd_per_hour(env),
    )
    return CoderService(JobStore(home / "jobs", Redactor(env=env)), deps)
