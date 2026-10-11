"""
Build the control center's test fixture from the real 2026-10-10 tickets.

    python agents/tests/ledger/make_fixture.py            write apps/control-center/test/fixtures/state.sample.json
    python agents/tests/ledger/make_fixture.py --check    fail when the committed fixture is out of date

The 22 tickets are the real state comments of this repository's first run, folded by the real ledger code.
What GitHub did not have yet is added, and labelled as fixture data in `ledger.errors`: a CD history (a clean
promotion, a smoke failure that rolled back, a superseded build), one orchestrator tick, Azure's billed spend as
read on 2026-10-11 (13.02 USD) and two ledger invocations. Nothing here is published to Pages.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "agents"))

from sdlc_agents.ledger import events, fold, model  # noqa: E402

OUT = ROOT / "apps" / "control-center" / "test" / "fixtures" / "state.sample.json"
NOW = "2026-10-11T20:05:00Z"
RUN = "https://github.com/stevengonsalvez/foundry-autonomous-sdlc/actions/runs/"


def entry(action: str, env: str, at: str, item: dict[str, Any], run: int, **extra: Any) -> dict[str, Any]:
    pr = item["state_data"]["pr"]
    sha = pr["merge_sha"]
    return {"at": at, "action": action, "env": env, "sha": sha, "version": (item["state_data"].get("release") or {}).get("tag") or f"main-{sha[:7]}",
            "run_url": f"{RUN}{run}", "reason": extra.pop("reason", None), "pr": pr["number"], "issue": item["number"],
            "includes": [{"pr": pr["number"], "issue": item["number"], "sha": sha}], **extra}


def build() -> dict[str, Any]:
    history = json.loads((HERE / "fixtures" / "history.json").read_text())
    by = {h["number"]: h for h in history}
    evs: list[dict[str, Any]] = []
    for h in history:
        t = model.ticket(number=h["number"], kind="pr" if h["is_pr"] else "issue", title=h["title"], author=h["author"],
                         opened_at=h["created_at"], closed_at=h["closed_at"], labels=tuple(h["labels"]),
                         state_data=h["state_data"], comment_ids=h["comment_ids"])
        evs.append(events.make("ticket.updated", t["updated_at"], {"ticket": t}, issue=t["issue"], source="reconcile"))
    first = {"at": "2026-10-10T14:00:00Z", "action": "stage", "env": "staging", "sha": "0" * 40, "version": "main-0000000",
             "run_url": f"{RUN}1", "reason": None, "pr": None, "issue": None, "includes": []}
    hist = [
        first,
        entry("stage", "staging", "2026-10-10T15:16:00Z", by[12], 2),
        entry("promote", "prod", "2026-10-10T15:28:00Z", by[12], 2),
        entry("stage", "staging", "2026-10-10T17:12:00Z", by[25], 3),
        entry("rollback", "staging", "2026-10-10T17:15:00Z", by[25], 3, reason="smoke failed on staging"),
        entry("stage", "staging", "2026-10-10T17:27:00Z", by[24], 4),
        entry("skip", "staging", "2026-10-10T17:33:00Z", by[24], 4, reason="superseded by a newer merge"),
        entry("stage", "staging", "2026-10-10T17:34:00Z", by[40], 5),
        entry("promote", "prod", "2026-10-10T17:46:00Z", by[40], 5),
    ]
    hist[-1]["includes"] = [{"pr": 40, "issue": None, "sha": hist[-1]["sha"]}, {"pr": 29, "issue": 24, "sha": by[24]["state_data"]["pr"]["merge_sha"]}]
    prod = {"sha": hist[-1]["sha"], "short": hist[-1]["sha"][:7], "version": hist[-1]["version"], "promoted_at": hist[-1]["at"],
            "run_url": hist[-1]["run_url"], "gates": ["smoke", "soak"], "pr": 40, "issue": None, "tag": "prod/20261010-174600-" + hist[-1]["sha"][:7],
            "includes": hist[-1]["includes"], "status": "live"}
    staging = {**prod, "status": "promoted", "deployed_at": hist[-2]["at"]}
    deploy = {"version": 1, "staging": staging, "prod": prod, "previous_prod": None, "history": hist}
    evs.append(events.make("env.changed", hist[-1]["at"], {"deploy": deploy}, source="cd"))
    evs.append(events.make("tick.finished", "2026-10-10T21:46:00Z", {
        "started_at": "2026-10-10T21:45:20Z", "finished_at": "2026-10-10T21:46:00Z", "lock": "acquired",
        "objects": [{"number": 40, "kind": "pr", "action": "release", "result": "ok", "detail": "released v0.3.1"},
                    {"number": 17, "kind": "issue", "action": "none", "result": "ok", "detail": "terminal"},
                    {"number": 38, "kind": "pr", "action": "ci-triage", "result": "deferred", "detail": "HTTP 429 rate_limit_exceeded"}],
        "errors": [], "model_calls": 2, "calls": [{"agent": "sdlc-release-notes", "in": 900, "out": 300, "usd": 0.0008},
                                                  {"agent": "sdlc-ci-triage", "in": 1200, "out": 200, "usd": 0.0007}],
        "usd_this_tick": 0.0015, "orchestrator_usd": 0.0156, "total_usd": 1.860893}, source="orchestrator"))
    evs.append(events.make("metrics.observed", "2026-10-10T21:45:50Z", {"usd": 1.860893, "orchestrator_usd": 0.761619, "issues": 22,
                                                                         "generated_at": "2026-10-10T21:45:50Z"}, source="reconcile"))
    evs.append(events.make("billing.observed", "2026-10-11T20:00:00Z", {
        "source": "azure-cost-management", "billed_usd": 13.0194, "currency": "USD", "as_of": "2026-10-11T20:00:00Z", "scope": "rg-fsdlcd-demo",
        "by_meter": [{"name": "Azure Container Apps", "usd": 6.7413}, {"name": "Foundry Tools", "usd": 5.9741},
                     {"name": "Foundry Models", "usd": 0.3033}, {"name": "Key Vault", "usd": 0.0007}]}, source="ledger"))
    for at, issues, usd in (("2026-10-11T20:01:00Z", [12, 24], 0.0031), ("2026-10-11T20:04:00Z", [40], 0.0029)):
        evs.append(events.make("ledger.invoked", at, {"op": "ingest", "seconds": 9.0, "usd": usd, "compute_usd": usd, "model_usd": 0.0,
                                                      "events": 3, "issues": issues, "mode": "hosted", "summaries": 0}, source="ledger"))
    doc = fold.fold(evs, NOW)
    doc["ledger"]["errors"] = [{"at": NOW, "message": "fixture: CD history, one tick, billing and ledger invocations are synthetic; tickets are real"}]
    return doc


def render() -> str:
    return json.dumps(build(), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text() != text:
            print(f"{OUT} is out of date: run python agents/tests/ledger/make_fixture.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
