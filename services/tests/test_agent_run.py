"""
POST /agent-run on the coder service: every prompt-agent agy call runs here, as the unprivileged engine
user, in a per-call empty cwd and HOME that are deleted afterwards. The client sends only the prompt, an
optional schema and a timeout; argv, env and the mode are built server-side.

The process runner and the engine user are injected, so the uid drop is observed without root. One test
runs the real default runner against a stand-in agy script as the current user.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import stat
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from sdlc_agents.coder.sandbox import RunAs
from sdlc_agents.coder.toolchain import AGY_AUTH_FILE

from sdlc_factory import coder_service
from sdlc_factory.coder_service import (
    AGENT_OUTPUT_BYTES,
    TOKEN_HEADER,
    FakeAgentRunner,
    FakeCoder,
    SandboxAgentRunner,
    serve,
)
from sdlc_factory.engines import AgyEngine, Outcome, ProcessOutput

AGY_TOKEN = '{"access_token":"ya29.AGENTRUNTOKEN"}'
SERVICE_TOKEN = "service-token-123"
RESULT = json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": "hello", "usage": {}}})


@contextmanager
def running(*, agent_runner: Any, token: str | None = SERVICE_TOKEN) -> Iterator[tuple[str, int]]:
    server = serve(FakeCoder(), host="127.0.0.1", port=0, token=token, agent_runner=agent_runner)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "127.0.0.1", server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def post(addr: tuple[str, int], body: Any, *, token: str | None = SERVICE_TOKEN) -> tuple[int, dict[str, Any]]:
    conn = http.client.HTTPConnection(*addr, timeout=30)
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers[TOKEN_HEADER] = token
    conn.request("POST", "/agent-run", body if isinstance(body, bytes) else json.dumps(body).encode(), headers)
    resp = conn.getresponse()
    data = json.loads(resp.read() or b"{}")
    conn.close()
    return resp.status, data


class Recorder:
    """A process runner that records what the sandbox handed it and what was on disk at that moment."""

    def __init__(self, output: ProcessOutput | None = None, *, gate: threading.Event | None = None,
                 entered: threading.Event | None = None, error: Exception | None = None):
        self.output = output or ProcessOutput(0, RESULT + "\n", "")
        self.gate, self.entered, self.error = gate, entered, error
        self.calls: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def __call__(self, argv, *, cwd, env, timeout_s, abort_on, user) -> ProcessOutput:
        home = Path(env["HOME"])
        token = home / AGY_AUTH_FILE
        schema = Path(argv[argv.index("--json-schema") + 1]) if "--json-schema" in argv else None
        with self.lock:
            self.calls.append({
                "argv": argv, "cwd": Path(cwd), "home": home, "env": env, "timeout_s": timeout_s, "user": user,
                "cwd_entries": sorted(p.name for p in Path(cwd).iterdir()),
                "token": token.read_text() if token.is_file() else None,
                "token_mode": stat.S_IMODE(token.lstat().st_mode) if token.is_file() else None,
                "token_owner": token.lstat().st_uid if token.is_file() else None,
                "schema": json.loads(schema.read_text()) if schema else None,
            })
        if self.entered is not None:
            self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(30)
        if self.error is not None:
            raise self.error
        return self.output


def me(tmp_path: Path) -> RunAs:
    return RunAs("agyuser", os.getuid(), os.getgid(), tmp_path / "agyuser-home")


def sandbox(tmp_path: Path, process: Any, **kw: Any) -> SandboxAgentRunner:
    kw.setdefault("engine_user", lambda: me(tmp_path))
    return SandboxAgentRunner(binary=Path("/opt/agy/bin/agy"), read_token=lambda: AGY_TOKEN, process=process,
                              root=tmp_path / "runs", **kw)


# -- auth and request shape ------------------------------------------------------------------------------


def test_agent_run_requires_the_service_token(tmp_path: Path) -> None:
    process = Recorder()
    with running(agent_runner=sandbox(tmp_path, process)) as addr:
        assert post(addr, {"prompt": "p", "schema": None, "timeout_s": 5}, token=None)[0] == 401
        assert post(addr, {"prompt": "p", "schema": None, "timeout_s": 5}, token="wrong")[0] == 401
        assert post(addr, {"prompt": "p", "schema": None, "timeout_s": 5})[0] == 200
    assert len(process.calls) == 1


def test_the_token_is_checked_before_the_body_is_read(tmp_path: Path) -> None:
    with running(agent_runner=sandbox(tmp_path, Recorder())) as addr:
        sock = socket.create_connection(addr, timeout=5)
        # A body is announced but never sent: a server that read it first would block, not answer.
        sock.sendall(b"POST /agent-run HTTP/1.1\r\nHost: x\r\nContent-Length: 5000\r\n\r\n")
        reply = sock.recv(4096).decode()
        sock.close()
    assert reply.startswith("HTTP/1.1 401"), reply


@pytest.mark.parametrize("body", [
    {"prompt": "p", "schema": None, "timeout_s": 5, "argv": ["/bin/sh", "-c", "id"]},
    {"prompt": "p", "schema": None, "timeout_s": 5, "env": {"LD_PRELOAD": "/tmp/x.so"}},
    {"prompt": "p", "schema": None, "timeout_s": 5, "mode": "accept-edits"},
    {"prompt": "p", "schema": None, "timeout_s": 5, "flags": ["--dangerously-skip-permissions"]},
    {"prompt": "", "schema": None, "timeout_s": 5},
    {"prompt": "x" * 100_001, "schema": None, "timeout_s": 5},
    {"prompt": 7, "schema": None, "timeout_s": 5},
    {"prompt": "p", "schema": [], "timeout_s": 5},
    {"prompt": "p", "schema": None, "timeout_s": 0},
    {"prompt": "p", "schema": None, "timeout_s": 901},
    {"prompt": "p", "schema": None, "timeout_s": True},
    {"prompt": "p", "schema": None, "timeout_s": 5.5},
    {"schema": None, "timeout_s": 5},
    [],
], ids=["argv", "env", "mode", "flags", "empty-prompt", "long-prompt", "prompt-type", "schema-type",
        "timeout-0", "timeout-901", "timeout-bool", "timeout-float", "no-prompt", "not-object"])
def test_anything_but_prompt_schema_and_timeout_is_refused(tmp_path: Path, body: Any) -> None:
    process = Recorder()
    with running(agent_runner=sandbox(tmp_path, process)) as addr:
        code, reply = post(addr, body)
    assert code == 400, reply
    assert reply["error"] == "invalid_request"
    assert process.calls == []


def test_a_body_that_is_not_json_is_refused(tmp_path: Path) -> None:
    with running(agent_runner=sandbox(tmp_path, Recorder())) as addr:
        assert post(addr, b"{nope")[0] == 400


def test_without_an_agent_runner_the_route_does_not_exist() -> None:
    with running(agent_runner=None) as addr:
        assert post(addr, {"prompt": "p", "schema": None, "timeout_s": 5})[0] == 404


# -- what runs, as whom, where ---------------------------------------------------------------------------


def test_the_server_builds_a_plan_mode_argv_and_drops_to_the_engine_user(tmp_path: Path) -> None:
    process = Recorder()
    schema = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}
    with running(agent_runner=sandbox(tmp_path, process)) as addr:
        code, reply = post(addr, {"prompt": "PROMPT-TEXT", "schema": schema, "timeout_s": 42})
    assert code == 200, reply
    (call,) = process.calls
    argv = call["argv"]
    assert argv[0] == "/opt/agy/bin/agy"
    assert argv[argv.index("-p") + 1] == "PROMPT-TEXT"
    assert argv[argv.index("--mode") + 1] == "plan"
    assert argv[argv.index("--print-timeout") + 1] == "42s"
    assert "--dangerously-skip-permissions" not in argv
    assert call["schema"] == schema
    assert call["timeout_s"] > 42                       # the hard kill comes after agy's own timeout
    assert call["user"] == me(tmp_path)
    assert reply == {"returncode": 0, "stdout": RESULT + "\n", "stderr": "", "timed_out": False,
                     "duration_s": reply["duration_s"]}
    assert isinstance(reply["duration_s"], float)


def test_env_is_built_from_nothing_with_only_the_proxy_settings_passed(tmp_path: Path,
                                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://egress-proxy:3128")
    monkeypatch.setenv("SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt")
    monkeypatch.setenv("CODER_SERVICE_TOKEN", "must-not-leak")
    monkeypatch.setenv("GITHUB_PAT_FILE", "/run/secrets/github_pat")
    process = Recorder()
    with running(agent_runner=sandbox(tmp_path, process)) as addr:
        post(addr, {"prompt": "p", "schema": None, "timeout_s": 5})
    env = process.calls[0]["env"]
    assert env["HTTPS_PROXY"] == "http://egress-proxy:3128"
    assert env["SSL_CERT_FILE"] == "/etc/ssl/certs/ca-certificates.crt"
    assert not {"CODER_SERVICE_TOKEN", "GITHUB_PAT_FILE", "AGY_TOKEN_FILE"} & set(env)
    assert env["HOME"] == str(process.calls[0]["home"])


def test_each_call_gets_a_fresh_empty_cwd_and_home_with_a_private_token_copy_both_deleted(tmp_path: Path) -> None:
    process = Recorder()
    with running(agent_runner=sandbox(tmp_path, process)) as addr:
        post(addr, {"prompt": "a", "schema": None, "timeout_s": 5})
        post(addr, {"prompt": "b", "schema": None, "timeout_s": 5})
    first, second = process.calls
    for call in (first, second):
        assert call["cwd_entries"] == []
        assert call["token"] == AGY_TOKEN and call["token_mode"] == 0o600
        assert call["token_owner"] == os.getuid()
        assert not call["cwd"].exists() and not call["home"].exists()
    assert first["home"] != second["home"] and first["cwd"] != second["cwd"]
    assert list((tmp_path / "runs").iterdir()) == []


def test_the_call_dirs_are_deleted_when_the_process_runner_fails(tmp_path: Path) -> None:
    process = Recorder(error=OSError("boom"))
    with running(agent_runner=sandbox(tmp_path, process)) as addr:
        code, reply = post(addr, {"prompt": "a", "schema": None, "timeout_s": 5})
    assert code == 500 and reply["error"] == "internal_error"
    assert not process.calls[0]["home"].exists()
    assert list((tmp_path / "runs").iterdir()) == []


def test_without_an_engine_user_nothing_runs(tmp_path: Path) -> None:
    process = Recorder()
    root = RunAs("root", 0, 0, Path("/root"))
    for user in (None, root):
        with running(agent_runner=sandbox(tmp_path, process, engine_user=lambda u=user: u)) as addr:
            code, reply = post(addr, {"prompt": "a", "schema": None, "timeout_s": 5})
        assert (code, reply["error"]) == (500, "sandbox_unavailable")
    assert process.calls == []


def test_an_unreadable_token_is_a_setup_error_and_nothing_runs(tmp_path: Path) -> None:
    def no_token() -> str:
        raise OSError("gone")

    process = Recorder()
    runner = SandboxAgentRunner(binary=Path("/opt/agy/bin/agy"), read_token=no_token, process=process,
                                root=tmp_path / "runs", engine_user=lambda: me(tmp_path))
    with running(agent_runner=runner) as addr:
        code, reply = post(addr, {"prompt": "a", "schema": None, "timeout_s": 5})
    assert (code, reply["error"]) == (500, "token_unavailable")
    assert "ya29" not in json.dumps(reply)
    assert process.calls == []
    assert not (tmp_path / "runs").exists()          # nothing was even provisioned


def test_concurrency_is_capped_and_the_overflow_is_told_to_retry(tmp_path: Path) -> None:
    gate = threading.Event()
    process = Recorder(gate=gate)
    runner = sandbox(tmp_path, process, concurrency=2, queue_wait_s=0.2)
    results: list[int] = []
    with running(agent_runner=runner) as addr:
        workers = [threading.Thread(target=lambda: results.append(post(addr, {"prompt": "x", "schema": None,
                                                                               "timeout_s": 5})[0]))
                   for _ in range(2)]
        for w in workers:
            w.start()
        end = time.monotonic() + 10
        while len(process.calls) < 2 and time.monotonic() < end:
            time.sleep(0.02)
        assert len(process.calls) == 2
        code, reply = post(addr, {"prompt": "third", "schema": None, "timeout_s": 5})
        assert (code, reply["error"]) == (429, "busy")
        gate.set()
        for w in workers:
            w.join(30)
        assert post(addr, {"prompt": "after", "schema": None, "timeout_s": 5})[0] == 200
    assert sorted(results) == [200, 200]


def test_a_timeout_is_reported(tmp_path: Path) -> None:
    process = Recorder(ProcessOutput(124, "partial", "[agy] print timeout after 5s\n"))
    with running(agent_runner=sandbox(tmp_path, process)) as addr:
        code, reply = post(addr, {"prompt": "a", "schema": None, "timeout_s": 5})
    assert code == 200 and reply["timed_out"] is True and reply["returncode"] == 124


def test_streams_are_cut_to_2_mib_at_a_line_boundary_keeping_the_tail(tmp_path: Path) -> None:
    line = "x" * 1023 + "\n"
    big = line * 3000 + RESULT + "\n"     # about 3 MiB, the result event last
    process = Recorder(ProcessOutput(0, big, line * 3000))
    with running(agent_runner=sandbox(tmp_path, process)) as addr:
        code, reply = post(addr, {"prompt": "a", "schema": None, "timeout_s": 5})
    assert code == 200
    for name in ("stdout", "stderr"):
        assert len(reply[name].encode()) <= AGENT_OUTPUT_BYTES
        assert big.endswith(reply[name]) or (line * 3000).endswith(reply[name])
        assert reply[name].startswith("x")    # never half a line
    assert reply["stdout"].endswith(RESULT + "\n")


def test_the_default_runner_runs_the_engine_as_the_given_user_in_the_sandbox(tmp_path: Path) -> None:
    """The real process path: a stand-in agy prints its uid, cwd listing and token into a result event."""
    fake_agy = tmp_path / "bin" / "agy"
    fake_agy.parent.mkdir()
    fake_agy.write_text(
        "#!/bin/sh\n"
        'resp=$(printf "uid=%s cwd=[%s] token=%s" "$(id -u)" "$(ls -A)" '
        '"$(cat "$HOME/.gemini/antigravity-cli/antigravity-oauth-token")")\n'
        "printf '{\"event\":\"result\",\"result\":{\"status\":\"SUCCESS\",\"response\":\"%s\"}}\\n' \"$resp\"\n")
    fake_agy.chmod(0o755)
    assert AGY_AUTH_FILE == ".gemini/antigravity-cli/antigravity-oauth-token"
    runner = SandboxAgentRunner(binary=fake_agy, read_token=lambda: "TOKEN-COPY", root=tmp_path / "runs",
                                engine_user=lambda: me(tmp_path))
    with running(agent_runner=runner) as addr:
        code, reply = post(addr, {"prompt": "hello", "schema": None, "timeout_s": 10})
    assert code == 200, reply
    result = AgyEngine(binary=fake_agy).classify(reply["returncode"], reply["stdout"], reply["stderr"])
    assert result.outcome is Outcome.OK, reply
    assert result.text == f"uid={os.getuid()} cwd=[] token=TOKEN-COPY"
    assert list((tmp_path / "runs").iterdir()) == []


# -- FACTORY_MODE=fake -----------------------------------------------------------------------------------


@pytest.mark.parametrize(("schema", "text"), [
    (None, FakeAgentRunner.TEXT),
    ({"type": "object"}, "{}"),
    ({"type": "object", "properties": {"a": {"type": "string"}}}, "{}"),
    ({"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}}, FakeAgentRunner.TEXT),
])
def test_fake_mode_answers_a_valid_result_event(schema: Any, text: str) -> None:
    runner = coder_service.build_agent_runner({"FACTORY_MODE": "fake"})
    assert isinstance(runner, FakeAgentRunner)
    with running(agent_runner=runner) as addr:
        code, reply = post(addr, {"prompt": "p", "schema": schema, "timeout_s": 5})
        assert post(addr, {"prompt": "p", "schema": None, "timeout_s": 5, "argv": ["x"]})[0] == 400
    assert code == 200, reply
    result = AgyEngine(binary=Path("agy")).classify(reply["returncode"], reply["stdout"], reply["stderr"])
    assert (result.outcome, result.text) == (Outcome.OK, text)
    assert reply["timed_out"] is False


# -- composition and startup -----------------------------------------------------------------------------


def test_live_agent_runner_reads_its_settings_from_env(tmp_path: Path) -> None:
    runner = coder_service.build_agent_runner({"AGENT_RUN_CONCURRENCY": "3", "AGY_BINARY": "/x/agy",
                                               "AGY_TOKEN_FILE": str(tmp_path / "tok")})
    assert isinstance(runner, SandboxAgentRunner)
    assert runner.concurrency == 3
    assert coder_service.build_agent_runner({}).concurrency == 2
    for bad in ("0", "-1", "two"):
        with pytest.raises(ValueError, match="AGENT_RUN_CONCURRENCY"):
            coder_service.build_agent_runner({"AGENT_RUN_CONCURRENCY": bad})


def test_live_mode_refuses_to_start_without_a_service_token() -> None:
    for env in ({}, {"FACTORY_MODE": "live"}, {"FACTORY_MODE": "live", "CODER_SERVICE_TOKEN": "  "}):
        with pytest.raises(SystemExit, match="CODER_SERVICE_TOKEN"):
            coder_service.main(env)


def test_fake_mode_may_start_without_a_service_token(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[Any] = []

    class Stop(Exception):
        pass

    def fake_serve(service: Any, **kw: Any) -> Any:
        started.append(kw)
        raise Stop

    monkeypatch.setattr(coder_service, "serve", fake_serve)
    with pytest.raises(Stop):
        coder_service.main({"FACTORY_MODE": "fake", "CODER_HOST": "127.0.0.1", "CODER_PORT": "0"})
    assert started[0]["token"] is None
    assert started[0]["host"] == "127.0.0.1"
    assert isinstance(started[0]["agent_runner"], FakeAgentRunner)


# -- review follow-ups -----------------------------------------------------------------------------------


def test_agent_runs_use_their_own_user_not_the_coder_jobs_agyuser() -> None:
    from sdlc_factory import agent_run

    entry = type("pw", (), {"pw_uid": 61001, "pw_gid": 61001, "pw_dir": "/nonexistent"})
    assert agent_run.ensure_agent_user(euid=lambda: 1000, getpwnam=lambda name: entry) is None
    user = agent_run.ensure_agent_user(euid=lambda: 0, getpwnam=lambda name: entry)
    assert user is not None and (user.name, user.uid) == ("agyagent", 61001)

    def missing(name: str) -> Any:
        raise KeyError(name)

    assert agent_run.ensure_agent_user(euid=lambda: 0, getpwnam=missing) is None
    assert agent_run.AGENT_USER != "agyuser"


def test_leftover_engine_processes_are_reaped_when_the_last_run_ends(tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    from sdlc_factory import agent_run

    monkeypatch.setattr(agent_run.os, "geteuid", lambda: 0)   # as if root: the engine uid is then not ours
    reaped: list[tuple[RunAs, int]] = []
    gate = threading.Event()
    process = Recorder(gate=gate)
    runner = sandbox(tmp_path, process, concurrency=2, reap=lambda u: reaped.append((u, len(process.calls))) or 0)
    with running(agent_runner=runner) as addr:
        first = threading.Thread(target=post, args=(addr, {"prompt": "a", "schema": None, "timeout_s": 5}))
        first.start()
        end = time.monotonic() + 10
        while not process.calls and time.monotonic() < end:
            time.sleep(0.02)
        second = threading.Thread(target=post, args=(addr, {"prompt": "b", "schema": None, "timeout_s": 5}))
        second.start()
        while len(process.calls) < 2 and time.monotonic() < end:
            time.sleep(0.02)
        gate.set()
        first.join(30)
        second.join(30)
    assert [u for u, _ in reaped] == [me(tmp_path)]    # once, after both: never under a sibling still running


def test_the_engine_users_own_uid_is_never_reaped(tmp_path: Path) -> None:
    reaped: list[RunAs] = []
    with running(agent_runner=sandbox(tmp_path, Recorder(), reap=lambda u: reaped.append(u) or 0)) as addr:
        assert post(addr, {"prompt": "a", "schema": None, "timeout_s": 5})[0] == 200
    assert reaped == []


def test_the_prompt_is_capped_in_bytes_for_the_argv_limit(tmp_path: Path) -> None:
    process = Recorder()
    with running(agent_runner=sandbox(tmp_path, process)) as addr:
        code, reply = post(addr, {"prompt": "é" * 70_000, "schema": None, "timeout_s": 5})   # 140 KB
    assert (code, reply["error"]) == (400, "invalid_request")
    assert process.calls == []


def test_tmpdir_is_inside_the_per_call_home(tmp_path: Path) -> None:
    process = Recorder()
    with running(agent_runner=sandbox(tmp_path, process)) as addr:
        post(addr, {"prompt": "a", "schema": None, "timeout_s": 5})
    env = process.calls[0]["env"]
    assert env["TMPDIR"] == str(process.calls[0]["home"] / "tmp")


def test_a_tail_without_a_newline_is_kept_not_dropped() -> None:
    from sdlc_factory.agent_run import tail_lines

    assert tail_lines("a" * 100, limit=10) == "a" * 10
    assert tail_lines("x\n" + "a" * 100, limit=10) == "a" * 10


def test_a_401_is_delivered_even_when_the_client_sent_a_large_body(tmp_path: Path) -> None:
    with running(agent_runner=sandbox(tmp_path, Recorder())) as addr:
        conn = http.client.HTTPConnection(*addr, timeout=10)
        conn.request("POST", "/agent-run", b'{"prompt": "' + b"x" * 500_000 + b'"}',
                     {"Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 401
        assert json.loads(resp.read()) == {"error": "unauthorized"}
