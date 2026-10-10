"""
sdlc-coder hosted agent: Invocations protocol entry point.

Request bodies follow docs/architecture.md (Coder contract): {"op": "start"|"status"|"cancel", ...}.
All logic lives in sdlc_agents.coder; this file only adapts HTTP to CoderService.
"""

from __future__ import annotations

import sys
import threading

from azure.ai.agentserver.invocations import InvocationAgentServerHost
from starlette.requests import Request
from starlette.responses import JSONResponse

from sdlc_agents.coder.job import Redactor
from sdlc_agents.coder.wiring import build_service

_fallback = Redactor()   # until the service (and its redactor, which knows the fetched secrets) exists


def _report(where: str, exc: BaseException | None) -> None:
    """Anything that escapes goes to stdout (the platform logstream), redacted and without local variables."""
    redact = service.redact if "service" in globals() else _fallback
    text = redact.traceback(exc) if exc is not None else "(no exception)"
    print(f"unhandled exception in {where}\n{text}", flush=True)


threading.excepthook = lambda args: _report(f"thread {args.thread.name if args.thread else '?'}", args.exc_value)
sys.excepthook = lambda kind, value, tb: _report("main", value)

app = InvocationAgentServerHost()
service = build_service()


@app.invoke_handler
async def handle(request: Request) -> JSONResponse:
    session_id = str(getattr(request.state, "session_id", "") or "")
    status, payload = service.handle_raw(await request.body(), session_id=session_id)
    return JSONResponse(payload, status_code=status)


if __name__ == "__main__":
    app.run()
