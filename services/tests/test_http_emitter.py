"""HttpEmitter's auth header and redirect refusal against a real local HTTP server."""

from __future__ import annotations

import http.server
import json
import threading
from collections.abc import Iterator
from typing import Any

import pytest

from sdlc_factory.http_emitter import HttpEmitter


@pytest.fixture
def server() -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """POST /ingest answers ok; POST /moved redirects to /ingest. Every request is recorded."""
    seen: list[dict[str, Any]] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            size = int(self.headers.get("Content-Length") or 0)
            seen.append({"path": self.path, "token": self.headers.get("x-factory-token"),
                         "body": self.rfile.read(size)})
            if self.path.startswith("/moved"):
                self.send_response(307)
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_address[1]}/ingest")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", seen
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_the_ledger_token_is_sent_when_configured(server) -> None:
    url, seen = server
    assert HttpEmitter(url, token="ledger-tok").emit([]).error is None
    assert seen[0]["token"] == "ledger-tok"
    assert json.loads(seen[0]["body"]) == {"events": [], "reconcile": False}


def test_no_token_header_without_a_token(server) -> None:
    url, seen = server
    assert HttpEmitter(url).emit([]).error is None
    assert seen[0]["token"] is None


def test_the_token_defaults_from_the_environment(server, monkeypatch: pytest.MonkeyPatch) -> None:
    url, seen = server
    monkeypatch.setenv("LEDGER_TOKEN", "from-env")
    HttpEmitter(url).emit([])
    assert seen[0]["token"] == "from-env"


def test_a_redirect_is_not_followed_and_is_reported(server) -> None:
    url, seen = server
    result = HttpEmitter(f"{url}/moved", token="ledger-tok").emit([{"type": "x"}])
    assert result.error is not None and "307" in result.error
    assert [r["path"] for r in seen] == ["/moved/ingest"]     # the token never went to the redirect target
