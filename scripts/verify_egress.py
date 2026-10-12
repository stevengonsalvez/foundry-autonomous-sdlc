"""
Prove the hosted-agent egress guardrail with a throwaway probe agent.

Deploys `egress-probe` (agents/hosted/egress_probe: 0.25 vCPU, 0.5 GiB, 2 minute idle, no role,
reads nothing secret) with the policy attached, checks the version really carries it, asks the probe
to GET its two fixed URLs (allowed: registry.npmjs.org, blocked: example.com; fixed in the probe so
it cannot be aimed elsewhere), checks the outcome against the policy's mode, then force-deletes the
probe. A few cents of hosted compute.

  Enforced: the allowed URL answers (any status but a proxy 403), the blocked URL gets 403.
  Audit:    both answer (the platform only logs the would-be denial; docs/runbook.md, section 9).

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
import deploy_agents as da

PROBE = "egress-probe"
PROBE_DIR = da.AGENTS_DIR / "hosted" / "egress_probe"


def probe_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in ("main.py", "requirements.txt"):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            # Regular file bit, or the service finds no manifest.
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, (PROBE_DIR / name).read_bytes())
    return buf.getvalue()


def judge(mode: str, allowed: dict[str, Any], blocked: dict[str, Any]) -> list[str]:
    """Return the broken expectations; empty means the policy behaved as its mode says."""
    if mode not in ("Audit", "Enforced"):
        return [f"unknown egress mode {mode!r}"]
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
    if not da._POLICY_ID.fullmatch(policy_id):
        print(f"error: not a raiPolicies resource id: {policy_id!r} (pass --policy-id, "
              "set EGRESS_POLICY_ID or apply terraform)", file=sys.stderr)
        return 1
    credential = AzureCliCredential()

    def call(method: str, url: str, scope: str,
             body: dict[str, Any] | None = None) -> da.HttpResponse:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Authorization": f"Bearer {credential.get_token(scope).token}",
                   "Content-Type": "application/json"}
        return da.urllib_transport(da.HttpRequest(method, url, headers, data, 300.0))

    policy = call("GET", f"{da.ARM}{policy_id}?api-version={da.EGRESS_API_VERSION}", da.ARM_SCOPE)
    if policy.status != 200:
        print(f"error: policy GET {policy.status}: {policy.text()[:300]}", file=sys.stderr)
        return 1
    egress = json.loads(policy.body)["properties"].get("egressPolicy")
    if not egress:
        print("error: the policy has no egressPolicy", file=sys.stderr)
        return 1
    mode = egress.get("mode")
    print(f"policy {policy_id.rsplit('/', 1)[-1]}: mode {mode}, "
          f"default {egress.get('defaultAction')}, {len(egress.get('rules', []))} rules")

    client = AIProjectClient(endpoint=config.project_endpoint, credential=credential)
    foundry = da.SdkFoundry(client)
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
        # An Audit pass looks exactly like no policy at all: prove the version carries it.
        if found["rai_policy"].lower() != policy_id.lower():
            print(f"FAIL probe version carries rai_policy {found['rai_policy']!r}, not the policy",
                  file=sys.stderr)
            return 1
        invoke = (f"{config.project_endpoint}/agents/{PROBE}/endpoint/protocols/invocations"
                  "?api-version=v1")
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
            verdict = "refused with 403" if mode == "Enforced" else "let through (audit only)"
            print(f"PASS {mode}: {allowed['url']} allowed, {blocked['url']} {verdict}")
        return 1 if problems else 0
    finally:
        if not args.keep:
            try:
                foundry.delete_agent(PROBE)
                print(f"{PROBE} deleted")
            except Exception as exc:  # never mask the verdict; the operator deletes by hand
                print(f"warning: {PROBE} not deleted ({type(exc).__name__}), delete it by hand",
                      file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
