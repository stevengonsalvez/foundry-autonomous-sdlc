"""
HttpEmitter: the tick's ledger hand-off (sdlc_agents.ledger.emitter.Emitter) over HTTP to ledger-api.

    POST {LEDGER_URL}/ingest   {"events": [...], "reconcile": bool}   ->  the Ledger.handle reply

Best effort, like HostedEmitter and InlineEmitter: any failure (refused, timeout, non-2xx, a reply that
is not JSON or says ok: false) comes back as EmitResult.error and never raises, because the ledger
reconciles from GitHub on a later call. ledger-api runs beside the worker, so a call costs nothing
(usd 0.0). Stdlib only.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from sdlc_agents.ledger.emitter import EmitResult

DEFAULT_TIMEOUT_S = 10.0
_DETAIL_CHARS = 160


class HttpEmitter:
    def __init__(self, base_url: str, *, timeout_s: float = DEFAULT_TIMEOUT_S):
        if urllib.parse.urlparse(base_url).scheme not in ("http", "https"):
            raise ValueError(f"LEDGER_URL must be an http(s) URL, got {base_url!r}")
        self._url = base_url.rstrip("/") + "/ingest"
        self._timeout_s = timeout_s

    def __repr__(self) -> str:
        return f"HttpEmitter({self._url})"

    def emit(self, events: list[dict[str, Any]], *, reconcile: bool = False) -> EmitResult:
        try:
            body = json.dumps({"events": events, "reconcile": reconcile}).encode()
            request = urllib.request.Request(self._url, data=body, method="POST",
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                reply = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return EmitResult(error=f"ledger: HTTP {exc.code}: {_read(exc)}")
        except Exception as exc:
            return EmitResult(error=f"ledger: {type(exc).__name__}: {str(exc)[:_DETAIL_CHARS]}")
        if not isinstance(reply, dict) or reply.get("ok") is False:
            return EmitResult(error=f"ledger: {str(reply)[:_DETAIL_CHARS]}")
        return EmitResult(usd=0.0, reply=reply)


def _read(exc: urllib.error.HTTPError) -> str:
    try:
        return exc.read().decode("utf-8", "replace")[:_DETAIL_CHARS]
    except Exception:
        return ""
