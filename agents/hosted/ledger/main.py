"""
sdlc-ledger hosted agent (Invocations protocol): the state-keeper.

Event driven: it does nothing until a request arrives, then the platform scales its compute back to
zero after the idle timeout (2 minutes, the minimum). Each POST /invocations is one operation:

    {"op": "ingest", "events": [...], "reconcile": false}   append events, fold, commit to branch `state`
    {"op": "reconcile", "issue": 12}                          rebuild from GitHub (issue optional)
    {"op": "rebuild"}                                         rebuild state.json from events.jsonl
    {"op": "status"}                                          read only

It writes only to branch `state` of the demo repository (the GitHub client refuses any other repo).
The orchestrator authenticates with Entra; the body is validated and cleaned before anything is stored.
"""

from __future__ import annotations

import asyncio
import logging
import os

from azure.ai.agentserver.invocations import InvocationAgentServerHost
from starlette.requests import Request
from starlette.responses import JSONResponse

from sdlc_agents.ledger.events import EventError
from sdlc_agents.ledger.runtime import build_ledger
from sdlc_agents.ledger.service import LedgerError
from sdlc_agents.runtime import ConfigError

logger = logging.getLogger("sdlc-ledger")

os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "false")
app = InvocationAgentServerHost()


@app.invoke_handler
async def handle_invoke(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "bad_request", "message": "body is not JSON"})
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"error": "bad_request", "message": "body must be an object"})
    try:
        ledger = await asyncio.to_thread(build_ledger, dict(os.environ))
        reply = await asyncio.to_thread(ledger.handle, body)
    except (LedgerError, EventError) as exc:
        return JSONResponse(status_code=400, content={"error": "bad_request", "message": str(exc)[:300]})
    except ConfigError as exc:
        return JSONResponse(status_code=500, content={"error": "config", "message": str(exc)})
    except Exception as exc:
        logger.exception("ledger call failed")
        return JSONResponse(status_code=502, content={"error": "ledger", "message": type(exc).__name__})
    return JSONResponse(reply)


if __name__ == "__main__":
    app.run()
