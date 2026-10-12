"""
Prove the hosted-agent egress guardrail with a throwaway probe agent.

Deploys `egress-probe` (agents/hosted/egress_probe: 0.25 vCPU, 0.5 GiB, 2 minute idle, no role, reads
nothing secret) with the policy attached, asks it to GET its two fixed URLs (allowed: registry.npmjs.org,
blocked: example.com; fixed in the probe so it cannot be aimed elsewhere), checks the outcome against the
policy's mode, then force-deletes the probe. A few cents of hosted compute.

  Enforced: the allowed URL answers (any status but a proxy 403), the blocked URL gets 403.
  Audit:    both answer; the would-be denial is a "Network egress decision" trace in App Insights.

The policy is read from ARM, so the expectation follows whatever mode is deployed. Exit 0 when the
observed behaviour matches the mode, 1 when it does not (the report says which URL broke the rule).

Usage:
  uv run --project agents python scripts/verify_egress.py [--policy-id ID] [--keep]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deploy_agents as da  # noqa: E402

PROBE = "egress-probe"
PROBE_DIR = da.AGENTS_DIR / "hosted" / "egress_probe"
POLICY_API = "2026-05-15-preview"


def probe_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in ("main.py", "requirements.txt"):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16  # regular file bit, or the service finds no manifest
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, (PROBE_DIR / name).read_bytes())
    return buf.getvalue()


def judge(mode: str, allowed: dict[str, Any], blocked: dict[str, Any]) -> list[str]:
    """Return the broken expectations; empty means the policy behaved as its mode says."""
    problems = []
    if "error" in allowed or allowed.get("status") == 403:
        problems.append(f"allowed URL did not get through: {allowed}")
    if mode == "Enforced" and blocked.get("status") != 403:
        problems.append(f"Enforced: blocked URL was not refused with 403: {blocked}")
    if mode == "Audit" and ("error" in blocked or blocked.get("status") == 403):
        problems.append(f"Audit: blocked URL was refused, Audit must only log: {blocked}")
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--policy-id", default=os.environ.get("EGRESS_POLICY_ID", ""))
    parser.add_argument("--keep", action="store_true", help="leave the probe agent deployed")
    args = parser.parse_args(argv)

    from azure.ai.projects import AIProjectClient
    from azure.identity import AzureCliCredential

    config = da.Config.resolve(os.environ, terraform_outputs=da.terraform_outputs)
    policy_id = args.policy_id or config.egress_policy_id
    if not policy_id:
        print("error: no policy (pass --policy-id, set EGRESS_POLICY_ID or apply terraform)", file=sys.stderr)
        return 1
    credential = AzureCliCredential()

    def call(method: str, url: str, scope: str, body: dict[str, Any] | None = None) -> da.HttpResponse:
        data = json.dumps(body).encode() if body is not None else None
        return da.urllib_transport(da.HttpRequest(method, url, {
            "Authorization": f"Bearer {credential.get_token(scope).token}", "Content-Type": "application/json"},
            data, 300.0))

    policy = call("GET", f"{da.ARM}{policy_id}?api-version={POLICY_API}", da.ARM_SCOPE)
    if policy.status != 200:
        print(f"error: policy GET {policy.status}: {policy.text()[:300]}", file=sys.stderr)
        return 1
    egress = json.loads(policy.body)["properties"].get("egressPolicy") or {}
    mode = egress.get("mode", "Enforced")
    print(f"policy {policy_id.rsplit('/', 1)[-1]}: mode {mode}, default {egress.get('defaultAction', 'Deny')}, "
          f"{len(egress.get('rules', []))} rules")

    foundry = da.SdkFoundry(AIProjectClient(endpoint=config.project_endpoint, credential=credential))
    code = probe_zip()
    sha = hashlib.sha256(code).hexdigest()
    try:
        version = foundry.create_hosted_version(
            PROBE, cpu="0.25", memory="0.5Gi", idle_minutes=2, env={}, code=code, sha256=sha,
            description=f"throwaway egress probe {sha[:12]}", rai_policy=policy_id)
        for _ in range(180):
            found = foundry.get_version(PROBE, version)
            if found["status"] == "active":
                break
            if found["status"] == "failed":
                print(f"error: probe version failed: {found.get('error')}", file=sys.stderr)
                return 1
            time.sleep(da.POLL_S)
        else:
            print("error: probe not active after 900 s", file=sys.stderr)
            return 1
        invoke = f"{config.project_endpoint}/agents/{PROBE}/endpoint/protocols/invocations?api-version=v1"
        caps = call("POST", invoke, da.AI_SCOPE, {"op": "caps"})
        print(f"caps {caps.status}: {caps.text()[:1500]}")
        reply = call("POST", invoke, da.AI_SCOPE, {"op": "probe"})
        if reply.status != 200:
            print(f"error: probe call {reply.status}: {reply.text()[:500]}", file=sys.stderr)
            return 1
        result = json.loads(reply.body)
        allowed, blocked = result["allowed"], result["blocked"]
        print(json.dumps({"allowed": allowed, "blocked": blocked}, indent=2))
        problems = judge(mode, allowed, blocked)
        for problem in problems:
            print(f"FAIL {problem}")
        if not problems:
            print(f"PASS {mode}: {allowed['url']} allowed, {blocked['url']} "
                  f"{'refused with 403' if mode == 'Enforced' else 'let through (audit only)'}")
        return 1 if problems else 0
    finally:
        if not args.keep:
            try:
                foundry._client.agents.delete(PROBE, force=True)
                print(f"{PROBE} deleted")
            except Exception as exc:  # never mask the verdict; the operator deletes by hand
                print(f"warning: {PROBE} not deleted ({type(exc).__name__}), delete it by hand", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
