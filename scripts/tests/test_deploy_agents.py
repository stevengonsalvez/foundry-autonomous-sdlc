"""deploy_agents.py against fake ARM, Key Vault, Foundry and az transports. No Azure access."""

from __future__ import annotations

import datetime
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from scripts import deploy_agents as da

from sdlc_agents.transport import HttpRequest, HttpResponse

PAT = "github_pat_DEPLOYSECRET0123456789"
SUB = "9c5f866c-0000-4000-8000-000000000000"
ENDPOINT = "https://aif-fsdlcd.services.ai.azure.com/api/projects/proj-sdlc"
KV = "https://kv-fsdlcd-demo-x1.vault.azure.net/"
PROJECT_SCOPE = (f"/subscriptions/{SUB}/resourceGroups/rg-fsdlcd-demo/providers/"
                 "Microsoft.CognitiveServices/accounts/aif-fsdlcd/projects/proj-sdlc")
KV_SCOPE = f"/subscriptions/{SUB}/resourceGroups/rg-fsdlcd-demo/providers/Microsoft.KeyVault/vaults/kv-fsdlcd-demo-x1"
# Fake role ids: the script must resolve real ones by name through az, never from a table.
ROLE_GUIDS = {"Key Vault Secrets User": "00000000-0000-4000-8000-00000000a001",
              "Azure AI User": "00000000-0000-4000-8000-00000000a002",
              "Cost Management Reader": "00000000-0000-4000-8000-00000000a003"}

CONFIG = da.Config(project_endpoint=ENDPOINT, key_vault_uri=KV, subscription_id=SUB,
                   resource_group="rg-fsdlcd-demo", github_owner="stevengonsalvez")


class FakeHttp:
    def __init__(self) -> None:
        self.requests: list[HttpRequest] = []

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        if request.url.startswith(KV.rstrip("/") + "/secrets/github-pat"):
            return HttpResponse(200, {}, json.dumps({"value": PAT}).encode())
        if "management.azure.com" in request.url and request.method == "PUT":
            return HttpResponse(201, {}, json.dumps({"name": "github-mcp", "properties": {}}).encode())
        return HttpResponse(404, {}, b"{}")


class FakeAz:
    def __init__(self, roles: dict[str, str] | None = None, assignments: list[dict[str, str]] | None = None):
        self.roles = ROLE_GUIDS if roles is None else roles
        self.assignments = assignments or []
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        if args[:3] == ["role", "definition", "list"]:
            name = args[args.index("--name") + 1]
            return json.dumps([{"name": self.roles[name], "roleName": name}] if name in self.roles else [])
        if args[:3] == ["role", "assignment", "list"]:
            scope = args[args.index("--scope") + 1]
            return json.dumps([a for a in self.assignments if a["scope"] == scope])
        if args[:3] == ["role", "assignment", "create"]:
            role = args[args.index("--role") + 1]
            entry = {"principalId": args[args.index("--assignee-object-id") + 1],
                     "scope": args[args.index("--scope") + 1],
                     "roleDefinitionId": f"/providers/Microsoft.Authorization/roleDefinitions/{role}"}
            self.assignments.append(entry)
            return json.dumps(entry)
        raise AssertionError(f"unexpected az call {args}")


class FakeFoundry:
    def __init__(self, polls_until_active: int = 1, fail_with: str | None = None):
        self.agents: dict[str, dict[str, Any]] = {}
        self.routines: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, list[dict[str, Any]]] = {}
        self.polls_until_active = polls_until_active
        self.fail_with = fail_with
        self.created: list[dict[str, Any]] = []
        self.puts: list[str] = []

    def get_agent(self, name: str) -> dict[str, Any] | None:
        agent = self.agents.get(name)
        if agent is None:
            return None
        latest = agent["versions"][-1]
        return {"name": name, "kind": "hosted", "latest_version": latest["version"], "status": latest["status"],
                "principal_id": agent["principal_id"]}

    def list_agents(self) -> list[dict[str, Any]]:
        return [a for a in (self.get_agent(n) for n in sorted(self.agents)) if a]

    def create_hosted_version(self, name: str, *, cpu: str, memory: str, idle_minutes: int, env: dict[str, str],
                              code: bytes, sha256: str, description: str) -> str:
        agent = self.agents.setdefault(name, {"versions": [], "principal_id": f"pid-{name}"})
        key = (cpu, memory, idle_minutes, tuple(sorted(env.items())), sha256)
        if agent["versions"] and agent["versions"][-1]["key"] == key:
            return agent["versions"][-1]["version"]
        version = str(len(agent["versions"]) + 1)
        agent["versions"].append({"version": version, "key": key, "status": "creating", "polls": 0})
        self.created.append({"name": name, "cpu": cpu, "memory": memory, "idle": idle_minutes, "env": env,
                             "sha256": sha256,
                             "size": len(code)})
        return version

    def get_version(self, name: str, version: str) -> dict[str, Any]:
        v = next(x for x in self.agents[name]["versions"] if x["version"] == version)
        v["polls"] += 1
        if self.fail_with:
            v["status"] = "failed"
            return {"status": "failed", "error": {"code": "CodeError", "message": self.fail_with}}
        if v["polls"] >= self.polls_until_active:
            v["status"] = "active"
        return {"status": v["status"], "error": None}

    def get_routine(self, name: str) -> dict[str, Any] | None:
        return dict(self.routines[name]) if name in self.routines else None

    def put_routine(self, name: str, **fields: Any) -> None:
        self.puts.append(name)
        self.routines[name] = dict(fields)

    def set_routine_enabled(self, name: str, enabled: bool) -> None:
        self.routines[name]["enabled"] = enabled

    def list_runs(self, name: str, limit: int) -> list[dict[str, Any]]:
        return self.runs.get(name, [])[:limit]


def make(dry_run: bool = False, foundry: FakeFoundry | None = None, az: FakeAz | None = None,
         http: FakeHttp | None = None) -> tuple[da.Deployer, io.StringIO, SimpleNamespace]:
    out = io.StringIO()
    record = SimpleNamespace(foundry=foundry or FakeFoundry(), az=az or FakeAz(), http=http or FakeHttp(),
                             commands=[], tokens=[], sleeps=[])

    def run(cmd: list[str], *, env: dict[str, str], cwd: Path) -> int:
        record.commands.append((cmd, env, cwd))
        return 0

    def token(scope: str) -> str:
        record.tokens.append(scope)
        return f"token-{scope}"

    deployer = da.Deployer(
        config=CONFIG, foundry=record.foundry, az=record.az, http=record.http, token=token, run=run,
        console=da.Console(out), dry_run=dry_run, sleep=record.sleeps.append,
        zip_builders={da.ORCHESTRATOR: lambda: b"orchestrator-zip", da.CODER: lambda: b"coder-zip",
                      da.LEDGER: lambda: b"ledger-zip"},
    )
    return deployer, out, record


# -- config ------------------------------------------------------------------------------------

def test_config_from_env_derives_account_project_and_scopes() -> None:
    env = {"FOUNDRY_PROJECT_ENDPOINT": ENDPOINT, "KEY_VAULT_URI": KV, "AZURE_SUBSCRIPTION_ID": SUB,
           "AZURE_RESOURCE_GROUP": "rg-fsdlcd-demo"}
    config = da.Config.resolve(env, terraform_outputs=lambda: pytest.fail("terraform not needed"))
    assert (config.account, config.project, config.key_vault_name) == ("aif-fsdlcd", "proj-sdlc", "kv-fsdlcd-demo-x1")
    assert config.project_scope == PROJECT_SCOPE
    assert config.secret_scope("github-pat") == f"{KV_SCOPE}/secrets/github-pat"
    assert config.github_owner == "stevengonsalvez"


def test_config_falls_back_to_terraform_outputs() -> None:
    outputs = {"foundry_project_endpoint": {"value": ENDPOINT}, "key_vault_uri": {"value": KV},
               "azure_subscription_id": {"value": SUB}, "resource_group_name": {"value": "rg-fsdlcd-demo"}}
    assert da.Config.resolve({}, terraform_outputs=lambda: outputs) == CONFIG
    with pytest.raises(da.DeployError, match="KEY_VAULT_URI"):
        da.Config.resolve({}, terraform_outputs=lambda: {k: v for k, v in outputs.items() if k != "key_vault_uri"})
    with pytest.raises(da.DeployError, match="project endpoint"):
        da.Config.resolve({"FOUNDRY_PROJECT_ENDPOINT": "https://x.example.com/nope"}, terraform_outputs=lambda: outputs)


# -- connection --------------------------------------------------------------------------------

def test_connection_puts_custom_keys_with_the_pat_from_key_vault_and_never_prints_it() -> None:
    deployer, out, rec = make()
    deployer.connection()
    kv, arm = rec.http.requests
    assert kv.method == "GET"
    assert kv.url == f"{KV.rstrip('/')}/secrets/github-pat?api-version=7.4"
    assert kv.headers["Authorization"] == "Bearer token-https://vault.azure.net/.default"
    assert arm.method == "PUT"
    assert arm.url == (f"https://management.azure.com{PROJECT_SCOPE}/connections/github-mcp"
                       "?api-version=2025-04-01-preview")
    assert arm.headers["Authorization"] == "Bearer token-https://management.azure.com/.default"
    props = json.loads(arm.body)["properties"]
    assert props["category"] == "RemoteTool"
    assert props["authType"] == "CustomKeys"
    assert props["target"] == "https://api.githubcopilot.com/mcp/"
    assert props["credentials"] == {"keys": {"Authorization": f"Bearer {PAT}", "X-MCP-Readonly": "true"}}
    assert PAT not in out.getvalue()
    assert "github-mcp" in out.getvalue()
    assert PAT not in repr(arm)


def test_connection_failure_reports_status_without_the_secret() -> None:
    http = FakeHttp()
    deployer, _out, _ = make(http=http)
    http_call = http.__call__

    def failing(request: HttpRequest) -> HttpResponse:
        if request.method == "PUT":
            return HttpResponse(403, {}, json.dumps({"error": {"message": f"denied for {PAT}"}}).encode())
        return http_call(request)

    deployer.http = failing
    with pytest.raises(da.DeployError) as err:
        deployer.connection()
    assert "403" in str(err.value)
    assert PAT not in str(err.value)


def test_connection_dry_run_reads_no_secret_and_calls_nothing() -> None:
    deployer, out, rec = make(dry_run=True)
    deployer.connection()
    assert rec.http.requests == []
    assert rec.tokens == []
    assert "would PUT connection github-mcp" in out.getvalue()


# -- prompt agents -----------------------------------------------------------------------------

def test_prompt_agents_runs_create_agents_with_the_endpoint() -> None:
    deployer, out, rec = make()
    deployer.prompt_agents()
    (cmd, env, cwd), = rec.commands
    assert cmd == [sys.executable, "-m", "sdlc_agents.create_agents"]
    assert env["FOUNDRY_PROJECT_ENDPOINT"] == ENDPOINT
    assert cwd == da.AGENTS_DIR
    dry, out, rec = make(dry_run=True)
    dry.prompt_agents()
    assert rec.commands == []
    assert "would run" in out.getvalue()


def test_prompt_agents_failure_raises() -> None:
    deployer, _, _ = make()
    deployer.run = lambda cmd, *, env, cwd: 1
    with pytest.raises(da.DeployError, match="create_agents"):
        deployer.prompt_agents()


# -- hosted ------------------------------------------------------------------------------------

def test_hosted_creates_all_agents_with_sizes_and_env_and_waits_for_active() -> None:
    deployer, out, rec = make(foundry=FakeFoundry(polls_until_active=3))
    deployer.hosted(da.DEFAULT_SIZES, timeout_s=600)
    by_name = {c["name"]: c for c in rec.foundry.created}
    orchestrator, coder, ledger = by_name["sdlc-orchestrator"], by_name["sdlc-coder"], by_name["sdlc-ledger"]
    assert (orchestrator["cpu"], orchestrator["memory"], orchestrator["idle"]) == ("1", "2Gi", 2)
    assert (coder["cpu"], coder["memory"], coder["idle"]) == ("2", "4Gi", 10)
    assert (ledger["cpu"], ledger["memory"], ledger["idle"]) == ("0.25", "0.5Gi", 2)
    assert ledger["env"]["AZURE_RESOURCE_GROUP"] == "rg-fsdlcd-demo" and "LEDGER_MODE" not in ledger["env"]
    assert orchestrator["env"]["LEDGER_MODE"] == "hosted"
    assert coder["env"] == {
        "KEY_VAULT_URI": KV, "FOUNDRY_PROJECT_ENDPOINT": ENDPOINT, "FOUNDRY_MODEL_DEPLOYMENT": "sdlc-default",
        "REPO": "stevengonsalvez/foundry-autonomous-sdlc", "GITHUB_OWNER": "stevengonsalvez",
        "HOSTED_CPU": "2", "HOSTED_MEMORY": "4Gi"}
    assert orchestrator["env"]["HOSTED_CPU"] == "1"
    assert len(rec.sleeps) == 6
    assert "sdlc-coder version 1 active" in out.getvalue()


def test_hosted_is_idempotent_for_an_unchanged_zip() -> None:
    foundry = FakeFoundry()
    deployer, out, _ = make(foundry=foundry)
    deployer.hosted(da.DEFAULT_SIZES, timeout_s=600)
    deployer.hosted(da.DEFAULT_SIZES, timeout_s=600)
    assert len(foundry.created) == 3
    assert "sdlc-coder version 1 unchanged" in out.getvalue()


def test_inline_ledger_mode_deploys_no_ledger_agent_and_tells_the_orchestrator() -> None:
    args = da.parse_args(["hosted", "--ledger-mode", "inline"])
    sizes = da.sizes_from(args)
    assert da.LEDGER not in sizes
    deployer, _, rec = make()
    deployer.hosted(sizes, timeout_s=600, ledger_mode=args.ledger_mode)
    assert {c["name"] for c in rec.foundry.created} == {"sdlc-orchestrator", "sdlc-coder"}
    assert next(c for c in rec.foundry.created if c["name"] == "sdlc-orchestrator")["env"]["LEDGER_MODE"] == "inline"
    with pytest.raises(da.DeployError, match="ledger mode"):
        deployer.hosted(sizes, timeout_s=600, ledger_mode="sometimes")


def test_hosted_failure_surfaces_the_error_message() -> None:
    deployer, _, _ = make(foundry=FakeFoundry(fail_with="pip: No matching distribution for aiohttp==9"))
    with pytest.raises(da.DeployError, match="No matching distribution"):
        deployer.hosted(da.DEFAULT_SIZES, timeout_s=600)


def test_hosted_times_out() -> None:
    deployer, _, _ = make(foundry=FakeFoundry(polls_until_active=10_000))
    with pytest.raises(da.DeployError, match="not active after"):
        deployer.hosted(da.DEFAULT_SIZES, timeout_s=12)


def test_hosted_dry_run_builds_zips_but_creates_nothing() -> None:
    deployer, out, rec = make(dry_run=True)
    deployer.hosted({da.CODER: da.HostedSize("2", "4Gi", 30)}, timeout_s=600)
    assert rec.foundry.created == []
    assert "would create sdlc-coder" in out.getvalue()
    assert "cpu=2 memory=4Gi idle_timeout=30m" in out.getvalue()


def test_real_zip_builders_load_from_the_repo() -> None:
    builders = da.default_zip_builders()
    data = builders[da.CODER]()
    assert data[:2] == b"PK"


# -- roles -------------------------------------------------------------------------------------

def _deployed_foundry(ledger: bool = False) -> FakeFoundry:
    foundry = FakeFoundry()
    for name in (da.ORCHESTRATOR, da.CODER, *((da.LEDGER,) if ledger else ())):
        foundry.create_hosted_version(name, cpu="1", memory="2Gi", idle_minutes=2, env={}, code=b"", sha256="x",
                                      description="")
    return foundry


def test_roles_assign_secret_scoped_vault_access_and_foundry_user_with_resolved_guids() -> None:
    az = FakeAz()
    deployer, out, _ = make(foundry=_deployed_foundry(), az=az)
    deployer.roles()
    got = {(a["principalId"], a["scope"], a["roleDefinitionId"].rsplit("/", 1)[-1]) for a in az.assignments}
    kv_user, ai_user = ROLE_GUIDS["Key Vault Secrets User"], ROLE_GUIDS["Azure AI User"]
    assert got == {
        ("pid-sdlc-orchestrator", f"{KV_SCOPE}/secrets/github-pat", kv_user),
        ("pid-sdlc-orchestrator", PROJECT_SCOPE, ai_user),
        ("pid-sdlc-coder", f"{KV_SCOPE}/secrets/github-pat", kv_user),
        ("pid-sdlc-coder", f"{KV_SCOPE}/secrets/agy-cli-token", kv_user),
        ("pid-sdlc-coder", PROJECT_SCOPE, ai_user),
    }
    create = next(c for c in az.calls if c[:3] == ["role", "assignment", "create"])
    assert create[create.index("--assignee-principal-type") + 1] == "ServicePrincipal"
    assert ["role", "definition", "list", "--name", "Foundry User", "-o", "json"] in az.calls   # new name tried first

    az.calls.clear()
    deployer.roles()
    assert not [c for c in az.calls if c[:3] == ["role", "assignment", "create"]]
    assert "already assigned" in out.getvalue()


def test_roles_refuse_an_unresolvable_role_name() -> None:
    deployer, _, _ = make(foundry=_deployed_foundry(), az=FakeAz(roles={"Key Vault Secrets User": "g"}))
    with pytest.raises(da.DeployError, match="Foundry User"):
        deployer.roles()


def test_roles_need_the_agents_to_exist() -> None:
    deployer, _, _ = make()
    with pytest.raises(da.DeployError, match="deploy hosted first"):
        deployer.roles()


def test_the_ledger_gets_only_what_it_needs_and_no_roles_when_it_is_not_deployed() -> None:
    az = FakeAz()
    deployer, out, _ = make(foundry=_deployed_foundry(ledger=True), az=az)
    deployer.roles()
    got = {(a["principalId"], a["scope"], a["roleDefinitionId"].rsplit("/", 1)[-1]) for a in az.assignments
           if a["principalId"] == "pid-sdlc-ledger"}
    assert got == {
        ("pid-sdlc-ledger", f"{KV_SCOPE}/secrets/github-pat", ROLE_GUIDS["Key Vault Secrets User"]),
        ("pid-sdlc-ledger", PROJECT_SCOPE, ROLE_GUIDS["Azure AI User"]),
        ("pid-sdlc-ledger", f"/subscriptions/{SUB}/resourceGroups/rg-fsdlcd-demo", ROLE_GUIDS["Cost Management Reader"]),
    }
    quiet, out2, _ = make(foundry=_deployed_foundry(), az=FakeAz())
    quiet.roles()
    assert "sdlc-ledger: not deployed" in out2.getvalue()


def test_roles_dry_run_lists_what_it_would_assign() -> None:
    az = FakeAz()
    deployer, out, _ = make(foundry=_deployed_foundry(), az=az, dry_run=True)
    deployer.roles()
    assert not [c for c in az.calls if c[:3] == ["role", "assignment", "create"]]
    assert out.getvalue().count("would assign") == 5


# -- routine -----------------------------------------------------------------------------------

def test_routine_is_created_disabled_and_enabled_on_request() -> None:
    foundry = FakeFoundry()
    deployer, _out, _ = make(foundry=foundry)
    deployer.routine(enable=None)
    tick = foundry.routines["sdlc-tick"]
    assert tick == {"description": da.ROUTINE_DESCRIPTION, "enabled": False, "cron": "*/5 * * * *",
                    "time_zone": "UTC", "agent": "sdlc-orchestrator", "input": {"op": "tick"}}
    deployer.routine(enable=True)
    assert foundry.routines["sdlc-tick"]["enabled"] is True
    assert foundry.puts == ["sdlc-tick"]           # second call changed only the enabled flag
    deployer.routine(enable=None)                  # a redeploy keeps the routine running
    assert foundry.routines["sdlc-tick"]["enabled"] is True
    assert foundry.puts == ["sdlc-tick"]
    deployer.routine(enable=False)
    assert foundry.routines["sdlc-tick"]["enabled"] is False


def test_routine_drift_is_corrected_keeping_the_enabled_state() -> None:
    foundry = FakeFoundry()
    foundry.routines["sdlc-tick"] = {"description": "old", "enabled": True, "cron": "0 * * * *", "time_zone": "UTC",
                                     "agent": "someone-else", "input": {}}
    deployer, _out, _ = make(foundry=foundry)
    deployer.routine(enable=None)
    assert foundry.routines["sdlc-tick"]["cron"] == "*/5 * * * *"
    assert foundry.routines["sdlc-tick"]["agent"] == "sdlc-orchestrator"
    assert foundry.routines["sdlc-tick"]["enabled"] is True


def test_probe_routine_is_left_alone_but_never_left_enabled() -> None:
    foundry = FakeFoundry()
    foundry.routines["probe-tick"] = {"description": "", "enabled": True, "cron": "*/5 * * * *", "time_zone": "UTC",
                                      "agent": "probe", "input": {}}
    deployer, out, _ = make(foundry=foundry)
    deployer.routine(enable=None)
    assert foundry.routines["probe-tick"]["enabled"] is False
    assert "probe-tick" in out.getvalue()


def test_routine_dry_run_changes_nothing() -> None:
    foundry = FakeFoundry()
    deployer, out, _ = make(foundry=foundry, dry_run=True)
    deployer.routine(enable=True)
    assert foundry.routines == {}
    assert "would create routine sdlc-tick" in out.getvalue()


# -- status ------------------------------------------------------------------------------------

def test_status_prints_versions_identities_routines_and_runs() -> None:
    foundry = _deployed_foundry()
    foundry.routines["sdlc-tick"] = {"description": "", "enabled": True, "cron": "*/5 * * * *", "time_zone": "UTC",
                                     "agent": "sdlc-orchestrator", "input": {"op": "tick"}}
    foundry.runs["sdlc-tick"] = [{"status": "Finished", "triggered_at": "2026-10-10T12:05:00Z", "error": None},
                                 {"status": "Failed", "triggered_at": "2026-10-10T12:00:00Z",
                                  "error": "424 session_not_ready"}]
    deployer, out, _ = make(foundry=foundry)
    deployer.status()
    text = out.getvalue()
    assert "sdlc-coder" in text
    assert "pid-sdlc-coder" in text
    assert "sdlc-tick: enabled" in text
    assert "424 session_not_ready" in text
    assert "probe-tick: absent" in text


# -- CLI ---------------------------------------------------------------------------------------

def test_all_runs_every_step_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    deployer, _, _ = make(dry_run=True)
    order: list[str] = []
    for step in ("connection", "prompt_agents", "hosted", "roles", "routine"):
        monkeypatch.setattr(deployer, step, lambda *a, _s=step, **k: order.append(_s))
    da.dispatch(deployer, da.parse_args(["all"]))
    assert order == ["connection", "prompt_agents", "hosted", "roles", "routine"]


def test_parse_args_sizes_and_routine_flags() -> None:
    args = da.parse_args(["--dry-run", "hosted", "--coder-cpu", "1", "--coder-memory", "2Gi",
                          "--coder-idle-minutes", "45", "--only", "sdlc-coder"])
    assert args.dry_run
    assert da.sizes_from(args) == {"sdlc-coder": da.HostedSize("1", "2Gi", 45)}
    with pytest.raises(SystemExit):
        da.parse_args(["hosted", "--orchestrator-idle-minutes", "1"])
    assert da.sizes_from(da.parse_args(["hosted"])) == da.DEFAULT_SIZES
    assert da.parse_args(["routine", "--enable"]).enable is True
    assert da.parse_args(["routine", "--disable"]).enable is False
    with pytest.raises(SystemExit):
        da.parse_args(["routine", "--enable", "--disable"])


def test_main_reports_deploy_errors_as_exit_code_1(monkeypatch: pytest.MonkeyPatch,
                                                   capsys: pytest.CaptureFixture[str]) -> None:
    def boom(args: Any) -> da.Deployer:
        raise da.DeployError(f"nope {PAT}")

    monkeypatch.setattr(da, "build_deployer", boom)
    assert da.main(["status"]) == 1
    assert "nope" in capsys.readouterr().err


def test_main_runs_the_command(monkeypatch: pytest.MonkeyPatch) -> None:
    deployer, out, _ = make(foundry=_deployed_foundry())
    monkeypatch.setattr(da, "build_deployer", lambda args: deployer)
    assert da.main(["status"]) == 0
    assert "sdlc-orchestrator" in out.getvalue()


def test_console_redacts_registered_secrets() -> None:
    out = io.StringIO()
    console = da.Console(out)
    console.secret(PAT)
    console.say(f"value {PAT}")
    assert out.getvalue() == "value ***\n"


# -- SDK facade --------------------------------------------------------------------------------

class _NotFound(Exception):
    pass


def _sdk_agent(name: str) -> dict[str, Any]:
    latest = {"version": "3", "status": "active", "definition": {"kind": "hosted"}}
    return {"name": name, "versions": {"latest": latest},
            "instance_identity": {"principal_id": f"pid-{name}", "client_id": "c"}}


class FakeAgentsOps:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []

    def get(self, agent_name: str) -> dict[str, Any]:
        if agent_name == "missing":
            raise _NotFound(agent_name)
        return _sdk_agent(agent_name)

    def list(self) -> list[dict[str, Any]]:
        return [_sdk_agent("sdlc-coder")]

    def create_version_from_code(self, **kwargs: Any) -> SimpleNamespace:
        self.created.append(kwargs)
        return SimpleNamespace(version="4")

    def get_version(self, agent_name: str, agent_version: str) -> dict[str, Any]:
        return {"status": "failed", "error": {"code": "CodeError", "message": "bad"}}


class FakeRoutinesOps:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def get(self, name: str) -> dict[str, Any]:
        if name == "missing":
            raise _NotFound(name)
        return {"name": name, "enabled": False, "description": "d",
                "triggers": {"tick": {"type": "schedule", "cron_expression": "*/5 * * * *", "time_zone": "UTC"}},
                "action": {"type": "invoke_agent_invocations_api", "agent_name": "sdlc-orchestrator",
                           "input": {"op": "tick"}}}

    def create_or_update(self, name: str, **kwargs: Any) -> None:
        self.calls.append(("put", (name, kwargs)))

    def enable(self, name: str) -> None:
        self.calls.append(("enable", name))

    def disable(self, name: str) -> None:
        self.calls.append(("disable", name))

    def list_runs(self, name: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("runs", kwargs))
        return [{"status": "Finished", "triggered_at": "t", "error_message": None}]


def test_sdk_facade_maps_agents_versions_and_routines() -> None:
    pytest.importorskip("azure.ai.projects")  # runs in the agents CI job, which installs the SDK
    agents, routines = FakeAgentsOps(), FakeRoutinesOps()
    client = SimpleNamespace(agents=agents, beta=SimpleNamespace(routines=routines))
    sdk = da.SdkFoundry(client, not_found=_NotFound)
    assert sdk.get_agent("missing") is None
    assert sdk.get_agent("sdlc-coder") == {"name": "sdlc-coder", "kind": "hosted", "latest_version": "3",
                                           "status": "active", "principal_id": "pid-sdlc-coder"}
    assert [a["name"] for a in sdk.list_agents()] == ["sdlc-coder"]
    version = sdk.create_hosted_version("sdlc-coder", cpu="2", memory="4Gi", idle_minutes=30, env={"A": "b"},
                                        code=b"zip", sha256="abc", description="d")
    assert version == "4"
    created = agents.created[0]
    definition = created["definition"]
    assert created["agent_name"] == "sdlc-coder"
    assert created["code_zip_sha256"] == "abc"
    assert created["code"] == ("sdlc-coder.zip", b"zip", "application/zip")
    assert definition.cpu == "2"
    assert definition.memory == "4Gi"
    assert definition.environment_variables == {"A": "b"}
    assert definition.code_configuration.runtime == "python_3_13"
    assert definition.session_configuration.idle_timeout_seconds == datetime.timedelta(minutes=30)
    assert definition.code_configuration.dependency_resolution == "remote_build"
    assert definition.protocol_versions[0].protocol == "invocations"
    assert sdk.get_version("sdlc-coder", "4")["error"]["message"] == "bad"

    assert sdk.get_routine("missing") is None
    assert sdk.get_routine("sdlc-tick") == {"description": "d", "enabled": False, "cron": "*/5 * * * *",
                                            "time_zone": "UTC", "agent": "sdlc-orchestrator", "input": {"op": "tick"}}
    sdk.put_routine("sdlc-tick", description="d", enabled=False, cron="*/5 * * * *", time_zone="UTC",
                    agent="sdlc-orchestrator", input={"op": "tick"})
    name, kwargs = routines.calls[0][1]
    assert name == "sdlc-tick"
    assert kwargs["enabled"] is False
    assert kwargs["triggers"]["default"].cron_expression == "*/5 * * * *"
    assert kwargs["action"].agent_name == "sdlc-orchestrator"
    assert kwargs["action"].input == {"op": "tick"}
    sdk.set_routine_enabled("sdlc-tick", True)
    sdk.set_routine_enabled("sdlc-tick", False)
    assert routines.calls[1:] == [("enable", "sdlc-tick"), ("disable", "sdlc-tick")]
    assert sdk.list_runs("sdlc-tick", 5) == [{"status": "Finished", "triggered_at": "t", "error": None}]


# -- subprocess adapters and builders ----------------------------------------------------------

def test_terraform_outputs_and_az_wrap_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        calls.append(cmd)
        if cmd[0] == "terraform":
            return SimpleNamespace(returncode=0, stdout=json.dumps({"key_vault_uri": {"value": KV}}), stderr="")
        if cmd[:2] == ["az", "fail"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="ERROR: AuthorizationFailed")
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")

    monkeypatch.setattr(da.subprocess, "run", fake_run)
    assert da.terraform_outputs() == {"key_vault_uri": {"value": KV}}
    assert calls[0][:2] == ["terraform", f"-chdir={da.TERRAFORM_DIR}"]
    assert da.run_az(["role", "definition", "list"]) == "[]"
    with pytest.raises(da.DeployError, match="AuthorizationFailed"):
        da.run_az(["fail", "x"])
    assert da.run_command(["true"], env={}, cwd=Path(".")) == 0


def test_missing_terraform_or_az_is_a_deploy_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(cmd: list[str], **kwargs: Any) -> None:
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(da.subprocess, "run", missing)
    with pytest.raises(da.DeployError, match="terraform output failed"):
        da.terraform_outputs()
    with pytest.raises(da.DeployError, match="az not runnable"):
        da.run_az(["account", "show"])


def test_zip_loader_supports_file_writing_builders(tmp_path: Path) -> None:
    builder = tmp_path / "x" / "build_zip.py"
    builder.parent.mkdir()
    builder.write_text("def build(out):\n    out.write_bytes(b'PK-from-file')\n    return 'sha'\n")
    assert da._load_zip_builder(builder)() == b"PK-from-file"
    missing = da.REPO_ROOT / "agents/hosted/nowhere/build_zip.py"
    with pytest.raises(da.DeployError, match="missing"):
        da._load_zip_builder(missing)()


def test_routine_dry_run_reports_drift_and_toggles_without_changing_anything() -> None:
    foundry = FakeFoundry()
    foundry.routines["sdlc-tick"] = {"description": da.ROUTINE_DESCRIPTION, "enabled": False, "cron": "0 * * * *",
                                     "time_zone": "UTC", "agent": "sdlc-orchestrator", "input": {"op": "tick"}}
    foundry.routines["probe-tick"] = {"description": "", "enabled": True, "cron": "*/5 * * * *", "time_zone": "UTC",
                                      "agent": "probe", "input": {}}
    deployer, out, _ = make(foundry=foundry, dry_run=True)
    deployer.routine(enable=None)
    assert "would update routine sdlc-tick (cron)" in out.getvalue()
    assert "probe-tick: present, would disable" in out.getvalue()
    foundry.routines["sdlc-tick"]["cron"] = "*/5 * * * *"
    deployer.routine(enable=True)
    assert "would set routine sdlc-tick enabled=True" in out.getvalue()
    assert foundry.routines["sdlc-tick"]["enabled"] is False
    assert foundry.routines["probe-tick"]["enabled"] is True
    assert foundry.puts == []


class SmokeHttp:
    def __init__(self, sessions: list[str], status: int = 404, error: str = "unknown_job"):
        self.sessions = sessions
        self.status = status
        self.error = error
        self.requests: list[HttpRequest] = []

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        return HttpResponse(self.status, {"x-agent-session-id": self.sessions.pop(0)},
                            json.dumps({"error": self.error}).encode())


def test_smoke_reuses_the_platform_session_id_as_a_query_parameter() -> None:
    http = SmokeHttp(["sess-1", "sess-1"])
    deployer, out, _ = make(http=http)  # type: ignore[arg-type]
    assert deployer.smoke() == "sess-1"
    first, second = http.requests
    base = f"{ENDPOINT}/agents/sdlc-coder/endpoint/protocols/invocations?api-version=v1"
    assert first.url == base
    assert second.url == base + "&agent_session_id=sess-1"
    assert json.loads(second.body) == {"op": "status", "job_id": "smoke-check"}
    assert second.headers["Authorization"] == "Bearer token-https://ai.azure.com/.default"
    assert "in session sess-1" in out.getvalue()


def test_smoke_fails_on_a_wrong_answer_or_a_session_switch() -> None:
    deployer, _, _ = make(http=SmokeHttp(["s"], status=424, error="session_not_ready"))  # type: ignore[arg-type]
    with pytest.raises(da.DeployError, match="424"):
        deployer.smoke()
    deployer, _, _ = make(http=SmokeHttp(["s-1", "s-2"]))  # type: ignore[arg-type]
    with pytest.raises(da.DeployError, match="expected s-1"):
        deployer.smoke()
    dry, out, _ = make(dry_run=True)
    assert dry.smoke() == ""
    assert "would POST" in out.getvalue()


def test_smoke_command_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    deployer, _, _ = make(dry_run=True)
    seen: list[Any] = []
    monkeypatch.setattr(deployer, "smoke", lambda session: seen.append(session))
    da.dispatch(deployer, da.parse_args(["smoke", "--session", "abc"]))
    assert seen == ["abc"]
