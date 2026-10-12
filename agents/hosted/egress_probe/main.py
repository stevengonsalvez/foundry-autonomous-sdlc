"""
egress-probe hosted agent (Invocations protocol): a throwaway diagnostic, deployed only by
scripts/verify_egress.py and deleted by it afterwards. It reads nothing secret and holds no role.

    {"op": "probe", "urls": ["https://registry.npmjs.org/", ...]}   one GET per URL, status or error
    {"op": "caps"}                                                     capabilities, netfilter, proxy env

Used to prove the hosted-agent egress policy: an allowed host answers, an unlisted host is refused.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request

from azure.ai.agentserver.invocations import InvocationAgentServerHost
from starlette.requests import Request
from starlette.responses import JSONResponse

app = InvocationAgentServerHost()
MAX_URLS = 20


def fetch(url: str, timeout_s: float = 10.0) -> dict[str, object]:
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        return {"url": url, "error": "scheme"}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=timeout_s) as resp:
            return {"url": url, "status": resp.status}
    except urllib.error.HTTPError as exc:
        body = exc.read(300).decode("utf-8", "replace")
        return {"url": url, "status": exc.code, "server": exc.headers.get("server", ""), "body": body}
    except Exception as exc:  # DNS, refused, reset, TLS, timeout: the class is the evidence
        return {"url": url, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


def caps() -> dict[str, object]:
    status = {}
    with open("/proc/self/status") as fh:
        for line in fh:
            key, _, value = line.partition(":")
            if key in ("CapEff", "CapBnd", "CapPrm", "NoNewPrivs", "Seccomp"):
                status[key] = value.strip()
    netfilter = {}
    for tool in ("iptables", "ip6tables", "nft"):
        path = shutil.which(tool)
        if path is None:
            netfilter[tool] = "absent"
            continue
        args = [path, "list", "ruleset"] if tool == "nft" else [path, "-S"]
        done = subprocess.run(args, capture_output=True, text=True, timeout=10)
        netfilter[tool] = {"rc": done.returncode, "out": (done.stdout + done.stderr)[:300]}
    # Proxy settings are reported as host:port only, never with credentials.
    proxy = {k: urllib.parse.urlsplit(v).netloc.rpartition("@")[2] if "://" in v else v[:200]
             for k, v in os.environ.items() if "proxy" in k.lower()}
    cap_net_admin = bool(int(status.get("CapEff", "0"), 16) & (1 << 12))
    return {"euid": os.geteuid(), "status": status, "cap_net_admin": cap_net_admin,
            "netfilter": netfilter, "proxy_env": proxy}


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
        urls = body.get("urls")
        if not isinstance(urls, list) or not urls or len(urls) > MAX_URLS or not all(isinstance(u, str) for u in urls):
            return JSONResponse(status_code=400, content={"error": f"urls must be 1 to {MAX_URLS} strings"})
        return JSONResponse({"results": [fetch(u) for u in urls]})
    return JSONResponse(status_code=400, content={"error": "op must be probe or caps"})


if __name__ == "__main__":
    app.run()
