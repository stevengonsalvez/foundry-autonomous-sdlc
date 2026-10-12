"""
Deploy the agent side of the demo onto the Foundry project. Idempotent; every step can be rerun.

  connection     project connection github-mcp (RemoteTool, CustomKeys, Authorization: Bearer <PAT>)
  prompt-agents  prompt agent versions (python -m sdlc_agents.create_agents)
  hosted         hosted agents sdlc-orchestrator, sdlc-coder and sdlc-ledger from zips, waits for status active
                 (idle timeout: orchestrator 2 minutes so compute stops between ticks, coder 10 minutes and the
                 egress guardrail EGRESS_POLICY_ID,
                 ledger 2 minutes at 0.25 vCPU and 0.5 GiB: it wakes only when events arrive)
  roles          Key Vault Secrets User per secret, Foundry User on the project for the hosted agents,
                 Cost Management Reader on the resource group for the ledger
  routine        routine sdlc-tick: every five minutes, invocations {"op":"tick"} to sdlc-orchestrator
  status         agent versions, identities, routine state and the last routine runs
  smoke          two coder status calls (no job, so 404 expected) proving the endpoint and session reuse
  all            connection, prompt-agents, hosted, roles, routine (in that order)

Credentials are the operator's `az login` (AzureCliCredential). The PAT is read from Key Vault,
sent only in the connection PUT body, and redacted from everything this script prints.

Configuration comes from the environment, falling back to `terraform output` in infra/terraform:
FOUNDRY_PROJECT_ENDPOINT, KEY_VAULT_URI, AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, GITHUB_OWNER, and
EGRESS_POLICY_ID (output egress_policy_id: the egress guardrail attached to sdlc-coder; warned when absent).

Usage: uv run --project agents python scripts/deploy_agents.py [--dry-run] <command> [options]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import itertools
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TextIO

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = REPO_ROOT / "agents"
TERRAFORM_DIR = REPO_ROOT / "infra" / "terraform"
if str(AGENTS_DIR) not in sys.path:
    sys.path.insert(0, str(AGENTS_DIR))

from sdlc_agents.keyvault import KeyVaultSecrets  # noqa: E402
from sdlc_agents.ports import OWNER, REPO  # noqa: E402
from sdlc_agents.transport import HttpRequest, Transport, urllib_transport  # noqa: E402

ORCHESTRATOR = "sdlc-orchestrator"
CODER = "sdlc-coder"
LEDGER = "sdlc-ledger"
LEDGER_MODES = ("hosted", "inline", "off")


@dataclass(frozen=True)
class HostedSize:
    cpu: str
    memory: str          # "2Gi"
    idle_minutes: int    # session idle timeout before compute is released (platform range 2 to 60)


# Hosted compute bills while a session is active. The orchestrator idles out between five minute ticks;
# the coder stays up between the orchestrator's status polls.
DEFAULT_SIZES: dict[str, HostedSize] = {ORCHESTRATOR: HostedSize("1", "2Gi", 2), CODER: HostedSize("2", "4Gi", 10),
                                         LEDGER: HostedSize("0.25", "0.5Gi", 2)}
MODEL_DEPLOYMENT = "sdlc-default"
CONNECTION_NAME = "github-mcp"
MCP_TARGET = "https://api.githubcopilot.com/mcp/"
ARM = "https://management.azure.com"
ARM_API_VERSION = "2025-04-01-preview"
ARM_SCOPE = "https://management.azure.com/.default"
AI_SCOPE = "https://ai.azure.com/.default"
# Hosted agents that get the egress guardrail. The coder runs untrusted code (agy, npm ci, tests);
# the orchestrator and ledger run only this repository's code and are left open (docs/architecture.md).
EGRESS_AGENTS = (CODER,)
ROUTINE = "sdlc-tick"
PROBE_ROUTINE = "probe-tick"
ROUTINE_CRON = "*/5 * * * *"
ROUTINE_DESCRIPTION = "Wakes sdlc-orchestrator every five minutes to advance issues and PRs."
POLL_S = 5
KV_SECRETS_USER = "Key Vault Secrets User"
FOUNDRY_USER = "Foundry User"
COST_READER = "Cost Management Reader"
# Foundry roles were renamed; the old name is tried when the new one is not visible yet.
ROLE_NAMES: dict[str, tuple[str, ...]] = {
    KV_SECRETS_USER: (KV_SECRETS_USER,),
    FOUNDRY_USER: (FOUNDRY_USER, "Azure AI User"),
    COST_READER: (COST_READER,),
}
_ENDPOINT = re.compile(r"https://([a-z0-9-]+)\.services\.ai\.azure\.com/api/projects/([A-Za-z0-9_.-]+)/?")


class DeployError(RuntimeError):
    pass


# ---------------------------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Config:
    project_endpoint: str
    key_vault_uri: str
    subscription_id: str
    resource_group: str
    github_owner: str = OWNER
    # Full ARM id of the egress guardrail (accounts/raiPolicies) attached to sdlc-coder; empty = none.
    egress_policy_id: str = ""

    @classmethod
    def resolve(cls, env: Mapping[str, str], *, terraform_outputs: Callable[[], dict[str, Any]]) -> Config:
        wanted = {"FOUNDRY_PROJECT_ENDPOINT": "foundry_project_endpoint", "KEY_VAULT_URI": "key_vault_uri",
                  "AZURE_SUBSCRIPTION_ID": "azure_subscription_id", "AZURE_RESOURCE_GROUP": "resource_group_name"}
        values = {var: env.get(var, "") for var in wanted}
        egress = env.get("EGRESS_POLICY_ID", "")
        if not all(values.values()):
            outputs = terraform_outputs()
            for var, output in wanted.items():
                values[var] = values[var] or str((outputs.get(output) or {}).get("value", ""))
            egress = egress or str((outputs.get("egress_policy_id") or {}).get("value", ""))
        missing = [var for var, value in values.items() if not value]
        if missing:
            raise DeployError(f"{', '.join(missing)} not set and not found in terraform outputs")
        config = cls(values["FOUNDRY_PROJECT_ENDPOINT"], values["KEY_VAULT_URI"], values["AZURE_SUBSCRIPTION_ID"],
                     values["AZURE_RESOURCE_GROUP"], env.get("GITHUB_OWNER") or OWNER, egress)
        if not _ENDPOINT.fullmatch(config.project_endpoint):
            raise DeployError(f"not a Foundry project endpoint: {config.project_endpoint}")
        return config

    @property
    def account(self) -> str:
        return _ENDPOINT.fullmatch(self.project_endpoint).group(1)  # type: ignore[union-attr]

    @property
    def project(self) -> str:
        return _ENDPOINT.fullmatch(self.project_endpoint).group(2)  # type: ignore[union-attr]

    @property
    def key_vault_name(self) -> str:
        return (urllib.parse.urlparse(self.key_vault_uri).hostname or "").split(".")[0]

    @property
    def project_scope(self) -> str:
        return (f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}/providers/"
                f"Microsoft.CognitiveServices/accounts/{self.account}/projects/{self.project}")

    @property
    def group_scope(self) -> str:
        return f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}"

    def secret_scope(self, secret: str) -> str:
        return (f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}/providers/"
                f"Microsoft.KeyVault/vaults/{self.key_vault_name}/secrets/{secret}")

    def hosted_env(self) -> dict[str, str]:
        # The platform injects FOUNDRY_PROJECT_ENDPOINT too; setting it here keeps the agents independent of that.
        return {"KEY_VAULT_URI": self.key_vault_uri, "FOUNDRY_PROJECT_ENDPOINT": self.project_endpoint,
                "FOUNDRY_MODEL_DEPLOYMENT": MODEL_DEPLOYMENT, "REPO": REPO, "GITHUB_OWNER": self.github_owner}


def terraform_outputs() -> dict[str, Any]:
    try:
        proc = subprocess.run(["terraform", f"-chdir={TERRAFORM_DIR}", "output", "-json"],  # noqa: S603, S607
                              capture_output=True, text=True, check=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DeployError(f"terraform output failed ({exc}); set the environment variables instead") from None
    outputs: dict[str, Any] = json.loads(proc.stdout or "{}")
    return outputs


# ---------------------------------------------------------------------------------------------
# Output with secret redaction
# ---------------------------------------------------------------------------------------------

class Console:
    def __init__(self, out: TextIO = sys.stdout):
        self._out = out
        self._secrets: list[str] = []

    def secret(self, value: str) -> None:
        if value:
            self._secrets.append(value)

    def redact(self, text: str) -> str:
        for value in self._secrets:
            text = text.replace(value, "***")
        return text

    def say(self, message: str) -> None:
        print(self.redact(message), file=self._out, flush=True)


# ---------------------------------------------------------------------------------------------
# Foundry data plane (agents, versions, routines) behind a small facade
# ---------------------------------------------------------------------------------------------

class FoundryOps(Protocol):
    def get_agent(self, name: str) -> dict[str, Any] | None: ...
    def list_agents(self) -> list[dict[str, Any]]: ...
    def create_hosted_version(self, name: str, *, cpu: str, memory: str, idle_minutes: int, env: dict[str, str],
                              code: bytes, sha256: str, description: str, rai_policy: str = "") -> str: ...
    def get_version(self, name: str, version: str) -> dict[str, Any]: ...
    def get_routine(self, name: str) -> dict[str, Any] | None: ...
    def put_routine(self, name: str, **fields: Any) -> None: ...
    def set_routine_enabled(self, name: str, enabled: bool) -> None: ...
    def list_runs(self, name: str, limit: int) -> list[dict[str, Any]]: ...


def _g(obj: Any, key: str) -> Any:
    """Field access that works for SDK models (mappings) and plain dicts alike."""
    if obj is None:
        return None
    if isinstance(obj, Mapping) or hasattr(obj, "get"):
        return obj.get(key)
    return getattr(obj, key, None)


class SdkFoundry:
    def __init__(self, client: Any, *, not_found: type[Exception] | None = None):
        if not_found is None:
            from azure.core.exceptions import ResourceNotFoundError
            not_found = ResourceNotFoundError
        self._client = client
        self._not_found = not_found

    def _agent_view(self, agent: Any) -> dict[str, Any]:
        latest = _g(_g(agent, "versions"), "latest")
        return {"name": _g(agent, "name"), "kind": _g(_g(latest, "definition"), "kind"),
                "latest_version": str(_g(latest, "version")), "status": _g(latest, "status"),
                "principal_id": _g(_g(agent, "instance_identity"), "principal_id")}

    def get_agent(self, name: str) -> dict[str, Any] | None:
        try:
            return self._agent_view(self._client.agents.get(agent_name=name))
        except self._not_found:
            return None

    def list_agents(self) -> list[dict[str, Any]]:
        return [self._agent_view(a) for a in self._client.agents.list()]

    def create_hosted_version(self, name: str, *, cpu: str, memory: str, idle_minutes: int, env: dict[str, str],
                              code: bytes, sha256: str, description: str, rai_policy: str = "") -> str:
        from azure.ai.projects.models import (
            CodeConfiguration,
            HostedAgentDefinition,
            ProtocolVersionRecord,
            RaiConfig,
            SessionConfiguration,
        )

        definition = HostedAgentDefinition(
            cpu=cpu, memory=memory, environment_variables=env,
            session_configuration=SessionConfiguration(idle_timeout_seconds=datetime.timedelta(minutes=idle_minutes)),
            code_configuration=CodeConfiguration(runtime="python_3_13", entry_point=["python", "main.py"],
                                                 dependency_resolution="remote_build"),
            protocol_versions=[ProtocolVersionRecord(protocol="invocations", version="2.0.0")],
            # The egress guardrail binds to the version: a policy change needs a new version and a new session.
            rai_config=RaiConfig(rai_policy_name=rai_policy) if rai_policy else None,
        )
        created = self._client.agents.create_version_from_code(
            agent_name=name, definition=definition, code=(f"{name}.zip", code, "application/zip"),
            code_zip_sha256=sha256, description=description,
        )
        return str(_g(created, "version"))

    def get_version(self, name: str, version: str) -> dict[str, Any]:
        found = self._client.agents.get_version(agent_name=name, agent_version=version)
        return {"status": _g(found, "status"), "error": _g(found, "error")}

    def get_routine(self, name: str) -> dict[str, Any] | None:
        try:
            routine = self._client.beta.routines.get(name)
        except self._not_found:
            return None
        trigger = next(iter((_g(routine, "triggers") or {}).values()), None)
        action = _g(routine, "action")
        return {"description": _g(routine, "description"), "enabled": bool(_g(routine, "enabled")),
                "cron": _g(trigger, "cron_expression"), "time_zone": _g(trigger, "time_zone"),
                "agent": _g(action, "agent_name"), "input": _g(action, "input")}

    def put_routine(self, name: str, **fields: Any) -> None:
        from azure.ai.projects.models import InvokeAgentInvocationsApiRoutineAction, ScheduleRoutineTrigger

        self._client.beta.routines.create_or_update(
            name, description=fields["description"], enabled=fields["enabled"],
            triggers={"default": ScheduleRoutineTrigger(cron_expression=fields["cron"], time_zone=fields["time_zone"])},
            action=InvokeAgentInvocationsApiRoutineAction(agent_name=fields["agent"], input=fields["input"]),
        )

    def set_routine_enabled(self, name: str, enabled: bool) -> None:
        if enabled:
            self._client.beta.routines.enable(name)
        else:
            self._client.beta.routines.disable(name)

    def list_runs(self, name: str, limit: int) -> list[dict[str, Any]]:
        runs = self._client.beta.routines.list_runs(name, limit=limit, order="desc")
        return [{"status": _g(r, "status"), "triggered_at": str(_g(r, "triggered_at")),
                 "error": _g(r, "error_message")} for r in itertools.islice(runs, limit)]


# ---------------------------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------------------------

class _TokenCredential:
    """Adapts a scope -> token callable to the get_token(...) shape KeyVaultSecrets expects."""

    def __init__(self, token: Callable[[str], str]):
        self._token = token

    def get_token(self, *scopes: str, **_: Any) -> Any:
        return type("AccessToken", (), {"token": self._token(scopes[0])})()


def _load_zip_builder(path: Path) -> Callable[[], bytes]:
    def build() -> bytes:
        if not path.exists():
            raise DeployError(f"{path.relative_to(REPO_ROOT)} is missing")
        spec = importlib.util.spec_from_file_location(f"build_zip_{path.parent.name}", path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if hasattr(module, "build_zip"):
            data: bytes = module.build_zip()
            return data
        # The orchestrator's builder writes a file: build(out) -> sha256.
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / f"{path.parent.name}.zip"
            module.build(out)
            return out.read_bytes()
    return build


def default_zip_builders() -> dict[str, Callable[[], bytes]]:
    return {ORCHESTRATOR: _load_zip_builder(AGENTS_DIR / "hosted/orchestrator/build_zip.py"),
            CODER: _load_zip_builder(AGENTS_DIR / "hosted/coder/build_zip.py"),
            LEDGER: _load_zip_builder(AGENTS_DIR / "hosted/ledger/build_zip.py")}


@dataclass
class Deployer:
    config: Config
    foundry: FoundryOps
    az: Callable[[list[str]], str]
    http: Transport
    token: Callable[[str], str]
    run: Callable[..., int]
    console: Console
    dry_run: bool = False
    sleep: Callable[[float], None] = time.sleep
    zip_builders: dict[str, Callable[[], bytes]] | None = None

    def say(self, message: str) -> None:
        self.console.say(("[dry-run] " if self.dry_run else "") + message)

    # -- connection ------------------------------------------------------------------------

    def connection(self) -> None:
        url = f"{ARM}{self.config.project_scope}/connections/{CONNECTION_NAME}?api-version={ARM_API_VERSION}"
        if self.dry_run:
            self.say(f"would PUT connection {CONNECTION_NAME}: RemoteTool, CustomKeys, target {MCP_TARGET}, "
                     f"Authorization from Key Vault secret github-pat ({self.config.key_vault_name})")
            return
        pat = KeyVaultSecrets(self.config.key_vault_uri, _TokenCredential(self.token), transport=self.http) \
            .get_secret("github-pat")
        self.console.secret(pat)
        body = {"properties": {"category": "RemoteTool", "authType": "CustomKeys", "target": MCP_TARGET,
                               "isSharedToAll": False,
                               # Read-only mode of the GitHub MCP server: the PAT behind it can write.
                               "credentials": {"keys": {"Authorization": f"Bearer {pat}", "X-MCP-Readonly": "true"}}}}
        resp = self.http(HttpRequest("PUT", url, {"Authorization": f"Bearer {self.token(ARM_SCOPE)}",
                                                  "Content-Type": "application/json"},
                                     json.dumps(body).encode(), 60.0))
        if resp.status not in (200, 201):
            raise DeployError(f"PUT connection {CONNECTION_NAME} returned {resp.status}: "
                              f"{self.console.redact(resp.text()[:500])}")
        self.say(f"connection {CONNECTION_NAME}: {'created' if resp.status == 201 else 'updated'} ({MCP_TARGET})")

    # -- prompt agents ---------------------------------------------------------------------

    def prompt_agents(self) -> None:
        cmd = [sys.executable, "-m", "sdlc_agents.create_agents"]
        if self.dry_run:
            self.say(f"would run {' '.join(cmd)} in {AGENTS_DIR}")
            return
        rc = self.run(cmd, env={**os.environ, "FOUNDRY_PROJECT_ENDPOINT": self.config.project_endpoint},
                      cwd=AGENTS_DIR)
        if rc != 0:
            raise DeployError(f"sdlc_agents.create_agents exited {rc}")

    # -- hosted agents ---------------------------------------------------------------------

    def hosted(self, sizes: dict[str, HostedSize], timeout_s: int, ledger_mode: str = "hosted") -> None:
        """Deploy the hosted agents. `ledger_mode` tells the orchestrator how to reach the state-keeper:
        hosted (the sdlc-ledger agent), inline (the same code in its own process, the documented fallback
        that deploys no ledger agent) or off."""
        if ledger_mode not in LEDGER_MODES:
            raise DeployError(f"ledger mode must be one of {', '.join(LEDGER_MODES)}")
        builders = self.zip_builders or default_zip_builders()
        # The ledger first: the orchestrator is told to use it only once it is there.
        for name, size in sorted(sizes.items(), key=lambda item: item[0] != LEDGER):
            env = {**self.config.hosted_env(), "HOSTED_CPU": size.cpu, "HOSTED_MEMORY": size.memory}
            if name == ORCHESTRATOR:
                env["LEDGER_MODE"] = ledger_mode
            if name == LEDGER:
                env.update({"AZURE_SUBSCRIPTION_ID": self.config.subscription_id,
                            "AZURE_RESOURCE_GROUP": self.config.resource_group})
            code = builders[name]()
            sha = hashlib.sha256(code).hexdigest()
            rai_policy = self.config.egress_policy_id if name in EGRESS_AGENTS else ""
            if name in EGRESS_AGENTS and not rai_policy:
                self.say(f"warning: {name} has no egress policy (set EGRESS_POLICY_ID or terraform output "
                         "egress_policy_id); its outbound traffic is unrestricted")
            if self.dry_run:
                self.say(f"would create {name} version: cpu={size.cpu} memory={size.memory} "
                         f"idle_timeout={size.idle_minutes}m python_3_13 remote_build invocations 2.0.0, "
                         f"zip {len(code)} bytes sha256 {sha}, env {sorted(env)}, egress {rai_policy or 'none'}")
                continue
            before = self.foundry.get_agent(name)
            version = self.foundry.create_hosted_version(
                name, cpu=size.cpu, memory=size.memory, idle_minutes=size.idle_minutes, env=env, code=code,
                sha256=sha, description=f"{name} zip sha256 {sha[:12]}", rai_policy=rai_policy)
            unchanged = before is not None and before["latest_version"] == version
            self.say(f"{name} version {version} {'unchanged' if unchanged else 'created'}, waiting for active")
            self._wait_active(name, version, timeout_s)
            self.say(f"{name} version {version} active")

    def _wait_active(self, name: str, version: str, timeout_s: int) -> None:
        waited = 0
        while True:
            found = self.foundry.get_version(name, version)
            if found["status"] == "active":
                return
            if found["status"] == "failed":
                error = found.get("error") or {}
                raise DeployError(f"{name} version {version} failed: {_g(error, 'code')}: {_g(error, 'message')}")
            if waited >= timeout_s:
                raise DeployError(f"{name} version {version} not active after {timeout_s}s (status {found['status']})")
            self.sleep(POLL_S)
            waited += POLL_S

    # -- role assignments ------------------------------------------------------------------

    def roles(self) -> None:
        plan = [
            (ORCHESTRATOR, KV_SECRETS_USER, self.config.secret_scope("github-pat")),
            (ORCHESTRATOR, FOUNDRY_USER, self.config.project_scope),
            (CODER, KV_SECRETS_USER, self.config.secret_scope("github-pat")),
            (CODER, KV_SECRETS_USER, self.config.secret_scope("agy-cli-token")),
            # Model calls from the fallback engine; the implicit project access is not relied on.
            (CODER, FOUNDRY_USER, self.config.project_scope),
        ]
        names = [ORCHESTRATOR, CODER]
        if self.foundry.get_agent(LEDGER) is not None:
            names.append(LEDGER)
            plan += [
                (LEDGER, KV_SECRETS_USER, self.config.secret_scope("github-pat")),
                (LEDGER, FOUNDRY_USER, self.config.project_scope),      # model summaries on sdlc-default
                (LEDGER, COST_READER, self.config.group_scope),         # what Azure billed, read only
            ]
        else:
            self.say(f"{LEDGER}: not deployed, no roles assigned (inline or off mode)")
        principals = {name: self._principal(name) for name in names}
        guids = {role: self._role_guid(role) for role in {r for _, r, _ in plan}}
        for name, role, scope in plan:
            pid, guid = principals[name], guids[role]
            existing = json.loads(self.az(["role", "assignment", "list", "--scope", scope, "-o", "json"]) or "[]")
            if any(a.get("principalId") == pid and str(a.get("roleDefinitionId", "")).lower().endswith(guid.lower())
                   and str(a.get("scope", "")).lower() == scope.lower() for a in existing):
                self.say(f"{name}: {role} on {scope} already assigned")
                continue
            if self.dry_run:
                self.say(f"would assign {role} ({guid}) to {name} ({pid}) on {scope}")
                continue
            self.az(["role", "assignment", "create", "--assignee-object-id", pid,
                     "--assignee-principal-type", "ServicePrincipal", "--role", guid, "--scope", scope, "-o", "json"])
            self.say(f"{name}: assigned {role} on {scope}")

    def _principal(self, name: str) -> str:
        agent = self.foundry.get_agent(name)
        if agent is None or not agent.get("principal_id"):
            raise DeployError(f"{name} has no instance identity yet; deploy hosted first")
        return str(agent["principal_id"])

    def _role_guid(self, role: str) -> str:
        for candidate in ROLE_NAMES[role]:
            found = json.loads(self.az(["role", "definition", "list", "--name", candidate, "-o", "json"]) or "[]")
            if found:
                return str(found[0]["name"])
        raise DeployError(f"role {' / '.join(ROLE_NAMES[role])} not found by az role definition list")

    # -- routine ---------------------------------------------------------------------------

    def routine(self, enable: bool | None) -> None:
        self._quiet_probe()
        desired = {"description": ROUTINE_DESCRIPTION, "cron": ROUTINE_CRON, "time_zone": "UTC",
                   "agent": ORCHESTRATOR, "input": {"op": "tick"}}
        current = self.foundry.get_routine(ROUTINE)
        if current is None:
            enabled = bool(enable)
            if self.dry_run:
                self.say(f"would create routine {ROUTINE} (enabled={enabled}): cron '{ROUTINE_CRON}' UTC, "
                         f"invocations {{\"op\":\"tick\"}} to {ORCHESTRATOR}")
                return
            self.foundry.put_routine(ROUTINE, enabled=enabled, **desired)
            self.say(f"routine {ROUTINE}: created, enabled={enabled}")
            return
        target = current["enabled"] if enable is None else enable
        drift = [key for key, value in desired.items() if current.get(key) != value]
        if drift:
            if self.dry_run:
                self.say(f"would update routine {ROUTINE} ({', '.join(drift)}), enabled={target}")
                return
            self.foundry.put_routine(ROUTINE, enabled=target, **desired)
            self.say(f"routine {ROUTINE}: updated {', '.join(drift)}, enabled={target}")
        elif target != current["enabled"]:
            if self.dry_run:
                self.say(f"would set routine {ROUTINE} enabled={target}")
                return
            self.foundry.set_routine_enabled(ROUTINE, target)
            self.say(f"routine {ROUTINE}: {'enabled' if target else 'disabled'}")
        else:
            self.say(f"routine {ROUTINE}: unchanged, enabled={target}")

    def _quiet_probe(self) -> None:
        """The spike's routine cannot be deleted yet (docs/findings.md); keep it disabled and leave it."""
        probe = self.foundry.get_routine(PROBE_ROUTINE)
        if probe is None:
            self.say(f"{PROBE_ROUTINE}: absent")
        elif probe["enabled"] and not self.dry_run:
            self.foundry.set_routine_enabled(PROBE_ROUTINE, False)
            self.say(f"{PROBE_ROUTINE}: disabled (schedule routines cannot be deleted yet)")
        else:
            self.say(f"{PROBE_ROUTINE}: present, {'would disable' if probe['enabled'] else 'disabled'}, left in place")

    # -- smoke -----------------------------------------------------------------------------

    def smoke(self, session: str | None = None) -> str:
        """Call the coder twice with a status for a job that does not exist (expect 404 unknown_job).

        The platform issues the session id in the x-agent-session-id response header; the second call
        passes it back as the agent_session_id query parameter and must land in the same session.
        """
        base = f"{self.config.project_endpoint}/agents/{CODER}/endpoint/protocols/invocations?api-version=v1"
        body = json.dumps({"op": "status", "job_id": "smoke-check"}).encode()
        if self.dry_run:
            self.say(f"would POST {base} twice with {body.decode()}, reusing x-agent-session-id")
            return ""
        for attempt in (1, 2):
            url = base + (f"&agent_session_id={urllib.parse.quote(session)}" if session else "")
            resp = self.http(HttpRequest("POST", url, {"Authorization": f"Bearer {self.token(AI_SCOPE)}",
                                                       "Content-Type": "application/json"}, body, 240.0))
            returned = resp.headers.get("x-agent-session-id", "")
            if resp.status != 404 or json.loads(resp.body or b"{}").get("error") != "unknown_job":
                raise DeployError(f"smoke call {attempt} to {CODER} returned {resp.status}: {resp.text()[:300]}")
            if session and returned and returned != session:
                raise DeployError(f"smoke call {attempt} came back in session {returned}, expected {session}")
            session = session or returned
            self.say(f"smoke {attempt}: {CODER} answered 404 unknown_job in session {session or '-'}")
        return session or ""

    # -- status ----------------------------------------------------------------------------

    def status(self) -> None:
        for agent in self.foundry.list_agents():
            self.say(f"agent {agent['name']}: {agent['kind']} version {agent['latest_version']} {agent['status']} "
                     f"principal {agent['principal_id'] or '-'}")
        for name in (ROUTINE, PROBE_ROUTINE):
            routine = self.foundry.get_routine(name)
            if routine is None:
                self.say(f"{name}: absent")
                continue
            self.say(f"{name}: {'enabled' if routine['enabled'] else 'disabled'} cron '{routine['cron']}' "
                     f"{routine['time_zone']} -> {routine['agent']} input {json.dumps(routine['input'])}")
            for run in self.foundry.list_runs(name, 5):
                self.say(f"  run {run['triggered_at']} {run['status']} {run['error'] or ''}".rstrip())


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------

def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="deploy_agents.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="print what would change, change nothing")
    hosted = argparse.ArgumentParser(add_help=False)
    for agent, flag in ((ORCHESTRATOR, "orchestrator"), (CODER, "coder"), (LEDGER, "ledger")):
        default = DEFAULT_SIZES[agent]
        hosted.add_argument(f"--{flag}-cpu", default=default.cpu)
        hosted.add_argument(f"--{flag}-memory", default=default.memory)
        hosted.add_argument(f"--{flag}-idle-minutes", type=_idle_minutes, default=default.idle_minutes,
                            help="session idle timeout in minutes (2 to 60)")
    hosted.add_argument("--only", choices=(ORCHESTRATOR, CODER, LEDGER), help="deploy one hosted agent")
    hosted.add_argument("--ledger-mode", choices=LEDGER_MODES, default=None,
                        help="how the orchestrator reaches the state-keeper (hosted when sdlc-ledger is deployed in "
                             "the same run; required when the orchestrator is deployed alone, so a redeploy never "
                             "changes it silently); inline deploys no sdlc-ledger agent")
    hosted.add_argument("--timeout", type=int, default=900, help="seconds to wait for status active")
    routine = argparse.ArgumentParser(add_help=False)
    toggle = routine.add_mutually_exclusive_group()
    toggle.add_argument("--enable", dest="enable", action="store_const", const=True, default=None)
    toggle.add_argument("--disable", dest="enable", action="store_const", const=False)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("all", parents=[hosted, routine])
    sub.add_parser("connection")
    sub.add_parser("prompt-agents")
    sub.add_parser("hosted", parents=[hosted])
    sub.add_parser("roles")
    sub.add_parser("routine", parents=[routine])
    sub.add_parser("status")
    smoke = sub.add_parser("smoke")
    smoke.add_argument("--session", help="an existing coder session id to call into")
    return parser.parse_args(argv)


def _idle_minutes(value: str) -> int:
    minutes = int(value)
    if not 2 <= minutes <= 60:
        raise argparse.ArgumentTypeError("idle timeout must be 2 to 60 minutes")
    return minutes


def sizes_from(args: argparse.Namespace) -> dict[str, HostedSize]:
    sizes = {ORCHESTRATOR: HostedSize(args.orchestrator_cpu, args.orchestrator_memory, args.orchestrator_idle_minutes),
             CODER: HostedSize(args.coder_cpu, args.coder_memory, args.coder_idle_minutes),
             LEDGER: HostedSize(args.ledger_cpu, args.ledger_memory, args.ledger_idle_minutes)}
    if args.only:
        return {args.only: sizes[args.only]}
    if args.ledger_mode in ("inline", "off"):
        del sizes[LEDGER]
    return sizes


def dispatch(deployer: Deployer, args: argparse.Namespace) -> None:
    command = args.command
    if command in ("all", "connection"):
        deployer.connection()
    if command in ("all", "prompt-agents"):
        deployer.prompt_agents()
    if command in ("all", "hosted"):
        sizes = sizes_from(args)
        mode = args.ledger_mode or ("hosted" if LEDGER in sizes else None)
        if ORCHESTRATOR in sizes and mode is None:
            raise DeployError("deploying the orchestrator alone: say how it reaches the ledger with --ledger-mode")
        deployer.hosted(sizes, args.timeout, mode or "hosted")
    if command in ("all", "roles"):
        deployer.roles()
    if command in ("all", "routine"):
        deployer.routine(args.enable)
    if command == "status":
        deployer.status()
    if command == "smoke":
        deployer.smoke(args.session)


def run_az(args: list[str]) -> str:
    try:
        proc = subprocess.run(["az", *args], capture_output=True, text=True, timeout=300, check=False)  # noqa: S603, S607
    except OSError as exc:
        raise DeployError(f"az not runnable: {exc}") from None
    if proc.returncode != 0:
        raise DeployError(f"az {' '.join(args[:3])} failed: {proc.stderr.strip()[-800:]}")
    return proc.stdout


def run_command(cmd: list[str], *, env: dict[str, str], cwd: Path) -> int:
    return subprocess.run(cmd, env=env, cwd=cwd, check=False).returncode  # noqa: S603


def build_deployer(args: argparse.Namespace) -> Deployer:  # pragma: no cover - real Azure clients
    from azure.ai.projects import AIProjectClient
    from azure.identity import AzureCliCredential

    config = Config.resolve(os.environ, terraform_outputs=terraform_outputs)
    credential = AzureCliCredential()
    return Deployer(
        config=config, foundry=SdkFoundry(AIProjectClient(endpoint=config.project_endpoint, credential=credential)),
        az=run_az, http=urllib_transport, token=lambda scope: credential.get_token(scope).token, run=run_command,
        console=Console(), dry_run=args.dry_run,
    )


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        dispatch(build_deployer(args), args)
    except DeployError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
