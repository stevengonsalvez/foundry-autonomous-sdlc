"""
egress-probe hosted agent (Invocations protocol): a throwaway diagnostic, deployed only by
scripts/verify_egress.py and deleted by it afterwards. It reads nothing secret and holds no role.

    {"op": "probe"}   one GET to each fixed URL below (no redirects followed): status code or error class,
                      the issuer common name of the TLS certificate the host presented, and the platform
                      proxy's x-deny-reason value when the response carries one
    {"op": "caps"}    euid, CAP_NET_ADMIN, and the names (never values) of proxy variables

The URLs are fixed here, not taken from the request, so the agent cannot be pointed at internal
endpoints (managed identity, IMDS, the platform proxy) and redirects are not followed, so an allowed host
cannot bounce it elsewhere. Response bodies, other headers and exception messages are never returned: the
status code or the exception class is the evidence. The certificate issuer (public data) shows whether the
platform proxy terminates TLS (measured 2026-10-12: with a policy attached it does, for every host). It does
not tell a proxy 403 from an origin's, so the x-deny-reason header the proxy adds to its own refusals does
(an origin's responses never carried it); its value is "<host>:<method>", at most 160 characters.

Used to prove the hosted-agent egress policy: an allowed host answers, an unlisted host is refused.
"""

from __future__ import annotations

import os
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

from azure.ai.agentserver.invocations import InvocationAgentServerHost
from starlette.requests import Request
from starlette.responses import JSONResponse

app = InvocationAgentServerHost()
# Allowed: on every coder allow-list. Blocked: on none of them.
ALLOWED_URL = "https://registry.npmjs.org/"
BLOCKED_URL = "https://example.com/"




class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None   # the 3xx surfaces as an HTTPError and is reported as its status


_OPENER = urllib.request.build_opener(_NoRedirect)


def issuer_cn(host: str, timeout_s: float = 10.0) -> str:
    """Common name of the issuer of the certificate presented for `host` (verified against the system
    store), or `error:<class>`. Only this one public field leaves the sandbox."""
    try:
        with socket.create_connection((host, 443), timeout=timeout_s) as sock, \
                ssl.create_default_context().wrap_socket(sock, server_hostname=host) as tls:
            issuer = tls.getpeercert().get("issuer", ())
    except Exception as exc:
        return f"error:{type(exc).__name__}"
    return next((value for rdn in issuer for key, value in rdn if key == "commonName"), "")


def fetch(url: str, timeout_s: float = 10.0) -> dict[str, object]:
    host = urllib.parse.urlsplit(url).hostname or ""
    try:
        with _OPENER.open(urllib.request.Request(url, method="GET"), timeout=timeout_s) as resp:
            result: dict[str, object] = {"url": url, "status": resp.status}
    except urllib.error.HTTPError as exc:
        result = {"url": url, "status": exc.code}
        reason = exc.headers.get("x-deny-reason")
        if reason:
            result["deny_reason"] = reason[:160]
    except Exception as exc:  # DNS, refused, reset, TLS, timeout: the class is the evidence
        result = {"url": url, "error": type(exc).__name__}
    return {**result, "issuer": issuer_cn(host)}


def caps() -> dict[str, object]:
    cap_eff = "0"
    with open("/proc/self/status") as fh:
        for line in fh:
            key, _, value = line.partition(":")
            if key == "CapEff":
                cap_eff = value.strip()
    return {"euid": os.geteuid(), "cap_net_admin": bool(int(cap_eff, 16) & (1 << 12)),
            "proxy_vars": sorted(k for k in os.environ if "proxy" in k.lower())}


@app.invoke_handler
async def handle_invoke(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "body is not JSON"})
    op = body.get("op") if isinstance(body, dict) else None
    if op == "caps":
        return JSONResponse(caps())
    if op == "probe":
        return JSONResponse({"allowed": fetch(ALLOWED_URL), "blocked": fetch(BLOCKED_URL)})
    return JSONResponse(status_code=400, content={"error": "op must be probe or caps"})


if __name__ == "__main__":
    app.run()
