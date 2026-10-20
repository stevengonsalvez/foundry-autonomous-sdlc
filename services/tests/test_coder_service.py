"""
The local coder service: the Coder contract (docs/architecture.md) over plain HTTP.

Real jobs run the unchanged CoderService/JobRunner against a real bare git remote with scripted
engines and the fake vitest from agents/tests/coder; the HTTP layer is driven with http.client
exactly as CliFoundry.invoke_hosted calls it.
"""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from coder.gitfixture import make_remote
from coder.test_runner import (
    PAT,
    QUOTA_RESTRICTED,
    QUOTA_UNRESTRICTED,
    SEED,
    FakeClock,
    FakeGitHub,
    ScriptedEngine,
    World,
    job,
)
from sdlc_agents.coder import local_wiring
from sdlc_agents.coder.engines import AgyEngine
from sdlc_agents.coder.runner import EngineContext
from sdlc_agents.coder.sandbox import RunAs
from sdlc_agents.ports import REPO, CommandResult

from sdlc_factory import coder_service
from sdlc_factory.coder_service import MAX_BODY_BYTES, SESSION_HEADER, TOKEN_HEADER, FakeCoder, serve

SERVICES = Path(__file__).resolve().parents[1]
AGENTS = SERVICES.parent / "agents"
FIX = {"app/web/src/eta.txt": "2026-10-12\n"}


@pytest.fixture
def coder_world(tmp_path: Path) -> World:
    remote_root = tmp_path / "remote"
    base = make_remote(remote_root, SEED)
    return World(tmp_path, remote_root, base, FakeGitHub(), FakeClock(), [])


@contextmanager
def running(service: Any, *, token: str | None = None) -> Iterator[tuple[str, int]]:
    server = serve(service, host="127.0.0.1", port=0, token=token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "127.0.0.1", server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def call(addr: tuple[str, int], body: Any, *, session: str | None = None, headers: dict[str, str] | None = None,
         path: str = "/invoke") -> tuple[int, dict[str, str], dict[str, Any]]:
    conn = http.client.HTTPConnection(*addr, timeout=30)
    if session is not None:
        path += "?" + urllib.parse.urlencode({"agent_session_id": session})
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    conn.request("POST", path, raw, {"Content-Type": "application/json", **(headers or {})})
    resp = conn.getresponse()
    data = json.loads(resp.read() or b"{}")
    conn.close()
    return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data


def poll(addr: tuple[str, int], job_id: str, session: str, timeout_s: float = 60) -> dict[str, Any]:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        code, _, status = call(addr, {"op": "status", "job_id": job_id}, session=session)
        assert code == 200, status
        if status["status"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} still running")


def gated(gate: threading.Event, entered: threading.Event, then: CommandResult | None = None):
    def step(root: Path) -> CommandResult:
        entered.set()
        assert gate.wait(30)
        if then is not None:
            return then
        (root / "app/web/src/eta.txt").write_text(FIX["app/web/src/eta.txt"])
        return CommandResult(0, "edited")

    return step


# -- the contract over HTTP -----------------------------------------------------------------------------


def test_start_runs_the_job_to_a_pr_and_the_session_is_issued_then_echoed(coder_world: World) -> None:
    gate, entered = threading.Event(), threading.Event()
    coder_world.engines = [ScriptedEngine("agy", [gated(gate, entered)])]
    with running(coder_world.service()) as addr:
        code, headers, started = call(addr, {"op": "start", "job": job()})
        assert code == 200, started
        session = headers[SESSION_HEADER]
        assert len(session) >= 32
        assert started == {"job_id": "j-12-1", "status": "running", "session_id": session}

        assert entered.wait(30)
        code, headers, status = call(addr, {"op": "status", "job_id": "j-12-1"}, session=session)
        assert code == 200
        assert headers[SESSION_HEADER] == session
        assert status["status"] == "running"

        gate.set()
        final = poll(addr, "j-12-1", session)
    assert final["status"] == "succeeded", final
    assert final["pr"]["number"] == 100
    assert final["session_id"] == session
    assert coder_world.github.labels[100] == ("agent:pr",)


def test_cancel_stops_a_running_job(coder_world: World) -> None:
    gate, entered = threading.Event(), threading.Event()
    coder_world.engines = [ScriptedEngine("agy", [gated(gate, entered, CommandResult(130, "[cancelled]"))])]
    with running(coder_world.service()) as addr:
        _, headers, _ = call(addr, {"op": "start", "job": job()})
        session = headers[SESSION_HEADER]
        assert entered.wait(30)
        code, _, resp = call(addr, {"op": "cancel", "job_id": "j-12-1"}, session=session)
        assert (code, resp["status"]) == (200, "cancelling")
        gate.set()
        assert poll(addr, "j-12-1", session)["status"] == "cancelled"


def test_scope_violation_fails_the_job(coder_world: World) -> None:
    coder_world.engines = [ScriptedEngine("agy", [{**FIX, ".github/workflows/ci.yml": "pwned\n"}])]
    with running(coder_world.service()) as addr:
        _, headers, _ = call(addr, {"op": "start", "job": job()})
        status = poll(addr, "j-12-1", headers[SESSION_HEADER])
    assert (status["status"], status["reason"]) == ("failed", "scope-violation")
    assert ".github/workflows/ci.yml" in status["detail"]
    assert coder_world.github.pulls == []


def test_agy_quota_on_both_engines_maps_to_agent_quota(coder_world: World) -> None:
    coder_world.engines = [ScriptedEngine("agy", [lambda root: QUOTA_RESTRICTED]),
                           ScriptedEngine("agy-unrestricted", [lambda root: QUOTA_UNRESTRICTED])]
    with running(coder_world.service()) as addr:
        _, headers, _ = call(addr, {"op": "start", "job": job()})
        status = poll(addr, "j-12-1", headers[SESSION_HEADER])
    assert (status["status"], status["reason"]) == ("failed", "agent-quota"), status


def test_bad_op_bad_json_and_unknown_job_are_client_errors(coder_world: World) -> None:
    with running(coder_world.service()) as addr:
        assert call(addr, {"op": "explode"})[0] == 400
        assert call(addr, b"{not json")[0] == 400
        code, _, body = call(addr, {"op": "status", "job_id": "j-404-1"})
        assert (code, body["error"]) == (404, "unknown_job")
        assert call(addr, {"op": "status"}, path="/elsewhere")[0] == 404


def test_a_malformed_session_id_is_refused(coder_world: World) -> None:
    with running(coder_world.service()) as addr:
        assert call(addr, {"op": "status", "job_id": "x"}, session="bad\r\nx-evil: 1")[0] == 400


def test_healthz_answers_without_a_token() -> None:
    with running(FakeCoder(), token="s3cret-token") as addr:
        conn = http.client.HTTPConnection(*addr, timeout=10)
        conn.request("GET", "/healthz")
        resp = conn.getresponse()
        assert (resp.status, json.loads(resp.read())) == (200, {"ok": True})


def test_token_is_required_when_configured() -> None:
    with running(FakeCoder(), token="s3cret-token") as addr:
        assert call(addr, {"op": "status", "job_id": "j-1-1"})[0] == 401
        assert call(addr, {"op": "status", "job_id": "j-1-1"}, headers={TOKEN_HEADER: "wrong"})[0] == 401
        assert call(addr, {"op": "status", "job_id": "j-1-1"}, headers={TOKEN_HEADER: "s3cret-token"})[0] == 404


def test_oversized_bodies_are_refused_unread() -> None:
    with running(FakeCoder()) as addr:
        conn = http.client.HTTPConnection(*addr, timeout=10)
        conn.putrequest("POST", "/invoke")
        conn.putheader("Content-Length", str(MAX_BODY_BYTES + 1))
        conn.endheaders()
        resp = conn.getresponse()
        assert resp.status == 413
        assert resp.getheader("Connection") == "close"


def test_a_body_without_content_length_is_refused() -> None:
    with running(FakeCoder()) as addr:
        conn = http.client.HTTPConnection(*addr, timeout=10)
        conn.putrequest("POST", "/invoke")
        conn.putheader("Transfer-Encoding", "chunked")
        conn.endheaders()
        assert conn.getresponse().status == 411


# -- FACTORY_MODE=fake ------------------------------------------------------------------------------------


def test_fake_mode_finishes_a_job_with_a_pr_after_n_status_polls() -> None:
    service = coder_service.build_service({"FACTORY_MODE": "fake", "FAKE_STATUS_POLLS": "2"})
    with running(service) as addr:
        code, headers, started = call(addr, {"op": "start", "job": job()})
        session = headers[SESSION_HEADER]
        assert (code, started["status"], started["session_id"]) == (200, "running", session)
        assert call(addr, {"op": "start", "job": job()}, session=session)[2]["status"] == "running"   # idempotent
        assert call(addr, {"op": "status", "job_id": "j-12-1"}, session=session)[2]["status"] == "running"
        done = call(addr, {"op": "status", "job_id": "j-12-1"}, session=session)[2]
        assert done["status"] == "succeeded"
        assert done["pr"]["number"] == 1012
        assert done["engine"] == "fake"
        assert {"phase", "reason", "cost", "log_tail", "iterations", "stale_s"} <= set(done)
        assert call(addr, {"op": "start", "job": job()}, session=session)[2]["status"] == "succeeded"

        call(addr, {"op": "start", "job": job(job_id="j-12-2")}, session=session)
        assert call(addr, {"op": "cancel", "job_id": "j-12-2"}, session=session)[2]["status"] == "cancelling"
        cancelled = call(addr, {"op": "status", "job_id": "j-12-2"}, session=session)[2]
        assert (cancelled["status"], cancelled["reason"]) == ("cancelled", "cancelled")

        assert call(addr, {"op": "start", "job": job(repo="someone/else")})[0] == 400
        assert call(addr, {"op": "status", "job_id": "j-9-9"})[0] == 404


def test_fake_mode_revise_reports_the_existing_pr() -> None:
    fake = FakeCoder(polls=1)
    fake.handle({"op": "start", "job": job(job_id="j-40-2", mode="revise", branch="agent/issue-40", tests=[],
                                           issue={"number": 40, "title": "t", "body": "b"}, pr={"number": 13})})
    assert fake.handle({"op": "status", "job_id": "j-40-2"})[1]["pr"]["number"] == 13


# -- local wiring: secrets from files, agy engines only, fail closed ----------------------------------------


def secrets_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    (tmp_path / "pat").write_text(PAT + "\n")
    (tmp_path / "agy").write_text('{"access_token":"ya29.SECRETAGY987654321"}\n')
    return {"HOME": str(tmp_path / "home"), "GITHUB_PAT_FILE": str(tmp_path / "pat"),
            "AGY_TOKEN_FILE": str(tmp_path / "agy"), "STATE_DIR": str(tmp_path / "state"),
            "WORKROOT": str(tmp_path / "work"), **extra}


def test_file_secrets_are_read_per_call_and_a_missing_one_never_shows_content(tmp_path: Path) -> None:
    secrets = local_wiring.FileSecrets(local_wiring.secret_paths(secrets_env(tmp_path)))
    assert secrets.get_secret("github-pat") == PAT
    (tmp_path / "pat").write_text("github_pat_ROTATED0123456789\n")
    assert secrets.get_secret("github-pat") == "github_pat_ROTATED0123456789"
    (tmp_path / "pat").unlink()
    with pytest.raises(local_wiring.SecretError, match="github-pat"):
        secrets.get_secret("github-pat")
    with pytest.raises(local_wiring.SecretError, match="unknown secret"):
        secrets.get_secret("storage-key")


def test_default_secret_paths_are_the_compose_secrets() -> None:
    assert local_wiring.secret_paths({}) == {"github-pat": Path("/run/secrets/github_pat"),
                                             "agy-cli-token": Path("/run/secrets/agy_cli_token")}


def test_local_service_fails_closed_without_the_engine_user(tmp_path: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("as root the engine user can be created")
    github = FakeGitHub()
    seen: list[str] = []
    service = local_wiring.build_local_service(secrets_env(tmp_path), repo=REPO,
                                               github=lambda pat: seen.append(pat) or github)
    code, resp = service.handle({"op": "start", "job": job()})
    assert code == 200, resp
    end = time.monotonic() + 30
    while (status := service.handle({"op": "status", "job_id": "j-12-1"})[1])["status"] == "running":
        assert time.monotonic() < end
        time.sleep(0.05)
    assert (status["status"], status["reason"]) == ("failed", "sandbox-unavailable")
    assert seen and set(seen) == {PAT}                       # the lease used the PAT read from the file
    assert "agent-lease/12" in github.branches
    assert (tmp_path / "state/j-12-1/state.json").is_file()    # job state lives on STATE_DIR
    assert PAT not in (tmp_path / "state/j-12-1/state.json").read_text()


def test_a_restart_marks_jobs_left_running_on_the_state_volume_interrupted(tmp_path: Path) -> None:
    env = secrets_env(tmp_path)
    state = tmp_path / "state/j-12-1/state.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"job_id": "j-12-1", "request": job(), "status": "running", "phase": "implement"}))
    service = local_wiring.build_local_service(env, repo=REPO, github=lambda pat: FakeGitHub())
    status = service.handle({"op": "status", "job_id": "j-12-1"})[1]
    assert (status["status"], status["reason"]) == ("failed", "interrupted")


def test_the_local_service_is_pinned_to_the_coder_repo(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=REPO):
        local_wiring.build_local_service(secrets_env(tmp_path), repo="someone/else")


def context(tmp_path: Path, run_as: RunAs | None, binary: Path | None = Path("/opt/agy/bin/agy")) -> EngineContext:
    from sdlc_agents.coder.job import JobSpec

    return EngineContext(JobSpec.from_request(job()), (), False, threading.Event(), {}, binary,
                         tmp_path / "agyhome", run_as, agy_log_dir=tmp_path / "logs")


def test_the_engine_chain_is_agy_then_unrestricted_agy_and_no_model_loop(tmp_path: Path) -> None:
    user = RunAs("agyuser", 1001, 1001, tmp_path / "agyhome")
    chain = local_wiring.agy_chain(context(tmp_path, user), {})
    assert [e.name for e in chain] == ["agy", "agy-unrestricted"]
    assert all(isinstance(e, AgyEngine) for e in chain)
    assert [e.name for e in local_wiring.agy_chain(context(tmp_path, RunAs("root", 0, 0, tmp_path)), {})] == ["agy"]
    assert local_wiring.agy_chain(context(tmp_path, user, binary=None), {}) == []


def test_proxy_and_ca_settings_reach_agy_and_nothing_else_does(tmp_path: Path) -> None:
    env = {"HTTPS_PROXY": "http://proxy.internal:3128", "SSL_CERT_FILE": "/etc/ssl/corp.pem",
           "GITHUB_PAT_FILE": "/run/secrets/github_pat", "CODER_SERVICE_TOKEN": "s3cret-token"}
    calls: list[dict[str, Any]] = []

    def record(cmd: list[str], **kw: Any) -> CommandResult:
        calls.append(kw["env"])
        return CommandResult(0, "ok")

    (engine,) = local_wiring.agy_chain(context(tmp_path, None), local_wiring.agy_extra_env(env), run=record)
    engine.edit("prompt", workdir=str(tmp_path), timeout_s=5)
    assert calls[0]["HTTPS_PROXY"] == "http://proxy.internal:3128"
    assert calls[0]["SSL_CERT_FILE"] == "/etc/ssl/corp.pem"
    assert not {"GITHUB_PAT_FILE", "CODER_SERVICE_TOKEN"} & set(calls[0])
    assert calls[0]["HOME"] == str(tmp_path / "agyhome")


def test_repo_defaults_from_the_factory_config_and_env_overrides_it(tmp_path: Path) -> None:
    assert coder_service.resolve_repo({"FACTORY_CONFIG": str(SERVICES.parent / "factory/factory.yaml")}) == REPO
    assert coder_service.resolve_repo({"REPO": "a/b"}) == "a/b"


def test_importing_the_service_pulls_in_no_azure_package() -> None:
    code = ("import sys, sdlc_factory.coder_service, sdlc_agents.coder.local_wiring; "
            "bad = [m for m in sys.modules if m.split('.')[0] in ('azure', 'starlette')]; "
            "sys.exit(f'imported {bad}' if bad else 0)")
    env = {**os.environ, "PYTHONPATH": f"{AGENTS}{os.pathsep}{SERVICES}"}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr + result.stdout
