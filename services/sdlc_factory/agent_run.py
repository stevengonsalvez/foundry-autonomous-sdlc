"""
POST /agent-run: the one place prompt-agent agy calls run (served by coder_service).

    request   {"prompt": str (1..100000 chars), "schema": object | null, "timeout_s": int 1..900}
    reply     {"returncode": int, "stdout": str, "stderr": str, "timed_out": bool, "duration_s": float}

The client sends data only. argv comes from AgyEngine in plan mode, the environment is built from
nothing (plus the proxy and CA settings), and any other request field is refused, so a caller cannot pick
flags, a binary, a mode or env. The reply is the raw process output; the caller classifies it.

Each call, as root:
- takes a slot (AGENT_RUN_CONCURRENCY, default 2); none free within `queue_wait_s` is 429 `busy`;
- makes `<root>/call-XXXX` (0711, root) holding `cwd/` (empty) and `home/` (0700, both owned by the
  engine user), writes the agy token and the schema into `home` 0600 without following links;
- runs agy as the agent user (supplementary groups cleared, own process group killed after);
- when it was the last run in flight, SIGKILLs whatever the agent user left behind (a helper that
  escaped the process group), then deletes the whole call directory, whatever happened.

The agent user is `agyagent` (uid 61001, made by Dockerfile.coder), NOT the coder jobs' `agyuser`:
coder jobs run unrestricted agy and npm on untrusted repositories, and with the same uid they could
read /proc/<pid>/cwd of an agent run and rewrite its schema or HOME (forging a reviewer verdict), and
their reap would kill agent runs. Agent runs still share `agyagent` with each other.

No agent user (not root, or missing) or no readable token: 500 with `sandbox_unavailable` or
`token_unavailable`, and nothing runs. FACTORY_MODE=fake answers from FakeAgentRunner instead.
"""

from __future__ import annotations

import functools
import json
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from sdlc_agents.coder import sandbox
from sdlc_agents.coder.job import Redactor
from sdlc_agents.coder.sandbox import RunAs
from sdlc_agents.coder.toolchain import AGY_AUTH_FILE

from sdlc_factory.engines import (
    HARD_KILL_AFTER_S,
    MAX_PROMPT_CHARS,
    TIMEOUT_RC,
    AgyEngine,
    ProcessOutput,
    subprocess_runner,
)

AGENT_RUN_PATH = "/agent-run"
AGENT_MODE = "plan"                         # fixed: prompt agents never edit
MAX_AGENT_TIMEOUT_S = 900
AGENT_OUTPUT_BYTES = 2 * 1024 * 1024        # per stream in the reply, cut at a line boundary
DEFAULT_AGENT_CONCURRENCY = 2
DEFAULT_QUEUE_WAIT_S = 60.0
BUSY_RETRY_AFTER_S = 30
DEFAULT_AGY_BINARY = "/opt/agy/bin/agy"
DEFAULT_AGY_TOKEN_FILE = "/run/secrets/agy_cli_token"  # noqa: S105 (a path, not a secret)
SCHEMA_FILE = "schema.json"
AGENT_USER = "agyagent"
MAX_PROMPT_BYTES = 128 * 1024 - 1           # Linux MAX_ARG_STRLEN, terminator included: one argv string
_FIELDS = frozenset({"prompt", "schema", "timeout_s"})


class RequestError(ValueError):
    pass


@dataclass(frozen=True)
class AgentRunRequest:
    prompt: str
    schema: dict[str, Any] | None
    timeout_s: int

    @classmethod
    def parse(cls, raw: bytes) -> AgentRunRequest:
        try:
            body = json.loads(raw)
        except ValueError:
            raise RequestError("body is not JSON") from None
        if not isinstance(body, dict):
            raise RequestError("body must be a JSON object")
        extra = set(body) - _FIELDS
        if extra:
            raise RequestError(f"unknown fields {sorted(extra)}: only prompt, schema and timeout_s are accepted")
        prompt, schema, timeout = body.get("prompt"), body.get("schema"), body.get("timeout_s")
        if not isinstance(prompt, str) or not 1 <= len(prompt) <= MAX_PROMPT_CHARS:
            raise RequestError(f"prompt must be a string of 1..{MAX_PROMPT_CHARS} characters")
        if len(prompt.encode("utf-8", errors="surrogatepass")) > MAX_PROMPT_BYTES:
            raise RequestError(f"prompt is over {MAX_PROMPT_BYTES} bytes, the argv limit")
        if schema is not None and not isinstance(schema, dict):
            raise RequestError("schema must be an object or null")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= MAX_AGENT_TIMEOUT_S:
            raise RequestError(f"timeout_s must be an integer of 1..{MAX_AGENT_TIMEOUT_S}")
        return cls(prompt, schema, timeout)


class AgentRunService(Protocol):
    redact: Redactor

    def handle_raw(self, raw: bytes) -> tuple[int, dict[str, Any]]: ...


class ProcessRunner(Protocol):
    def __call__(self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout_s: float,
                 abort_on: Callable[[str], str | None], user: RunAs) -> ProcessOutput: ...


def ensure_agent_user(*, euid: Callable[[], int] = os.geteuid,
                      getpwnam: Callable[[str], Any] = pwd.getpwnam) -> RunAs | None:
    """The agent-run user, which the image creates. None when not root or it is missing (fail closed)."""
    if euid() != 0:
        return None
    try:
        entry = getpwnam(AGENT_USER)
    except KeyError:
        return None
    return RunAs(AGENT_USER, entry.pw_uid, entry.pw_gid, Path(entry.pw_dir))


def dropped_runner(argv: list[str], *, cwd: Path, env: dict[str, str], timeout_s: float,
                   abort_on: Callable[[str], str | None], user: RunAs) -> ProcessOutput:
    """engines.subprocess_runner with the child switched to `user` before exec (as shell.run does)."""
    drop: dict[str, Any] = {"user": user.uid, "group": user.gid}
    if os.geteuid() == 0:
        drop["extra_groups"] = []    # setgroups needs root; a non-root caller has none to drop
    popen = functools.partial(subprocess.Popen, **drop)
    return subprocess_runner(argv, cwd=cwd, env=env, timeout_s=timeout_s, abort_on=abort_on, popen=popen)


def tail_lines(text: str, limit: int = AGENT_OUTPUT_BYTES) -> str:
    """The last `limit` bytes of `text`, starting at a line boundary (the result event is the last line)."""
    data = text.encode("utf-8", errors="replace")
    if len(data) <= limit:
        return text
    cut = data.find(b"\n", len(data) - limit)
    kept = data[cut + 1:] if 0 <= cut < len(data) - 1 else data[-limit:]   # one huge line: keep its tail
    return kept.decode("utf-8", errors="replace")


def _invalid(exc: RequestError) -> tuple[int, dict[str, Any]]:
    return 400, {"error": "invalid_request", "message": str(exc)}


class SandboxAgentRunner:
    def __init__(self, *, binary: Path, read_token: Callable[[], str],
                 concurrency: int = DEFAULT_AGENT_CONCURRENCY, queue_wait_s: float = DEFAULT_QUEUE_WAIT_S,
                 engine_user: Callable[[], RunAs | None] = ensure_agent_user,
                 process: ProcessRunner = dropped_runner, root: Path | None = None,
                 reap: Callable[[RunAs], int] = sandbox.reap_user, clock: Callable[[], float] = time.monotonic):
        if concurrency < 1:
            raise ValueError(f"AGENT_RUN_CONCURRENCY must be at least 1, got {concurrency}")
        self.concurrency = concurrency
        self.redact = Redactor()
        self._engine = AgyEngine(binary=binary, pass_proxy=True)
        self._read_token = read_token
        self._slots = threading.BoundedSemaphore(concurrency)
        self._queue_wait_s = queue_wait_s
        self._engine_user = engine_user
        self._process = process
        self._root = root
        self._root_lock = threading.Lock()
        self._reap = reap
        self._active = 0
        self._active_lock = threading.Lock()   # held while reaping, so no run starts mid-reap
        self._clock = clock

    def handle_raw(self, raw: bytes) -> tuple[int, dict[str, Any]]:
        try:
            request = AgentRunRequest.parse(raw)
        except RequestError as exc:
            return _invalid(exc)
        if not self._slots.acquire(timeout=self._queue_wait_s):
            return 429, {"error": "busy", "retry_after_s": BUSY_RETRY_AFTER_S}
        try:
            return self._run(request)
        finally:
            self._slots.release()

    def _run(self, request: AgentRunRequest) -> tuple[int, dict[str, Any]]:
        user = self._engine_user()
        if user is None or user.uid == 0:
            return 500, {"error": "sandbox_unavailable", "message": "no unprivileged engine user"}
        try:
            token = self._read_token().strip()
        except Exception as exc:   # never the content: only the error type
            return 500, {"error": "token_unavailable", "message": f"agy token unreadable: {type(exc).__name__}"}
        if not token:
            return 500, {"error": "token_unavailable", "message": "agy token is empty"}
        call = Path(tempfile.mkdtemp(prefix="call-", dir=self._base()))
        try:
            os.chmod(call, 0o711)  # noqa: S103 (traverse only: the engine user cannot list or write it)
            cwd, home = call / "cwd", call / "home"
            tmp = home / "tmp"
            for path in (cwd, home, tmp):
                path.mkdir(mode=0o700)
                os.chown(path, user.uid, user.gid)
            owner = (user.uid, user.gid)
            sandbox.write_private_file(home, AGY_AUTH_FILE, token.encode(), owner=owner)
            schema_path = None
            if request.schema is not None:
                schema_path = sandbox.write_private_file(home, SCHEMA_FILE, json.dumps(request.schema).encode(),
                                                         owner=owner)
            argv = self._engine.argv(request.prompt, mode=AGENT_MODE, schema_path=schema_path,
                                     timeout_s=request.timeout_s, log_path=None)
            env = {**self._engine.env(home), "TMPDIR": str(tmp)}   # agy temp files go with the call dir
            with self._active_lock:
                self._active += 1
            try:
                started = self._clock()
                out = self._process(argv, cwd=cwd, env=env, timeout_s=request.timeout_s + HARD_KILL_AFTER_S,
                                    abort_on=self._engine.abort_on, user=user)
                elapsed = self._clock() - started
            finally:
                self._ended(user)
        finally:
            _remove(call)
        return 200, {"returncode": out.returncode, "stdout": tail_lines(out.stdout), "stderr": tail_lines(out.stderr),
                     "timed_out": out.returncode == TIMEOUT_RC, "duration_s": round(float(elapsed), 3)}

    def _ended(self, user: RunAs) -> None:
        with self._active_lock:
            self._active -= 1
            if self._active == 0 and user.uid not in (0, os.geteuid()):   # never this process's own uid
                left = self._reap(user)
                if left:
                    print(f"agent-run: {left} {user.name} processes survived the reap", file=sys.stderr, flush=True)

    def _base(self) -> Path:
        """Root's per-process directory for call dirs: a fresh unguessable name (mkdtemp), never pre-created."""
        with self._root_lock:
            if self._root is None:
                self._root = Path(tempfile.mkdtemp(prefix="agent-run-"))
            self._root.mkdir(mode=0o711, parents=True, exist_ok=True)
            os.chmod(self._root, 0o711)  # noqa: S103 (traverse only, as above)
            return self._root


def _remove(call: Path) -> None:
    """Delete a call directory. rmtree is fd-based on Linux, so links planted inside are not followed."""
    try:
        shutil.rmtree(call)
    except OSError as exc:   # left behind: say so, the token copy inside is still 0600 to the engine user
        print(f"agent-run: cannot remove {call}: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)


class FakeAgentRunner:
    """FACTORY_MODE=fake: a deterministic agy result event, no process, no token."""

    TEXT = "fake agent: no model was called"

    def __init__(self) -> None:
        self.redact = Redactor()

    def handle_raw(self, raw: bytes) -> tuple[int, dict[str, Any]]:
        try:
            request = AgentRunRequest.parse(raw)
        except RequestError as exc:
            return _invalid(exc)
        response = "{}" if _object_without_required(request.schema) else self.TEXT
        event = {"event": "result", "result": {"status": "SUCCESS", "response": response, "duration_seconds": 0.0,
                                               "usage": {"input_tokens": 1, "output_tokens": 1, "thinking_tokens": 0,
                                                         "total_tokens": 2},
                                               "denied_actions": []}}
        return 200, {"returncode": 0, "stdout": json.dumps(event) + "\n", "stderr": "", "timed_out": False,
                     "duration_s": 0.0}


def _object_without_required(schema: dict[str, Any] | None) -> bool:
    return schema is not None and schema.get("type") == "object" and not schema.get("required")


def _concurrency(env: Mapping[str, str]) -> int:
    raw = (env.get("AGENT_RUN_CONCURRENCY") or str(DEFAULT_AGENT_CONCURRENCY)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        raise ValueError(f"AGENT_RUN_CONCURRENCY must be a positive integer, got {raw!r}")
    return value


def build_agent_runner(env: Mapping[str, str] = os.environ) -> AgentRunService:
    if env.get("FACTORY_MODE", "").strip().lower() == "fake":
        return FakeAgentRunner()
    token_file = Path(env.get("AGY_TOKEN_FILE") or DEFAULT_AGY_TOKEN_FILE)
    concurrency = _concurrency(env)

    def read_token() -> str:   # every call: a rotated token file is picked up without a restart
        from sdlc_agents.coder.local_wiring import FileSecrets

        return FileSecrets({"agy-cli-token": token_file}).get_secret("agy-cli-token")

    return SandboxAgentRunner(binary=Path(env.get("AGY_BINARY") or DEFAULT_AGY_BINARY), read_token=read_token,
                              concurrency=concurrency)

