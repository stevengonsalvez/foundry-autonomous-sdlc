"""
Prove the hosted-agent egress guardrail with a throwaway probe agent.

Checks, in order, and exits 1 on any broken expectation (every one it can name is reported):
  1. The live sdlc-coder's latest version carries the policy (rai_policy) and the same
     EGRESS_FINGERPRINT (mode and rule hash) as the policy in ARM now: a policy that exists but is
     not attached proves nothing.
  2. Deploys `egress-probe` (agents/hosted/egress_probe: 0.25 vCPU, 0.5 GiB, 2 minute idle, no
     role, reads nothing secret) with the policy attached, checks that version reports the policy,
     asks the probe to GET its two fixed URLs (allowed: registry.npmjs.org, blocked: example.com;
     fixed in the probe so it cannot be aimed elsewhere, redirects are not followed) and checks
     the outcome against the policy's mode. Any stale egress-probe is deleted first and the probe
     is force-deleted at the end, always.

  Enforced: the allowed URL answers 200-399, the blocked URL gets 403 carrying the proxy's
            x-deny-reason header (an origin's own 403 does not).
  Audit:    both answer 200-399 (the platform only logs the would-be denial; docs/runbook.md,
            section 9).

The policy is read from ARM (the reader the deploy script uses), so the expectation follows
whatever mode is deployed. Exit 0 when the observed behaviour matches the mode, 1 when it does not.

Usage:
  uv run --project agents python scripts/verify_egress.py \
      [--policy-id ID] [--no-coder-check] [--keep]
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
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deploy_agents as da
from sdlc_agents.transport import HttpResponse

PROBE = "egress-probe"
CONFLICT_TRIES = 4
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


def _answered(result: Any) -> bool:
    """A real HTTP answer in 200-399 (an integer, not a missing field, an error or a bool)."""
    status = result.get("status") if isinstance(result, dict) else None
    return isinstance(status, int) and not isinstance(status, bool) and 200 <= status < 400


def judge(mode: str | None, allowed: Any, blocked: Any) -> list[str]:
    """Return the broken expectations; empty means the policy behaved as its mode says."""
    if mode not in da.EGRESS_MODES:
        return [f"unknown egress mode {mode!r}"]
    problems = []
    if not _answered(allowed):
        problems.append(f"allowed URL did not answer 200-399: {allowed}")
    blocked_status = blocked.get("status") if isinstance(blocked, dict) else None
    if mode == "Enforced" and blocked_status != 403:
        problems.append(f"Enforced: blocked URL was not refused with 403: {blocked}")
    elif mode == "Enforced" and not blocked.get("deny_reason"):
        problems.append(
            f"Enforced: the 403 did not come from the platform proxy (no x-deny-reason): {blocked}"
        )
    if mode == "Audit" and not _answered(blocked):
        problems.append(
            f"Audit: blocked URL did not answer 200-399, Audit must only log: {blocked}"
        )
    return problems


def check_live_coder(foundry: da.FoundryOps, policy: da.EgressPolicy) -> list[str]:
    """The deployed coder must carry this policy, in this mode, with these rules."""
    coder = foundry.get_agent(da.CODER)
    if coder is None:
        return [f"{da.CODER} is not deployed (use --no-coder-check to verify the policy alone)"]
    live = foundry.get_version(da.CODER, coder["latest_version"])
    problems = []
    if live["rai_policy"].lower() != policy.id.lower():
        problems.append(
            f"live {da.CODER} version {coder['latest_version']} carries egress policy "
            f"{live['rai_policy'] or 'none'}, not {policy.name}"
        )
    if live["env"].get("EGRESS_FINGERPRINT") != policy.fingerprint:
        problems.append(
            f"live {da.CODER} was deployed against {live['env'].get('EGRESS_FINGERPRINT')!r}, "
            f"the policy is now {policy.fingerprint!r}: redeploy the coder"
        )
    return problems


def verify(
    *,
    config: da.Config,
    policy_id: str,
    foundry: da.FoundryOps,
    http: da.Transport,
    token: Callable[[str], str],
    keep: bool = False,
    check_coder: bool = True,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    def call(method: str, url: str, scope: str, body: dict[str, Any] | None = None) -> HttpResponse:
        headers = {"Authorization": f"Bearer {token(scope)}", "Content-Type": "application/json"}
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(1, CONFLICT_TRIES + 1):
            resp = http(da.HttpRequest(method, url, headers, data, 300.0))
            if resp.status != 409 or attempt == CONFLICT_TRIES:
                return resp
            # Measured 2026-10-12: the first call after a version turns active sometimes answers 409
            # agent_version_failed and the next one succeeds.
            print(
                f"  {resp.status} from the probe endpoint, "
                f"retrying ({attempt}/{CONFLICT_TRIES - 1})"
            )
            sleep(15)
        raise AssertionError("unreachable")

    try:
        config.check_policy_scope(policy_id)
        policy = da.read_egress_policy(http, token(da.ARM_SCOPE), policy_id)
    except da.DeployError as exc:
        print(f"FAIL {exc}")
        return 1
    print(
        f"policy {policy.name}: mode {policy.mode}, default Deny, {policy.rules} rules, "
        f"fingerprint {policy.fingerprint}"
    )
    problems = check_live_coder(foundry, policy) if check_coder else []
    for problem in problems:  # reported now: a later early return must not hide them
        print(f"FAIL {problem}")

    if foundry.get_agent(PROBE) is not None:  # a leftover from an interrupted run
        foundry.delete_agent(PROBE)
        print(f"deleted a stale {PROBE}")
    code = probe_zip()
    sha = hashlib.sha256(code).hexdigest()
    try:
        version = foundry.create_hosted_version(
            PROBE,
            cpu="0.25",
            memory="0.5Gi",
            idle_minutes=2,
            env={},
            code=code,
            sha256=sha,
            description=f"throwaway egress probe {sha[:12]}",
            rai_policy=policy.id,
        )
        for _ in range(180):
            found = foundry.get_version(PROBE, version)
            if found["status"] == "active":
                break
            if found["status"] == "failed":
                print(f"FAIL probe version failed: {found.get('error')}")
                return 1
            sleep(da.POLL_S)
        else:
            print("FAIL probe not active after 900 s")
            return 1
        # An Audit pass looks exactly like no policy at all: prove the version carries it.
        if found["rai_policy"].lower() != policy.id.lower():
            print(f"FAIL probe version carries rai_policy {found['rai_policy']!r}, not the policy")
            return 1
        invoke = (
            f"{config.project_endpoint}/agents/{PROBE}/endpoint/protocols/invocations"
            "?api-version=v1"
        )
        caps = call("POST", invoke, da.AI_SCOPE, {"op": "caps"})
        print(f"caps {caps.status}: {caps.text()[:500]}")
        reply = call("POST", invoke, da.AI_SCOPE, {"op": "probe"})
        if reply.status != 200:
            print(f"FAIL probe call {reply.status}: {reply.text()[:300]}")
            return 1
        try:
            result = json.loads(reply.body)
            allowed, blocked = result["allowed"], result["blocked"]
            if not isinstance(allowed, dict) or not isinstance(blocked, dict):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            print(f"FAIL malformed probe reply: {reply.text()[:300]}")
            return 1
        print(json.dumps({"allowed": allowed, "blocked": blocked}, indent=2))
        probe_problems = judge(policy.mode, allowed, blocked)
        for problem in probe_problems:
            print(f"FAIL {problem}")
        problems += probe_problems
        if not problems:
            verdict = (
                "refused by the proxy (403, " + str(blocked["deny_reason"]) + ")"
                if policy.mode == "Enforced"
                else "let through (audit only)"
            )
            print(f"PASS {policy.mode}: {allowed['url']} allowed, {blocked['url']} {verdict}")
        return 1 if problems else 0
    finally:
        if not keep:
            try:
                foundry.delete_agent(PROBE)
                print(f"{PROBE} deleted")
            except Exception as exc:  # never mask the verdict; the operator deletes by hand
                print(
                    f"warning: {PROBE} not deleted ({type(exc).__name__}), delete it by hand",
                    file=sys.stderr,
                )


def main(argv: list[str]) -> int:  # pragma: no cover - real Azure clients
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--policy-id", default=os.environ.get("EGRESS_POLICY_ID", ""))
    parser.add_argument(
        "--no-coder-check",
        action="store_true",
        help="skip the live sdlc-coder check (a stack where the coder is not deployed)",
    )
    parser.add_argument("--keep", action="store_true", help="leave the probe agent deployed")
    args = parser.parse_args(argv)

    from azure.ai.projects import AIProjectClient
    from azure.identity import AzureCliCredential

    try:
        config = da.Config.resolve(os.environ, terraform_outputs=da.terraform_outputs)
        policy_id = args.policy_id or config.egress_policy_id
        if policy_id in ("", da.EGRESS_OFF):
            raise da.DeployError(
                "no egress policy to verify (pass --policy-id, set EGRESS_POLICY_ID "
                "or enable coder_egress_mode and apply terraform)"
            )
        da.policy_id_parts(policy_id)
    except da.DeployError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    credential = AzureCliCredential()
    foundry = da.SdkFoundry(
        AIProjectClient(endpoint=config.project_endpoint, credential=credential)
    )
    return verify(
        config=config,
        policy_id=policy_id,
        foundry=foundry,
        http=da.urllib_transport,
        token=lambda scope: credential.get_token(scope).token,
        keep=args.keep,
        check_coder=not args.no_coder_check,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
