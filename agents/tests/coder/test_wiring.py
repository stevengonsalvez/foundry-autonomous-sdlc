"""The hosted composition root builds the real adapters without touching the network."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sdlc_agents.coder import sandbox
from sdlc_agents.coder.engines import AgyEngine, ModelLoopEngine
from sdlc_agents.coder.git_adapter import SubprocessGit
from sdlc_agents.coder.job import JobSpec
from sdlc_agents.coder.runner import EngineContext
from sdlc_agents.coder.sandbox import RunAs
from sdlc_agents.coder.wiring import build_service, compute_usd_per_hour, owner_user_id
from sdlc_agents.github import GitHubClient
from sdlc_agents.keyvault import KeyVaultSecrets
from sdlc_agents.ports import REPO
from sdlc_agents.transport import HttpRequest, HttpResponse


class Credential:
    def get_token(self, *scopes: str, **_: Any) -> SimpleNamespace:
        return SimpleNamespace(token=f"tok-for-{scopes[0]}")


ENV = {"HOME": "/home/session", "KEY_VAULT_URI": "https://kv-x.vault.azure.net/",
       "FOUNDRY_PROJECT_ENDPOINT": "https://acct.services.ai.azure.com/api/projects/proj"}


def _spec() -> JobSpec:
    return JobSpec.from_request({
        "job_id": "j-1", "repo": REPO, "branch": "agent/issue-1", "mode": "feature", "issue": {"number": 1},
        "tests": [{"path": "app/tests/a.test.ts", "content": "x"}], "test_cmd": "npm test", "allowed_paths": ["app/"],
    })


def test_build_service_wires_vault_github_git_and_the_engine_chain(tmp_path: Path) -> None:
    service = build_service({**ENV, "HOME": str(tmp_path)}, credential=Credential())
    deps = service._deps
    assert isinstance(deps.secrets, KeyVaultSecrets)
    assert deps.github is GitHubClient
    assert isinstance(deps.git(("a", "b"), threading.Event()), SubprocessGit)
    assert deps.toolchain.home == tmp_path
    ctx = EngineContext(_spec(), ("app/tests/a.test.ts",), False, threading.Event(), {"PATH": "/bin"},
                        agy_binary=tmp_path / "agy", agy_home=tmp_path)
    chain = deps.engines(ctx)
    assert [type(e) for e in chain] == [AgyEngine, ModelLoopEngine]
    assert chain[0]._prepare is None
    assert chain[0]._dirty is ctx.dirty
    assert chain[0]._before_call is ctx.refresh_agy_settings
    assert chain[0]._log_dir == ctx.agy_log_dir
    assert chain[0]._env["HOME"] == str(tmp_path)
    user = RunAs("agyuser", 1001, 1001, Path("/home/agyuser"))
    chain_as_user = deps.engines(EngineContext(_spec(), (), False, threading.Event(), {},
                                               agy_binary=Path("/usr/local/bin/agy"), agy_home=user.home, run_as=user))
    assert [e.name for e in chain_as_user] == ["agy", "agy-unrestricted", "loop"]
    isolated = chain_as_user[0]
    assert isolated._run_as == user
    assert isolated._prepare is not None
    assert chain_as_user[1]._run_as == user
    no_agy = deps.engines(EngineContext(_spec(), (), False, threading.Event(), {}, agy_binary=None, agy_home=tmp_path))
    assert [e.name for e in no_agy] == ["loop"]
    assert deps.engine_user is sandbox.ensure_agy_user


def test_compute_price_comes_from_the_deployed_size() -> None:
    assert compute_usd_per_hour({"HOSTED_CPU": "2", "HOSTED_MEMORY": "4Gi"}) == pytest.approx(0.2706)
    assert compute_usd_per_hour({}) == 0.0
    assert compute_usd_per_hour({"HOSTED_CPU": "two"}) == 0.0


def test_model_loop_uses_the_project_endpoint_with_an_ai_scoped_token(tmp_path: Path) -> None:
    service = build_service({**ENV, "HOME": str(tmp_path)}, credential=Credential())
    loop = service._deps.engines(EngineContext(_spec(), (), False, threading.Event(), {}, None, Path("/h")))[0]
    client = loop._client
    assert client._url == "https://acct.services.ai.azure.com/api/projects/proj/openai/v1/responses"
    assert client._deployment == "sdlc-default"
    assert client._token() == "tok-for-https://ai.azure.com/.default"


def test_owner_user_id_reads_the_numeric_id_or_gives_none() -> None:
    def ok(request: HttpRequest) -> HttpResponse:
        assert request.url == "https://api.github.com/users/stevengonsalvez"
        return HttpResponse(200, {}, json.dumps({"login": "stevengonsalvez", "id": 9320602}).encode())

    assert owner_user_id("pat", transport=ok) == 9320602
    assert owner_user_id("pat", transport=lambda r: HttpResponse(401, {}, b"{}")) is None
    assert owner_user_id("pat", transport=lambda r: HttpResponse(200, {}, b'{"id": "x"}')) is None

    def down(request: HttpRequest) -> HttpResponse:
        raise OSError("network unreachable")

    assert owner_user_id("pat", transport=down) is None


def test_the_model_loop_is_wired_to_the_failing_tests_and_the_workdir(tmp_path: Path) -> None:
    service = build_service({**ENV, "HOME": str(tmp_path)}, credential=Credential())
    failing = lambda: ("app/web/tests/home-page.test.tsx",)  # noqa: E731
    ctx = EngineContext(_spec(), (), True, threading.Event(), {}, agy_binary=None, agy_home=tmp_path, failing=failing)
    loop = service._deps.engines(ctx)[-1]
    assert isinstance(loop, ModelLoopEngine)
    assert loop._failing is failing
    assert loop._workdir == "app"
