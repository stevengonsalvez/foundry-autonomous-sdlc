"""
Composition root for the coder outside Foundry (the compose `coder` worker): no Key Vault, no
managed identity, no model loop. The job logic (CoderService, JobRunner) is the hosted one, unchanged.

Differences from wiring.py, on purpose:
- Secrets are files (compose secrets), read on every use so a rotated token is picked up:
  GITHUB_PAT_FILE (default /run/secrets/github_pat), AGY_TOKEN_FILE (default /run/secrets/agy_cli_token).
- The engine chain is agy (allow-list, one round), then agy-unrestricted (engine user only). The Foundry
  model loop is dropped: when both agy engines give up the job ends `engines-exhausted`.
- STATE_DIR (default $HOME/jobs) holds job state; put it on a volume so a restarted container marks
  every job it finds running as `interrupted` (CoderService does that on construction).
- WORKROOT (default /srv/sdlc-work) holds the checkouts.
- HTTPS_PROXY, HTTP_PROXY, NO_PROXY (either case) and SSL_CERT_FILE, when set, are added to agy's
  environment, which is otherwise built from nothing.
- Hosted compute is not priced (compute_usd_per_hour 0).

The unprivileged engine user is unchanged: `agyuser`, created when the process is root; without it the
job fails closed with `sandbox-unavailable` and nothing untrusted runs.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sdlc_agents.clock import SystemClock
from sdlc_agents.coder import sandbox, shell
from sdlc_agents.coder.engines import AgyEngine
from sdlc_agents.coder.git_adapter import SubprocessGit
from sdlc_agents.coder.job import JobStore, Redactor
from sdlc_agents.coder.runner import CoderDeps, CoderService, EngineContext
from sdlc_agents.coder.toolchain import NODE_DIR, Toolchain
from sdlc_agents.coder.wiring import owner_user_id
from sdlc_agents.github import GitHubClient
from sdlc_agents.ports import REPO, CodingEnginePort, CommandResult, GitHubPort

DEFAULT_SECRET_FILES = {"github-pat": ("GITHUB_PAT_FILE", "/run/secrets/github_pat"),
                        "agy-cli-token": ("AGY_TOKEN_FILE", "/run/secrets/agy_cli_token")}
AGY_EXTRA_ENV = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "NO_PROXY", "no_proxy",
                 "SSL_CERT_FILE")
MAX_SECRET_BYTES = 64 * 1024

Runner = Callable[..., CommandResult]


class SecretError(RuntimeError):
    """A secret could not be read. The message names the secret and its file, never its content."""


class FileSecrets:
    """SecretsPort over files. Reads on every call: compose secrets can be rotated without a rebuild."""

    def __init__(self, paths: Mapping[str, Path]):
        self._paths = dict(paths)

    def get_secret(self, name: str) -> str:
        path = self._paths.get(name)
        if path is None:
            raise SecretError(f"unknown secret {name!r}")
        try:
            with path.open("rb") as handle:
                data = handle.read(MAX_SECRET_BYTES + 1)
        except OSError as exc:
            raise SecretError(f"cannot read secret {name} from {path}: {type(exc).__name__}") from None
        try:
            value = data.decode("utf-8").strip() if len(data) <= MAX_SECRET_BYTES else ""
        except UnicodeDecodeError:
            raise SecretError(f"secret {name} in {path} is not UTF-8 text") from None
        if not value:
            raise SecretError(f"secret {name} in {path} is empty or larger than {MAX_SECRET_BYTES} bytes")
        return value


def secret_paths(env: Mapping[str, str]) -> dict[str, Path]:
    return {name: Path(env.get(var) or default) for name, (var, default) in DEFAULT_SECRET_FILES.items()}


def agy_extra_env(env: Mapping[str, str]) -> dict[str, str]:
    return {key: env[key] for key in AGY_EXTRA_ENV if env.get(key)}


def agy_chain(ctx: EngineContext, extra_env: Mapping[str, str], *, run: Runner = shell.run) -> list[CodingEnginePort]:
    """wiring.build_service's agy engines, same arguments, minus the model loop."""
    if ctx.agy_binary is None:
        return []
    extra = dict(extra_env)

    def run_with_extra(cmd: list[str], **kw: Any) -> CommandResult:
        return run(cmd, **{**kw, "env": {**kw.get("env", {}), **extra}})

    run_as = ctx.run_as
    prepare = (lambda checkout: sandbox.give_tree(checkout, run_as)) if run_as is not None else None
    agy: dict[str, Any] = {"home": ctx.agy_home, "run_as": run_as, "cancel": ctx.cancel, "prepare": prepare,
                           "dirty": ctx.dirty, "before_call": ctx.refresh_agy_settings, "log_dir": ctx.agy_log_dir,
                           "round_no": ctx.round_no, "run": run_with_extra}
    chain: list[CodingEnginePort] = [AgyEngine(ctx.agy_binary, **agy)]
    if run_as is not None and run_as.uid != 0:
        chain.append(AgyEngine(ctx.agy_binary, unrestricted=True, **agy))
    return chain


def build_local_service(env: Mapping[str, str] = os.environ, *, repo: str = REPO,
                        github: Callable[[str], GitHubPort] = GitHubClient) -> CoderService:
    """`repo` must be the coder's repo: JobSpec refuses any other, so a mismatch is a config error now."""
    if repo != REPO:
        raise ValueError(f"the coder only works on {REPO}, configured repo is {repo}")
    home = Path(env.get("HOME") or Path.home())
    state_dir = Path(env.get("STATE_DIR") or home / "jobs")
    extra = agy_extra_env(env)
    askpass_dir = Path(env["ASKPASS_DIR"]) if env.get("ASKPASS_DIR") else None
    if askpass_dir is not None:   # root-only and on a mount that allows exec (the container /tmp is noexec)
        askpass_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    deps = CoderDeps(
        home=home,
        secrets=FileSecrets(secret_paths(env)),
        github=github,
        git=lambda author, cancel: SubprocessGit(author=author, cancel=cancel, askpass_dir=askpass_dir),
        engines=lambda ctx: agy_chain(ctx, extra),
        toolchain=Toolchain(home, node_dir=NODE_DIR),
        clock=SystemClock(),
        owner_user_id=owner_user_id,
        engine_user=sandbox.ensure_agy_user,
        privileged_work_root=Path(env.get("WORKROOT") or sandbox.PRIVILEGED_WORK_ROOT),
    )
    return CoderService(JobStore(state_dir, Redactor(env=env)), deps)
