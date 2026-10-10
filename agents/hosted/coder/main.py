"""
sdlc-coder hosted agent: Invocations protocol entry point.

Request bodies follow docs/architecture.md (Coder contract): {"op": "start"|"status"|"cancel", ...}.
All logic lives in sdlc_agents.coder; this file only adapts HTTP to CoderService.
"""

from __future__ import annotations

import sys
import threading
import traceback

from azure.ai.agentserver.invocations import InvocationAgentServerHost
from starlette.requests import Request
from starlette.responses import JSONResponse

from sdlc_agents.coder.wiring import build_service


def _print_thread_crash(args: threading.ExceptHookArgs) -> None:
    """Anything that escapes a thread goes to stdout, which the platform logstream shows."""
    name = args.thread.name if args.thread else "?"
    text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    print(f"unhandled exception in thread {name}\n{text}", flush=True)


threading.excepthook = _print_thread_crash
sys.excepthook = lambda kind, value, tb: print("".join(traceback.format_exception(kind, value, tb)), flush=True)

app = InvocationAgentServerHost()
service = build_service()


@app.invoke_handler
async def handle(request: Request) -> JSONResponse:
    session_id = str(getattr(request.state, "session_id", "") or "")
    status, payload = service.handle_raw(await request.body(), session_id=session_id)
    return JSONResponse(payload, status_code=status)


if __name__ == "__main__":
    app.run()
