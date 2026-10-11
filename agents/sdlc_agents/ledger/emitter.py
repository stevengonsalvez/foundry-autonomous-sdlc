"""
How the orchestrator hands events to the ledger.

    HostedEmitter  one Invocations call to the `sdlc-ledger` hosted agent (the normal mode)
    InlineEmitter  runs the same Ledger in the orchestrator's own process (the documented fallback when the
                   hosted ledger cannot scale to zero or would break the spend cap); same events, same state
    NullEmitter    off

Emitting is best effort: a failure is returned as a note for the tick report and never fails or delays
the tick for long, because the ledger reconciles from GitHub (the source of truth) on its next call.
Stdlib only.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from sdlc_agents import cost
from sdlc_agents.ledger.service import Ledger
from sdlc_agents.ports import FoundryPort

LEDGER_AGENT = "sdlc-ledger"
CALL_TIMEOUT_S = 60


class EmitResult:
    def __init__(self, usd: float = 0.0, error: str | None = None, reply: dict[str, Any] | None = None):
        self.usd = usd
        self.error = error
        self.reply = reply or {}


class Emitter(Protocol):
    def emit(self, events: list[dict[str, Any]], *, reconcile: bool = False) -> EmitResult: ...


class NullEmitter:
    def emit(self, events: list[dict[str, Any]], *, reconcile: bool = False) -> EmitResult:
        return EmitResult()


class HostedEmitter:
    def __init__(self, foundry: FoundryPort, *, sleep: Any = time.sleep):
        self._foundry = foundry
        self._session: str | None = None

    def emit(self, events: list[dict[str, Any]], *, reconcile: bool = False) -> EmitResult:
        body = {"op": "ingest", "events": events, "reconcile": reconcile}
        started = time.monotonic()
        try:
            reply, self._session = self._foundry.invoke_hosted(
                LEDGER_AGENT, body, session_id=self._session, timeout_s=CALL_TIMEOUT_S
            )
        except Exception as exc:
            waited = time.monotonic() - started
            # A request that waited has woken the agent, which bills its idle tail whatever the answer was;
            # one that failed at once (no route, refused) never reached it.
            usd = cost.ledger_call_usd(waited) if waited >= 1.0 else 0.0
            return EmitResult(usd=usd, error=f"ledger: {type(exc).__name__}: {str(exc)[:160]}")
        if not reply.get("ok"):
            return EmitResult(error=f"ledger: {str(reply)[:160]}")
        return EmitResult(usd=float(reply.get("usd", 0.0)), reply=reply)


class InlineEmitter:
    def __init__(self, ledger: Ledger):
        self._ledger = ledger

    def emit(self, events: list[dict[str, Any]], *, reconcile: bool = False) -> EmitResult:
        try:
            reply = self._ledger.handle({"op": "ingest", "events": events, "reconcile": reconcile})
        except Exception as exc:
            return EmitResult(error=f"ledger: {type(exc).__name__}: {str(exc)[:160]}")
        return EmitResult(usd=float(reply.get("usd", 0.0)), reply=reply)
