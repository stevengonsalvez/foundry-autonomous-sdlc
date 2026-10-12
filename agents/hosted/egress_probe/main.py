"""
egress-probe hosted agent (Invocations protocol): a throwaway diagnostic, deployed only by
scripts/verify_egress.py and deleted by it afterwards. It reads nothing secret and holds no role.

    {"op": "probe"}   one GET to each fixed URL below; status code or error class only
    {"op": "caps"}    euid, CAP_NET_ADMIN, and the names (never values) of proxy variables

The URLs are fixed here, not taken from the request, so the agent cannot be pointed at internal
endpoints (managed identity, IMDS, the platform proxy). Response bodies, headers and exception
messages are never returned: the status code or the exception class is the evidence.

Used to prove the hosted-agent egress policy: an allowed host answers, an unlisted host is refused.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

from azure.ai.agentserver.invocations import InvocationAgentServerHost
from starlette.requests import Request
from starlette.responses import JSONResponse

app = InvocationAgentServerHost()
# Allowed: on every coder allow-list. Blocked: on none of them.
ALLOWED_URL = "https://registry.npmjs.org/"
BLOCKED_URL = "https://example.com/"


def fetch(url: str, timeout_s: float = 10.0) -> dict[str, object]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=timeout_s) as resp:
            return {"url": url, "status": resp.status}
    except urllib.error.HTTPError as exc:
        return {"url": url, "status": exc.code}
    except Exception as exc:  # DNS, refused, reset, TLS, timeout: the class is the evidence
        return {"url": url, "error": type(exc).__name__}


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
