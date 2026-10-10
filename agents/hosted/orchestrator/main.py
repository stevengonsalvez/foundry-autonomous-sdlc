"""
sdlc-orchestrator hosted agent (Invocations protocol).

Each POST /invocations runs one orchestrator tick (sdlc_agents.tick.run_tick) and returns the tick
report as JSON. The routine fires it every five minutes; the request body is ignored, so a manual
dispatch with any payload behaves the same. Shape follows the official hello-world sample:
microsoft-foundry/foundry-samples, samples/python/hosted-agents/bring-your-own/invocations.
"""

from __future__ import annotations

import asyncio
import logging
import os

from azure.ai.agentserver.invocations import InvocationAgentServerHost
from starlette.requests import Request
from starlette.responses import JSONResponse

from sdlc_agents.runtime import ConfigError, run_once

logger = logging.getLogger("sdlc-orchestrator")

# Prompts carry issue text and model answers; keep them out of the exported traces.
os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "false")
app = InvocationAgentServerHost()


@app.invoke_handler
async def handle_invoke(request: Request) -> JSONResponse:
    logger.info("tick requested (session %s)", getattr(request.state, "session_id", ""))
    try:
        report = await asyncio.to_thread(run_once, dict(os.environ))
    except ConfigError as exc:
        return JSONResponse(status_code=500, content={"error": "config", "message": str(exc)})
    except Exception as exc:
        # The tick itself never raises; this covers adapter construction (identity, Key Vault).
        logger.exception("tick setup failed")
        return JSONResponse(status_code=502, content={"error": "setup", "message": type(exc).__name__})
    return JSONResponse(report)


if __name__ == "__main__":
    app.run()
