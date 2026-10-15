"""Engines edit the working copy and nothing else; the model loop enforces scope on its own writes."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from sdlc_agents.coder import shell
from sdlc_agents.coder.engines import (
    AGY_RESTRICTED_CALL_TIMEOUT_S,
    AGY_UNRESTRICTED_CALL_TIMEOUT_S,
    AgyEngine,
    ModelLoopEngine,
    ModelReply,
    ResponsesClient,
    ResponsesError,
)
from sdlc_agents.coder.sandbox import RunAs
from sdlc_agents.ports import CommandResult
from sdlc_agents.transport import HttpRequest, HttpResponse


def test_agy_runs_headless_without_shell_permission_and_with_a_scrubbed_env(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("IDENTITY_ENDPOINT", "IDENTITY_HEADER", "AZURE_CLIENT_ID", "FOUNDRY_PROJECT_ENDPOINT",
                "KEY_VAULT_URI", "GITHUB_TOKEN", "GIT_ASKPASS", "APPLICATIONINSIGHTS_CONNECTION_STRING"):
        monkeypatch.setenv(key, "must-not-leak")
    monkeypatch.setenv("LANG", "C.UTF-8")
    fake = tmp_path / "bin" / "agy"
    fake.parent.mkdir()
    fake.write_text(f"#!{sys.executable}\nimport sys, os, pathlib, json\n"
                    "pathlib.Path('argv.json').write_text(json.dumps(sys.argv[1:]))\n"
                    "pathlib.Path('env.json').write_text(json.dumps(dict(os.environ)))\n")
    fake.chmod(0o755)
    work = tmp_path / "work"
    work.mkdir()
    agy_home = tmp_path / "agy-home"
    result = AgyEngine(fake, home=agy_home).edit("make tests pass", workdir=str(work), timeout_s=30)
    assert result.returncode == 0
    # No --sandbox: agy's own sandbox blocked every command (job j-10-1); the engine user is the isolation.
    assert json.loads((work / "argv.json").read_text()) == ["-p", "make tests pass", "--mode", "accept-edits"]
    env = json.loads((work / "env.json").read_text())
    assert "must-not-leak" not in env.values()
    assert set(env) <= {"PATH", "HOME", "LANG", "TERM", "TMPDIR", "PWD", "SHLVL", "_", "__CF_USER_TEXT_ENCODING"}
    assert env["HOME"] == str(agy_home)
    assert env["LANG"] == "C.UTF-8"
    assert env["PATH"].startswith(f"{fake.parent}:")


def test_agy_as_an_unprivileged_user_hands_it_the_checkout_first(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    prepared: list[Path] = []

    def run(cmd: list[str], **kwargs: Any) -> CommandResult:
        calls.append({"cmd": cmd, **kwargs})
        return CommandResult(0, "ok")

    user = RunAs(name="agyuser", uid=1001, gid=1001, home=Path("/home/agyuser"))
    reaped: list[RunAs] = []
    engine = AgyEngine(Path("/usr/local/bin/agy"), home=user.home, run_as=user, run=run, prepare=prepared.append,
                       reap=lambda u: reaped.append(u) or 0)
    assert engine.edit("p", workdir=str(tmp_path), timeout_s=5).returncode == 0
    assert reaped == [user]
    assert prepared == [tmp_path]
    assert calls[0]["user"] == 1001
    assert calls[0]["group"] == 1001
    assert calls[0]["env"]["HOME"] == "/home/agyuser"


def test_agy_timeout_is_a_failed_edit(tmp_path: Path) -> None:
    fake = tmp_path / "agy"
    fake.write_text("#!/bin/sh\nsleep 30\n")
    fake.chmod(0o755)
    result = AgyEngine(fake, home=tmp_path).edit("p", workdir=str(tmp_path), timeout_s=1)
    assert result.returncode == shell.TIMEOUT_RC


def test_agy_prompt_is_capped_below_the_kernel_argument_limit(tmp_path: Path) -> None:
    fake = tmp_path / "agy"
    fake.write_text(f"#!{sys.executable}\nimport sys\nprint(len(sys.argv[2]))\n")
    fake.chmod(0o755)
    result = AgyEngine(fake, home=tmp_path).edit("x" * 500_000, workdir=str(tmp_path), timeout_s=30)
    assert result.returncode == 0
    assert int(result.output.strip()) <= 100_000


class ScriptedClient:
    def __init__(self, replies: list[Any]):
        self.replies = replies
        self.calls: list[list[dict[str, str]]] = []

    def create(self, *, instructions: str, input_items: list[dict[str, str]], schema: dict[str, Any]) -> ModelReply:
        self.calls.append(list(input_items))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ModelReply(text=reply if isinstance(reply, str) else json.dumps(reply), input_tokens=1000,
                          output_tokens=200)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    files = {
        "app/web/tests/eta.test.ts": "import { eta } from '../src/eta';\nimport x from './helper.js';\n",
        "app/web/tests/helper.ts": "export default 1;\n",
        "app/web/src/eta.ts": "export const eta = () => null;\n",
        "app/node_modules/big/index.js": "ignored",
        ".github/workflows/ci.yml": "on: push\n",
    }
    for rel, content in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(content)
    return tmp_path


def _engine(client: ScriptedClient, *, tests_only: bool = False) -> ModelLoopEngine:
    return ModelLoopEngine(client, allowed_paths=("app/",), protected=("app/web/tests/eta.test.ts",),
                           tests_only=tests_only)


def test_model_loop_reads_then_writes_only_allowed_files(checkout: Path) -> None:
    client = ScriptedClient([
        {"edits": [], "read": ["app/web/src/eta.ts", "../../etc/passwd", ".github/workflows/ci.yml"], "note": ""},
        {"edits": [
            {"path": "app/web/src/eta.ts", "content": "export const eta = () => '2026-10-12';\n"},
            {"path": "app/web/src/new/view.ts", "content": "export {};\n"},
            {"path": ".github/workflows/ci.yml", "content": "pwned"},
            {"path": "app/web/tests/eta.test.ts", "content": "weakened"},
        ], "read": [], "note": "done"},
    ])
    engine = _engine(client)
    result = engine.edit("make it pass", workdir=str(checkout), timeout_s=60)
    assert result.returncode == 0
    assert (checkout / "app/web/src/eta.ts").read_text().endswith("'2026-10-12';\n")
    assert (checkout / "app/web/src/new/view.ts").exists()
    assert (checkout / ".github/workflows/ci.yml").read_text() == "on: push\n"
    assert (checkout / "app/web/tests/eta.test.ts").read_text().startswith("import")
    assert "rejected" in result.output
    assert ".github/workflows/ci.yml" in result.output
    first = client.calls[0][0]["content"]
    assert "app/web/src/eta.ts" in first
    assert "export const eta = () => null" in first
    assert "export default 1" in first                                                  # ./helper.js -> helper.ts
    assert "node_modules" not in first
    served = client.calls[1][-1]["content"]
    assert "export const eta" in served
    assert "not readable" in served
    assert engine.usage.input_tokens == 2000
    assert engine.usage.output_tokens == 400


def test_model_loop_in_maintenance_mode_writes_only_tests(checkout: Path) -> None:
    client = ScriptedClient([{"edits": [{"path": "app/web/src/eta.ts", "content": "x"},
                                        {"path": "app/web/tests/other.test.ts", "content": "ok"}],
                              "read": [], "note": ""}])
    engine = ModelLoopEngine(client, allowed_paths=("app/",), protected=(), tests_only=True)
    result = engine.edit("repair", workdir=str(checkout), timeout_s=60)
    assert result.returncode == 0
    assert (checkout / "app/web/src/eta.ts").read_text() == "export const eta = () => null;\n"
    assert (checkout / "app/web/tests/other.test.ts").read_text() == "ok"


@pytest.mark.parametrize("reply", [ResponsesError("429 rate limited"), "not json", json.dumps({"edits": "x"})])
def test_model_loop_failures_are_engine_failures(checkout: Path, reply: Any) -> None:
    result = _engine(ScriptedClient([reply])).edit("p", workdir=str(checkout), timeout_s=60)
    assert result.returncode == 1
    assert "model loop failed" in result.output


def test_model_loop_without_edits_is_a_successful_no_op(checkout: Path) -> None:
    reads = {"edits": [], "read": ["app/web/src/eta.ts"], "note": ""}
    result = _engine(ScriptedClient([reads, reads, reads])).edit("p", workdir=str(checkout), timeout_s=60)
    assert result.returncode == 0
    assert "no edits" in result.output
    result = _engine(ScriptedClient([{"edits": [], "read": [], "note": "cannot"}])).edit(
        "p", workdir=str(checkout), timeout_s=60)
    assert result.returncode == 0
    assert "cannot" in result.output


def test_model_loop_stops_at_its_deadline(checkout: Path) -> None:
    result = _engine(ScriptedClient([])).edit("p", workdir=str(checkout), timeout_s=0)
    assert result.returncode == 1
    assert "deadline" in result.output


class FakeTransport:
    def __init__(self, responses: list[tuple[int, dict[str, str], bytes]]):
        self.responses = responses
        self.requests: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    def __call__(self, request: HttpRequest) -> HttpResponse:
        assert request.method == "POST"
        assert request.body is not None
        self.requests.append((request.url, json.loads(request.body), request.headers))
        return HttpResponse(*self.responses.pop(0))


def _ok_body(text: str) -> bytes:
    return json.dumps({"status": "completed", "output": [
        {"type": "reasoning", "summary": []},
        {"type": "message", "content": [{"type": "output_text", "text": text}]},
    ], "usage": {"input_tokens": 11, "output_tokens": 7}}).encode()


def test_responses_client_posts_to_the_project_openai_endpoint_and_retries_429() -> None:
    transport = FakeTransport([(429, {"retry-after": "2"}, b"{}"), (200, {}, _ok_body('{"edits":[]}'))])
    sleeps: list[float] = []
    client = ResponsesClient("https://acct.services.ai.azure.com/api/projects/proj/", "sdlc-default",
                             token_provider=lambda: "tok", transport=transport, sleep=sleeps.append)
    reply = client.create(instructions="i", input_items=[{"role": "user", "content": "u"}], schema={"type": "object"})
    assert reply == ModelReply('{"edits":[]}', 11, 7)
    url, body, headers = transport.requests[0]
    assert url == "https://acct.services.ai.azure.com/api/projects/proj/openai/v1/responses"
    assert headers["Authorization"] == "Bearer tok"
    assert body["model"] == "sdlc-default"
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["store"] is False
    assert sleeps == [2.0]


def test_responses_client_raises_on_errors_and_incomplete_output() -> None:
    client = ResponsesClient("https://x/api/projects/p", "d", token_provider=lambda: "t",
                             transport=FakeTransport([(401, {}, b'{"error":{"message":"no"}}')]), sleep=lambda s: None)
    with pytest.raises(ResponsesError, match="401"):
        client.create(instructions="i", input_items=[], schema={})
    incomplete = json.dumps({"status": "incomplete", "output": [], "usage": {}}).encode()
    client = ResponsesClient("https://x/api/projects/p", "d", token_provider=lambda: "t",
                             transport=FakeTransport([(200, {}, incomplete)]), sleep=lambda s: None)
    with pytest.raises(ResponsesError, match="incomplete"):
        client.create(instructions="i", input_items=[], schema={})
    busy = [(429, {}, b"{}")] * 4
    client = ResponsesClient("https://x/api/projects/p", "d", token_provider=lambda: "t",
                             transport=FakeTransport(busy), sleep=lambda s: None)
    with pytest.raises(ResponsesError, match="429"):
        client.create(instructions="i", input_items=[], schema={})


@pytest.fixture
def hostile_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    (root / "app/src").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / ".git/config").write_text("[core]\n")
    (root / "app/src/ok.ts").write_text("ok\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("TOPSECRET\n")
    (root / "app/link").symlink_to(outside)
    (root / "app/secret.ts").symlink_to(outside / "secret.txt")
    return root


ESCAPES = ["../outside/secret.txt", "/etc/passwd", "app/link/secret.txt", "app/secret.ts",
           "app/src/../../../outside/secret.txt", "app/../.git/config", ".git/config",
           "app\\src\\ok.ts", "app/src/ok.ts\x00.png"]


@pytest.mark.parametrize("path", ESCAPES)
def test_model_loop_never_reads_outside_the_checkout(hostile_checkout: Path, path: str) -> None:
    engine = ModelLoopEngine(ScriptedClient([]), allowed_paths=(".",), protected=(), tests_only=False)
    served = engine._read(hostile_checkout, [path])
    assert "TOPSECRET" not in served
    assert "[core]" not in served
    assert "not readable" in served


@pytest.mark.parametrize("path", ESCAPES)
def test_model_loop_never_writes_outside_the_checkout(hostile_checkout: Path, path: str) -> None:
    reply = {"edits": [{"path": path, "content": "PWNED"}], "read": [], "note": ""}
    engine = ModelLoopEngine(ScriptedClient([reply]), allowed_paths=(".",), protected=(), tests_only=False)
    result = engine.edit("p", workdir=str(hostile_checkout), timeout_s=60)
    assert result.returncode == 0
    assert "rejected" in result.output
    assert (hostile_checkout.parent / "outside/secret.txt").read_text() == "TOPSECRET\n"
    assert (hostile_checkout / ".git/config").read_text() == "[core]\n"
    assert not list(hostile_checkout.parent.rglob("*PWNED*"))
    assert all("PWNED" not in f.read_text() for f in hostile_checkout.parent.rglob("*")
               if f.is_file() and not f.is_symlink())


def test_model_loop_scope_is_case_sensitive(hostile_checkout: Path) -> None:
    reply = {"edits": [{"path": "App/src/ok.ts", "content": "PWNED"}], "read": [], "note": ""}
    engine = ModelLoopEngine(ScriptedClient([reply]), allowed_paths=("app/",), protected=(), tests_only=False)
    assert "rejected ['App/src/ok.ts']" in engine.edit("p", workdir=str(hostile_checkout), timeout_s=60).output
    assert (hostile_checkout / "app/src/ok.ts").read_text() == "ok\n"


def _fake_agy(tmp_path: Path, body: str) -> Path:
    fake = tmp_path / "bin" / "agy"
    fake.parent.mkdir(exist_ok=True)
    fake.write_text(f"#!{sys.executable}\nimport sys, time, pathlib\n"
                    f"calls = pathlib.Path({str(tmp_path / 'calls')!r})\n"
                    "calls.write_text(calls.read_text() + 'x' if calls.exists() else 'x')\n" + body)
    fake.chmod(0o755)
    return fake


def test_agy_waiting_for_a_login_is_killed_at_once_and_fails(tmp_path: Path) -> None:
    fake = _fake_agy(tmp_path, "print('Authentication required. Please visit the URL to log in:', flush=True)\n"
                               "print('https://accounts.example/x', flush=True)\ntime.sleep(60)\n")
    started = time.monotonic()
    result = AgyEngine(fake, home=tmp_path).edit("p", workdir=str(tmp_path), timeout_s=120)
    assert result.returncode == shell.ABORTED_RC
    assert "authentication" in result.output
    assert time.monotonic() - started < 15


def test_agy_quota_message_aborts_only_without_edits(tmp_path: Path) -> None:
    fake = _fake_agy(tmp_path, "print('error: Individual quota reached. Please upgrade your subscription to increase your limits. Resets in 19h13m22s.', flush=True)\ntime.sleep(60)\n")
    assert AgyEngine(fake, home=tmp_path, dirty=lambda: False).edit(
        "p", workdir=str(tmp_path), timeout_s=120).returncode == shell.ABORTED_RC
    finishing = _fake_agy(tmp_path, "print('retrying after 429', flush=True)\ntime.sleep(1)\nprint('done')\n")
    result = AgyEngine(finishing, home=tmp_path, dirty=lambda: True).edit("p", workdir=str(tmp_path), timeout_s=120)
    assert result.returncode == 0


def test_agy_timeout_without_edits_is_retried_once_then_fails(tmp_path: Path) -> None:
    fake = _fake_agy(tmp_path, "time.sleep(60)\n")
    result = AgyEngine(fake, home=tmp_path, call_timeout_s=1, dirty=lambda: False).edit(
        "p", workdir=str(tmp_path), timeout_s=120)
    assert result.returncode == shell.TIMEOUT_RC
    assert (tmp_path / "calls").read_text() == "xx"


def test_agy_timeout_after_edits_keeps_them_for_the_test_run(tmp_path: Path) -> None:
    fake = _fake_agy(tmp_path, "time.sleep(60)\n")
    result = AgyEngine(fake, home=tmp_path, call_timeout_s=1, dirty=lambda: True).edit(
        "p", workdir=str(tmp_path), timeout_s=120)
    assert result.returncode == 0
    assert "keeping them" in result.output
    assert (tmp_path / "calls").read_text() == "x"


def test_model_loop_does_not_block_on_a_fifo(hostile_checkout: Path) -> None:
    os.mkfifo(hostile_checkout / "app/src/pipe.ts")
    engine = ModelLoopEngine(ScriptedClient([]), allowed_paths=("app/",), protected=(), tests_only=False)
    started = time.monotonic()
    assert "not readable" in engine._read(hostile_checkout, ["app/src/pipe.ts"])
    assert time.monotonic() - started < 5


def test_agy_settings_are_rewritten_before_every_call_including_the_retry(tmp_path: Path) -> None:
    fake = _fake_agy(tmp_path, "time.sleep(60)\n")
    rewrites: list[int] = []
    AgyEngine(fake, home=tmp_path, call_timeout_s=1, dirty=lambda: False,
              before_call=lambda: rewrites.append(1)).edit("p", workdir=str(tmp_path), timeout_s=120)
    assert len(rewrites) == 2


def test_every_agy_call_writes_its_own_debug_log(tmp_path: Path) -> None:
    fake = _fake_agy(tmp_path, "time.sleep(60)\n")
    logs = tmp_path / "reports"
    logs.mkdir()
    engine = AgyEngine(fake, home=tmp_path, call_timeout_s=1, dirty=lambda: False, log_dir=logs, round_no=lambda: 3)
    argv_file = tmp_path / "argv.json"
    fake.write_text(fake.read_text().replace("time.sleep(60)", f"import json; open({str(argv_file)!r}, 'a').write("
                                             "json.dumps(sys.argv[1:]) + chr(10)); time.sleep(60)"))
    engine.edit("p", workdir=str(tmp_path), timeout_s=120)
    calls = [json.loads(line) for line in argv_file.read_text().splitlines()]
    assert [c[c.index("--log-file") + 1] for c in calls] == [str(logs / "agy-iter3.log"), str(logs / "agy-iter3-2.log")]
    assert engine.last_logs == (logs / "agy-iter3.log", logs / "agy-iter3-2.log")


def test_unrestricted_agy_skips_permissions_but_only_as_the_engine_user(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(cmd: list[str], **kwargs: Any) -> CommandResult:
        calls.append(cmd)
        assert kwargs["user"] == 1001
        return CommandResult(0, "ok")

    user = RunAs("agyuser", 1001, 1001, Path("/home/agyuser"))
    engine = AgyEngine(Path("/opt/agy/bin/agy"), home=user.home, run_as=user, run=run, unrestricted=True,
                       reap=lambda u: 0)
    assert engine.name == "agy-unrestricted"
    engine.edit("p", workdir=str(tmp_path), timeout_s=5)
    assert calls[0][1:4] == ["-p", "p", "--dangerously-skip-permissions"]
    assert "--sandbox" not in calls[0]
    with pytest.raises(ValueError, match="root"):
        AgyEngine(Path("/opt/agy/bin/agy"), home=tmp_path, run_as=None, unrestricted=True)


def test_agy_rounds_are_capped_six_minutes_restricted_and_fifteen_unrestricted(tmp_path: Path) -> None:
    assert (AGY_RESTRICTED_CALL_TIMEOUT_S, AGY_UNRESTRICTED_CALL_TIMEOUT_S) == (360, 900)
    caps: list[float] = []

    def run(cmd: list[str], **kwargs: Any) -> CommandResult:
        caps.append(kwargs["timeout_s"])
        return CommandResult(0, "ok")

    user = RunAs("agyuser", 1001, 1001, Path("/home/agyuser"))
    for unrestricted in (False, True):
        AgyEngine(Path("/opt/agy/bin/agy"), home=user.home, run_as=user, run=run, unrestricted=unrestricted,
                  reap=lambda u: 0).edit("p", workdir=str(tmp_path), timeout_s=7200)
    AgyEngine(Path("/opt/agy/bin/agy"), home=user.home, run_as=user, run=run, unrestricted=True,
              reap=lambda u: 0).edit("p", workdir=str(tmp_path), timeout_s=100)   # the job deadline still wins
    assert caps == [360, 900, 100]


def test_a_timed_out_round_with_edits_keeps_them_and_says_it_timed_out(tmp_path: Path) -> None:
    user = RunAs("agyuser", 1001, 1001, Path("/home/agyuser"))
    engine = AgyEngine(Path("/opt/agy/bin/agy"), home=user.home, run_as=user, unrestricted=True, reap=lambda u: 0,
                       run=lambda cmd, **kw: CommandResult(shell.TIMEOUT_RC, "[timed out after 900s]"),
                       dirty=lambda: True)
    result = engine.edit("p", workdir=str(tmp_path), timeout_s=7200)
    assert result.returncode == 0
    assert "keeping them for the test run" in result.output
    assert engine.last_timed_out
    finished = AgyEngine(Path("/opt/agy/bin/agy"), home=user.home, run_as=user, reap=lambda u: 0,
                         run=lambda cmd, **kw: CommandResult(0, "done"))
    finished.edit("p", workdir=str(tmp_path), timeout_s=7200)
    assert not finished.last_timed_out


def test_root_never_inspects_the_tree_while_agy_still_runs(tmp_path: Path) -> None:
    pid_file = tmp_path / "agy.pid"
    fake = _fake_agy(tmp_path, f"import os; open({str(pid_file)!r}, 'w').write(str(os.getpid()))\n"
                               "print('error: Individual quota reached. Please upgrade your subscription to increase your limits. Resets in 19h13m22s.', flush=True)\ntime.sleep(60)\n")
    checks: list[bool] = []

    def dirty() -> bool:
        pid = int(pid_file.read_text())
        try:
            os.kill(pid, 0)
            checks.append(False)          # agy (the engine user) still alive: root's git would race it
        except ProcessLookupError:
            checks.append(True)
        return True

    result = AgyEngine(fake, home=tmp_path, dirty=dirty).edit("p", workdir=str(tmp_path), timeout_s=120)
    assert checks
    assert all(checks)
    assert result.returncode == 0                       # edits made before the quota stop are kept
    assert "quota" in result.output


@pytest.fixture
def web(tmp_path: Path) -> Path:
    """A slice of the real app: two workspaces, a stale test, a passing template test and a helper."""
    files = {
        "app/web/src/pages/HomePage.tsx": "export function HomePage() { return null; }\nexport const TITLE = 'x';\n",
        "app/web/src/api.ts": "export async function fetchParcel(id: string) { return id; }\n"
                              "export interface Parcel { id: string }\nexport type Status = 'a';\n",
        "app/core/src/index.ts": "export class TrackingNumber {}\n",
        "app/web/tests/helpers/render.tsx": "export function renderPage() { return 1; }\n",
        "app/web/tests/home-page.test.tsx": "import { describe, expect, it } from 'vitest';\n// STALE HEADING\n",
        "app/web/tests/about.test.tsx": "import { describe, expect, it } from 'vitest';\n// TEMPLATE STYLE\n",
    }
    for rel, content in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(content)
    return tmp_path


def _maintenance_loop(client: ScriptedClient) -> ModelLoopEngine:
    return ModelLoopEngine(client, allowed_paths=("app/web/tests/home-page.test.tsx",), protected=(),
                           tests_only=True, failing=lambda: ("app/web/tests/home-page.test.tsx",))


def test_the_loop_never_edits_blind(web: Path) -> None:
    client = ScriptedClient([{"edits": [], "read": [], "note": "nothing"}])
    _maintenance_loop(client).edit("repair the stale tests", workdir=str(web), timeout_s=60)
    prompt = client.calls[0][0]["content"]
    assert "// STALE HEADING" in prompt                                     # current content of the allowed file
    assert "app/web/src/pages/HomePage.tsx: HomePage, TITLE" in prompt       # real paths and exported names
    assert "app/web/src/api.ts: fetchParcel, Parcel, Status" in prompt
    assert "app/core/src/index.ts: TrackingNumber" in prompt
    assert "app/web/tests/helpers/render.tsx: renderPage" in prompt
    assert "// TEMPLATE STYLE" in prompt                                     # a passing test as the style template
    assert 'import { describe, expect, it } from "vitest"' in prompt         # the hard rules
    assert "never invent" in prompt.lower()


def test_the_loop_rejects_invented_imports_and_vitest_globals_and_asks_again(web: Path) -> None:
    invented = "import { describe, expect, it } from 'vitest';\nimport Home from '../src/pages/Home';\n"
    globals_only = "import { HomePage } from '../src/pages/HomePage';\ndescribe('h', () => { it('x', () => {}) });\n"
    good = ("import { describe, expect, it } from 'vitest';\nimport { HomePage } from '../src/pages/HomePage';\n"
            "import { tidy } from './helpers/tidy';\ndescribe('home', () => { it('renders', () => "
            "{ expect(HomePage).toBeTruthy(); }); });\n")
    client = ScriptedClient([
        {"edits": [{"path": "app/web/tests/home-page.test.tsx", "content": invented}], "read": [], "note": ""},
        {"edits": [{"path": "app/web/tests/home-page.test.tsx", "content": globals_only}], "read": [], "note": ""},
        {"edits": [{"path": "app/web/tests/home-page.test.tsx", "content": good},
                   {"path": "app/web/tests/helpers/tidy.ts", "content": "export const tidy = 1;\n"}],
         "read": [], "note": ""},
    ])
    engine = ModelLoopEngine(client, allowed_paths=("app/web/tests/",), protected=(), tests_only=True,
                             failing=lambda: ("app/web/tests/home-page.test.tsx",))
    result = engine.edit("repair", workdir=str(web), timeout_s=60)
    assert result.returncode == 0
    assert (web / "app/web/tests/home-page.test.tsx").read_text() == good   # imports a file from the same proposal
    second, third = client.calls[1][-1]["content"], client.calls[2][-1]["content"]
    assert "'../src/pages/Home'" in second and "does not exist" in second
    assert "describe, it" in third and "vitest" in third


def test_the_loop_writes_nothing_when_every_proposal_is_invalid(web: Path) -> None:
    bad = {"edits": [{"path": "app/web/tests/home-page.test.tsx", "content": "describe('x', () => {});\n"}],
           "read": [], "note": ""}
    engine = _maintenance_loop(ScriptedClient([bad, bad, bad]))
    result = engine.edit("repair", workdir=str(web), timeout_s=60)
    assert result.returncode == 0
    assert "rejected" in result.output
    assert "// STALE HEADING" in (web / "app/web/tests/home-page.test.tsx").read_text()


REAL_LINE = "error: Individual quota reached. Please upgrade your subscription to increase your limits."
REAL_JSON = ('AGY_ERROR: {"short_error":"RESOURCE_EXHAUSTED (code 429): Individual quota reached.",'
             '"status":"RESOURCE_EXHAUSTED","error_code":429,"retryable":true}')
NARRATION = "I will add a per-user quota check and return HTTP 429 when the limit is exceeded."
ABORT = "[aborted: agy reported a quota or rate limit]"


@pytest.mark.parametrize(("code", "output", "quota"), [
    (125, f"{REAL_LINE}\n{ABORT}", True),
    (125, f"{REAL_JSON}\n{ABORT}", True),
    (3, f"{REAL_LINE} Resets in 19h13m22s.\n{REAL_JSON}", True),
    (3, f"working on it\n{REAL_JSON}", True),
    (125, f"{NARRATION}\n{ABORT}", False),            # the abort marker alone is no evidence
    (3, f"{NARRATION}\nerror: something else broke", False),
    (3, "RESOURCE_EXHAUSTED mentioned by the model, not an agy error line", False),
    (125, "  the quota is spent says the model  \n" + ABORT, False),
    (125, "[aborted: agy needs authentication (token missing or expired)]", False),
    (3, "error: something else broke", False),
    (0, REAL_LINE, False),                              # exit 0: agy finished
    (1, f"{NARRATION}\n429 Too Many Requests in a test fixture", False),
])
def test_quota_failures_are_told_apart_from_auth_narration_and_other_failures(
        code: int, output: str, quota: bool) -> None:
    from sdlc_agents.coder.engines import is_quota_failure
    from sdlc_agents.ports import CommandResult
    assert is_quota_failure(CommandResult(code, output)) is quota


def test_model_narration_about_quotas_and_429_does_not_abort_a_healthy_agy(tmp_path: Path) -> None:
    fake = _fake_agy(tmp_path, f"print({NARRATION!r}, flush=True)\nprint('echoed: if (n > limit) return 429', "
                               "flush=True)\ntime.sleep(2)\nprint('done')\n")
    result = AgyEngine(fake, home=tmp_path, dirty=lambda: False).edit("p", workdir=str(tmp_path), timeout_s=120)
    assert result.returncode == 0 and "done" in result.output
    assert (tmp_path / "calls").read_text() == "x"


def test_agys_real_quota_error_line_is_aborted_and_classified_as_quota(tmp_path: Path) -> None:
    from sdlc_agents.coder.engines import is_quota_failure
    fake = _fake_agy(tmp_path, f"print({NARRATION!r}, flush=True)\nprint({REAL_LINE!r}, flush=True)\n"
                               "time.sleep(60)\n")
    result = AgyEngine(fake, home=tmp_path, dirty=lambda: False).edit("p", workdir=str(tmp_path), timeout_s=120)
    assert result.returncode == shell.ABORTED_RC and is_quota_failure(result)


def test_agys_own_quota_exit_code_is_classified_as_quota(tmp_path: Path) -> None:
    from sdlc_agents.coder.engines import is_quota_failure
    fake = _fake_agy(tmp_path, f"print({REAL_LINE!r}, flush=True)\nprint({REAL_JSON!r}, flush=True)\nsys.exit(3)\n")
    result = AgyEngine(fake, home=tmp_path, dirty=lambda: False).edit("p", workdir=str(tmp_path), timeout_s=120)
    assert result.returncode == 3 and is_quota_failure(result)
