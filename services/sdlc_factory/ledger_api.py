"""
ledger-api: the control center's data source and the ledger's write door, in front of one BranchStore.

    GET  /state.json   the folded v1 state document, exactly as stored (404 until the first ingest)
    GET  /issues.json  the pending-issues list the board shows, `[]` when none was ever stored
    GET  /healthz      liveness, never touches the store
    POST /ingest       {"events": [...], "reconcile": false}  ->  Ledger.handle, one commit per call

The control center is served from the same origin, so no CORS headers are sent. Ingest is serialised
behind a lock: this process is the only writer of the store, and a lost compare-and-swap would only cost
a retry. Stdlib http.server; run with `python -m sdlc_factory.ledger_api`.

Env: DOLT_HOST (127.0.0.1) DOLT_PORT (3306) DOLT_DB (ledger) DOLT_USER (root) DOLT_PASSWORD ()
     LEDGER_HOST (0.0.0.0) LEDGER_PORT (8080)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pymysql
from sdlc_agents.clock import SystemClock
from sdlc_agents.ledger.service import Ledger, LedgerError
from sdlc_agents.ledger.store import STATE_FILE, BranchStore, StoreConflict

from sdlc_factory.ledger_store import DoltBranchStore, pymysql_connector

ISSUES_FILE = "issues.json"
MAX_BODY_BYTES = 8 * 1024 * 1024
SCHEMA_WAIT_S = 60

log = logging.getLogger("ledger_api")


class LedgerApiServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], store: BranchStore, ledger: Ledger):
        super().__init__(address, _Handler)
        self.store = store
        self.ledger = ledger
        self.ingest_lock = threading.Lock()


def make_server(store: BranchStore, host: str, port: int, *, ledger: Ledger | None = None) -> LedgerApiServer:
    """Build (not start) the server. Port 0 picks a free port; read it from server.server_address."""
    ledger = ledger or Ledger(store, SystemClock(), mode="inline")  # no GitHub, billing or model: events only
    return LedgerApiServer((host, port), store, ledger)


def serve(store: BranchStore, host: str, port: int) -> None:
    server = make_server(store, host, port)
    log.info("ledger-api listening on %s:%s", *server.server_address[:2])
    try:
        server.serve_forever()
    finally:
        server.server_close()


class _Handler(BaseHTTPRequestHandler):
    server: LedgerApiServer
    protocol_version = "HTTP/1.1"

    GET_ROUTES = ("/state.json", "/issues.json", "/healthz")
    POST_ROUTES = ("/ingest",)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._json(HTTPStatus.OK, {"ok": True})
        elif path == "/state.json":
            self._serve_file(STATE_FILE, missing=None)
        elif path == "/issues.json":
            self._serve_file(ISSUES_FILE, missing="[]")
        else:
            self._refuse(path)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        if path != "/ingest":
            self._refuse(path)
            return
        body = self._read_json()
        if body is None:
            return
        try:
            with self.server.ingest_lock:
                reply = self.server.ledger.handle(
                    {"op": "ingest", "events": body.get("events", []), "reconcile": bool(body.get("reconcile"))}
                )
        except (LedgerError, ValueError) as exc:  # EventError is a ValueError: nothing was written
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except StoreConflict:
            self._error(HTTPStatus.CONFLICT, "ledger head kept moving; retry")
        except Exception:
            log.exception("ingest failed")
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "ingest failed")
        else:
            self._json(HTTPStatus.OK, reply)

    # -- helpers -----------------------------------------------------------------

    def _serve_file(self, name: str, *, missing: str | None) -> None:
        try:
            content = self.server.store.read().files.get(name, missing)
        except Exception:
            log.exception("store read failed")
            self._error(HTTPStatus.SERVICE_UNAVAILABLE, "store unavailable")
            return
        if content is None:
            self._error(HTTPStatus.NOT_FOUND, f"{name} has not been written yet")
            return
        self._send(HTTPStatus.OK, content.encode())

    def _read_json(self) -> dict[str, Any] | None:
        """The request body as a JSON object, or None after a 4xx reply was already sent."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0:
            self._error(HTTPStatus.BAD_REQUEST, "bad Content-Length")
            return None
        if length > MAX_BODY_BYTES:
            self.close_connection = True  # the unread body would corrupt the next request on this socket
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"body over {MAX_BODY_BYTES} bytes")
            return None
        try:
            doc = json.loads(self.rfile.read(length))
        except ValueError:
            self._error(HTTPStatus.BAD_REQUEST, "body is not JSON")
            return None
        if not isinstance(doc, dict):
            self._error(HTTPStatus.BAD_REQUEST, "body must be a JSON object")
            return None
        return doc

    def _refuse(self, path: str) -> None:
        known = path in self.GET_ROUTES or path in self.POST_ROUTES
        if known:
            allow = "GET" if path in self.GET_ROUTES else "POST"
            self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"ok": False, "error": "method not allowed"}, Allow=allow)
        else:
            self._error(HTTPStatus.NOT_FOUND, "not found")

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json(status, {"ok": False, "error": message})

    def _json(self, status: HTTPStatus, doc: Mapping[str, Any], **headers: str) -> None:
        self._send(status, json.dumps(doc).encode(), **headers)

    def _send(self, status: HTTPStatus, payload: bytes, **headers: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:
        log.info("%s %s", self.address_string(), format % args)


# -- entrypoint ----------------------------------------------------------------


def _ensure_schema_when_ready(store: DoltBranchStore, wait_s: float = SCHEMA_WAIT_S) -> None:
    """Dolt and this service start together under compose: wait for the database instead of crashing."""
    deadline = time.monotonic() + wait_s
    while True:
        try:
            store.ensure_schema()
            return
        except pymysql.err.OperationalError as exc:
            if time.monotonic() >= deadline:
                raise
            log.warning("dolt not ready (%s), retrying", exc)
            time.sleep(1)


def main(env: Mapping[str, str] | None = None) -> None:
    env = os.environ if env is None else env
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    store = DoltBranchStore(
        pymysql_connector(
            env.get("DOLT_HOST", "127.0.0.1"),
            int(env.get("DOLT_PORT", "3306")),
            env.get("DOLT_DB", "ledger"),
            user=env.get("DOLT_USER", "root"),
            password=env.get("DOLT_PASSWORD", ""),
        )
    )
    _ensure_schema_when_ready(store)
    serve(store, env.get("LEDGER_HOST", "0.0.0.0"), int(env.get("LEDGER_PORT", "8080")))  # noqa: S104


if __name__ == "__main__":
    main()
