"""
Minimal HTTP transport shared by the REST adapters (GitHub, Key Vault, hosted agent invocations).

Adapters take a `Transport` so tests inject a recorded-style fake. The default uses urllib and
never follows redirects: the adapter decides whether to follow one and which headers to send, so a
bearer token can never leak to a redirect target. Stdlib only.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes | None = None
    timeout_s: float = 30.0

    def __repr__(self) -> str:  # headers carry tokens: never print them
        return f"HttpRequest({self.method} {self.url})"


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]        # lower-case names
    body: bytes

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")


Transport = Callable[[HttpRequest], HttpResponse]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def urllib_transport(request: HttpRequest) -> HttpResponse:
    if not request.url.startswith("https://"):
        raise ValueError(f"refusing non-https URL: {request.url}")
    req = urllib.request.Request(request.url, data=request.body, method=request.method, headers=request.headers)
    try:
        with _OPENER.open(req, timeout=request.timeout_s) as resp:
            return HttpResponse(resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp is not None else b""
        return HttpResponse(exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, body)
