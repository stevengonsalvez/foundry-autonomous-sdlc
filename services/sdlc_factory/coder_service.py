"""
sdlc-coder over plain HTTP: replaces the Foundry hosted-agent host (agents/hosted/coder/main.py).

    POST /invoke[?agent_session_id=<id>]   body {"op": "start"|"status"|"cancel", ...}  (Coder contract)
    GET  /healthz                          {"ok": true}, no token

The reply carries `x-agent-session-id`: a fresh uuid when the caller sent none, else the caller's id.
This process is one session; the id is bookkeeping for the orchestrator, which stores and echoes it.

Exposure: it binds 0.0.0.0 inside its container and must sit on an internal compose network only,
never a published port. v1 has no user auth; when CODER_SERVICE_TOKEN is set every /invoke must send
it in `x-factory-token` (constant-time compare). Bodies over 1 MiB are refused unread (413).

Environment: CODER_HOST (0.0.0.0), CODER_PORT (8088), CODER_SERVICE_TOKEN, FACTORY_MODE (`fake` or
unset), FAKE_STATUS_POLLS (3), REPO (default: first repository in FACTORY_CONFIG, default
factory/factory.yaml), plus everything sdlc_agents.coder.local_wiring reads. Run with
`PYTHONPATH=../agents python -m sdlc_factory.coder_service`.

FACTORY_MODE=fake answers the same protocol from memory, with no repo, git, agy or secrets: a started job
reports `running` until its Nth status poll, then `succeeded` with a fake PR (the job's own PR for revise
and maintenance, else 1000 + the issue number). For the compose smoke test only.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import sys
import threading
import uuid
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

from sdlc_agents.clock import SystemClock
from sdlc_agents.coder.job import JobSpec, JobSpecError, JobState, Phase, Redactor, Status
from sdlc_agents.foundry import SESSION_HEADER
from sdlc_agents.ports import REPO, ClockPort

from sdlc_factory.config import load_factory

TOKEN_HEADER = "x-factory-token"   # noqa: S105 (a header name, not a secret)
MAX_BODY_BYTES = 1024 * 1024
SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
DEFAULT_PORT = 8088
DEFAULT_FAKE_POLLS = 3
DEFAULT_FACTORY_CONFIG = "factory/factory.yaml"
__all__ = ["MAX_BODY_BYTES", "SESSION_HEADER", "TOKEN_HEADER", "FakeCoder", "build_service", "main", "serve"]


class Invocable(Protocol):
    @property
    def redact(self) -> Redactor: ...
    def handle_raw(self, raw: bytes, *, session_id: str = "") -> tuple[int, dict[str, Any]]: ...


# -- HTTP ---------------------------------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    server_version = "sdlc-coder"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    timeout = 60   # per socket read: a client that stops sending cannot hold a thread forever
    service: Invocable
    token: str | None

    def do_GET(self) -> None:
        if urlsplit(self.path).path == "/healthz":
            self._reply(200, {"ok": True})
        else:
            self._reply(404, {"error": "not_found"})

    def do_POST(self) -> None:
        url = urlsplit(self.path)
        if url.path != "/invoke":
            self._reply(404, {"error": "not_found"}, close=True)
            return
        raw = self._body()
        if raw is None:
            return
        if self.token is not None and not hmac.compare_digest(
                self.headers.get(TOKEN_HEADER, "").encode(), self.token.encode()):
            self._reply(401, {"error": "unauthorized"})
            return
        given = parse_qs(url.query).get("agent_session_id")
        session = given[-1] if given else str(uuid.uuid4())
        if not SESSION_ID.fullmatch(session):
            self._reply(400, {"error": "invalid_session_id"})
            return
        try:
            status, payload = self.service.handle_raw(raw, session_id=session)
        except Exception as exc:   # handle_raw should never raise; the server keeps serving if it does
            print(f"coder: request failed\n{self.service.redact.traceback(exc)}", file=sys.stderr, flush=True)
            status, payload = 500, {"error": "internal_error"}
        self._reply(status, payload, session=session)

    def _body(self) -> bytes | None:
        """The request body, or None after an error reply. Oversized bodies are never read."""
        length = self.headers.get("Content-Length")
        if length is None:
            self._reply(411, {"error": "length_required"}, close=True)
            return None
        try:
            size = int(length)
            if size < 0:
                raise ValueError(length)
        except ValueError:
            self._reply(400, {"error": "invalid_content_length"}, close=True)
            return None
        if size > MAX_BODY_BYTES:
            self._reply(413, {"error": "body_too_large", "max_bytes": MAX_BODY_BYTES}, close=True)
            return None
        return self.rfile.read(size)

    def _reply(self, status: int, payload: dict[str, Any], *, session: str | None = None,
               close: bool = False) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        if session is not None:
            self.send_header(SESSION_HEADER, session)
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        print(self.service.redact(f"{self.address_string()} {format % args}"), file=sys.stderr, flush=True)


def serve(service: Invocable, *, host: str = "0.0.0.0", port: int = DEFAULT_PORT,  # noqa: S104 (see module doc)
          token: str | None = None) -> ThreadingHTTPServer:
    """A bound server; the caller runs `serve_forever()`. `port=0` picks a free one."""
    handler = type("CoderHandler", (_Handler,), {"service": service, "token": token or None})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


# -- FACTORY_MODE=fake ---------------------------------------------------------------------------------------


class FakeCoder:
    """The Coder contract from memory. Requests are validated by the real JobSpec; replies use JobState.view."""

    def __init__(self, polls: int = DEFAULT_FAKE_POLLS, *, clock: ClockPort | None = None):
        if polls < 1:
            raise ValueError("FAKE_STATUS_POLLS must be at least 1")
        self._polls = polls
        self._clock = clock or SystemClock()
        self._jobs: dict[str, tuple[JobSpec, JobState]] = {}
        self._seen: dict[str, int] = {}
        self._lock = threading.Lock()
        self.redact = Redactor()

    def handle_raw(self, raw: bytes, *, session_id: str = "") -> tuple[int, dict[str, Any]]:
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return 400, {"error": "invalid_json"}
        try:
            return self.handle(body, session_id=session_id)
        except Exception as exc:
            print(f"coder (fake): request failed\n{self.redact.traceback(exc)}", file=sys.stderr, flush=True)
            return 500, {"error": "internal_error"}

    def handle(self, body: Any, *, session_id: str = "") -> tuple[int, dict[str, Any]]:
        if not isinstance(body, dict):
            return 400, {"error": "invalid_request", "message": "body must be a JSON object"}
        op = body.get("op")
        with self._lock:
            if op == "start":
                return self._start(body.get("job"), session_id)
            if op == "status":
                return self._status(str(body.get("job_id", "")))
            if op == "cancel":
                return self._cancel(str(body.get("job_id", "")))
        return 400, {"error": "unknown_op", "message": "op must be start, status or cancel"}

    def _start(self, job: Any, session_id: str) -> tuple[int, dict[str, Any]]:
        try:
            spec = JobSpec.from_request(job)
        except JobSpecError as exc:
            return 400, {"error": "invalid_job", "message": str(exc)}
        known = self._jobs.get(spec.job_id)
        if known is not None:
            state = known[1]
            if state.terminal:
                return 200, self._view(state)
            return 200, {"job_id": state.job_id, "status": state.status.value, "session_id": state.session_id}
        state = JobState.new(spec, started_at=self._clock.now_iso())
        state.session_id, state.engine = session_id, "fake"
        self._jobs[spec.job_id] = (spec, state)
        self._seen[spec.job_id] = 0
        return 200, {"job_id": spec.job_id, "status": Status.RUNNING.value, "session_id": session_id}

    def _status(self, job_id: str) -> tuple[int, dict[str, Any]]:
        known = self._jobs.get(job_id)
        if known is None:
            return 404, {"error": "unknown_job", "job_id": job_id}
        spec, state = known
        if not state.terminal:
            self._seen[job_id] += 1
            if self._seen[job_id] >= self._polls:
                number = spec.pr_number or 1000 + spec.issue_number
                state.status, state.phase, state.iterations = Status.SUCCEEDED, Phase.PR, 1
                state.pr = {"number": number, "url": f"https://github.com/{spec.repo}/pull/{number}"}
                state.green_summary = "fake coder: all tests passed"
                state.updated_at = self._clock.now_iso()
        return 200, self._view(state)

    def _cancel(self, job_id: str) -> tuple[int, dict[str, Any]]:
        known = self._jobs.get(job_id)
        if known is None or known[1].terminal:
            return self._status(job_id)
        state = known[1]
        state.status, state.reason, state.updated_at = Status.CANCELLED, "cancelled", self._clock.now_iso()
        return 200, {"job_id": job_id, "status": "cancelling"}

    def _view(self, state: JobState) -> dict[str, Any]:
        return state.view(f"fake coder: job {state.job_id} {state.status.value}", now=self._clock.now_iso())


# -- composition -------------------------------------------------------------------------------------------


def resolve_repo(env: Mapping[str, str]) -> str:
    """REPO, else the first repository in the factory config, else the coder's own repo."""
    if env.get("REPO"):
        return env["REPO"]
    path = Path(env.get("FACTORY_CONFIG") or DEFAULT_FACTORY_CONFIG)
    if not path.is_file():
        return REPO
    first = load_factory(path).repositories[0]
    return f"{first.owner}/{first.name}"


def build_service(env: Mapping[str, str] = os.environ) -> Invocable:
    mode = env.get("FACTORY_MODE", "").strip().lower()
    if mode == "fake":
        return FakeCoder(int(env.get("FAKE_STATUS_POLLS") or DEFAULT_FAKE_POLLS))
    if mode not in ("", "live"):
        raise ValueError(f"FACTORY_MODE must be fake or live, got {mode!r}")
    from sdlc_agents.coder.local_wiring import build_local_service  # the real engines: only when used

    return build_local_service(env, repo=resolve_repo(env))


def main(env: Mapping[str, str] = os.environ) -> None:
    service = build_service(env)

    def report(where: str, exc: BaseException | None) -> None:
        text = service.redact.traceback(exc) if exc is not None else "(no exception)"
        print(f"unhandled exception in {where}\n{text}", file=sys.stderr, flush=True)

    threading.excepthook = lambda args: report(f"thread {args.thread.name if args.thread else '?'}", args.exc_value)
    host, port = env.get("CODER_HOST") or "0.0.0.0", int(env.get("CODER_PORT") or DEFAULT_PORT)  # noqa: S104
    token = env.get("CODER_SERVICE_TOKEN") or None
    server = serve(service, host=host, port=port, token=token)
    print(f"sdlc-coder listening on {host}:{server.server_address[1]} "
          f"mode={env.get('FACTORY_MODE') or 'live'} token={'required' if token else 'off'}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
