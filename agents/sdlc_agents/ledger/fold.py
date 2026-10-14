"""
Fold events into `state.json` (the document the control center reads).

    events.jsonl ──fold──▶ state.json        deterministic: the same events always give the same document

`apply` takes one event into the document, `finalise` recomputes everything derived from what the
events stored: each ticket's environment hops and board column (from the CD record), the
environments view, agent rows, spend totals with the billed-versus-ledger gap, and flow metrics.
The document can always be rebuilt from `events.jsonl` (`fold`), which is what a restarted ledger does.
Stdlib only.
"""

from __future__ import annotations

import copy
import statistics
from collections import defaultdict
from datetime import timedelta
from typing import Any

from sdlc_agents.clock import format_iso, parse_iso, seconds_between
from sdlc_agents.ledger import model
from sdlc_agents.ports import REPO

VERSION = 1
ARCHIVE_AFTER_DAYS = 30
RECENT_IDS = 1000
STALE_AFTER_S = 600

AGENTS: tuple[tuple[str, str, str], ...] = (
    ("sdlc-orchestrator", "hosted", "Runs the state machine every tick, owns all merges"),
    ("sdlc-coder", "hosted", "Writes the code in a sandbox, opens the PR"),
    ("sdlc-req-gate", "prompt", "Scores a requirement 0 to 100 and asks questions"),
    ("sdlc-product-owner", "prompt", "Simulated product owner, answers refinement questions"),
    ("sdlc-feasibility", "prompt", "Judges whether the change suits the coding agent"),
    ("sdlc-test-designer", "prompt", "Designs the failing tests that come first"),
    ("sdlc-reviewer", "prompt", "Reviews the PR diff and check results"),
    ("sdlc-triage", "prompt", "Triages a bug to severity and owner"),
    ("sdlc-ci-triage", "prompt", "Explains a red check and routes the repair"),
    ("sdlc-release-notes", "prompt", "Writes the release notes"),
    ("sdlc-ledger", "hosted", "Keeps the event log and the state this page reads"),
)

# The orchestrator action that makes each prompt agent run (machine.Kind values).
ACTION_AGENT = {
    "gate": "sdlc-req-gate",
    "rescore": "sdlc-req-gate",
    "answer": "sdlc-product-owner",
    "feasibility": "sdlc-feasibility",
    "design-tests": "sdlc-test-designer",
    "review": "sdlc-reviewer",
    "triage": "sdlc-triage",
    "ci-triage": "sdlc-ci-triage",
    "release": "sdlc-release-notes",
    "start-coder": "sdlc-coder",
    "poll-coder": "sdlc-coder",
    "reconcile-coder": "sdlc-coder",
    "coder-lost": "sdlc-coder",
}
CODER_RUNNING = ("starting", "running", "start-unconfirmed", "lease-held")


def empty(now: str) -> dict[str, Any]:
    return {
        "version": VERSION,
        "repo": REPO,
        "generated_at": now,
        "updated_at": now,
        "seq": 0,
        "board_stages": list(model.BOARD_STAGES),
        "tickets": [],
        "deploy": None,
        "environments": {"staging": None, "prod": None, "history": [], "source": "none"},
        "agents": [],
        "cost": {
            "totals": {},
            "caps": _caps(),
            "billing": None,
            "metrics": None,
            "ledger": {"invocations": 0, "seconds": 0.0, "usd": 0.0},
        },
        "flow": {},
        "archived": 0,
        "archived_ids": [],
        "summaries": {},
        "ledger": {
            "events": 0,
            "last_ingest_at": None,
            "mode": "hosted",
            "recent_ids": [],
            "last_tick": None,
            "counters": {},
            "errors": [],
        },
    }


def _caps() -> dict[str, float]:
    return {"issue_usd": model.ISSUE_CAP_USD, "halt_usd": model.HALT_USD, "total_usd": model.TOTAL_CAP_USD}


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply(doc: dict[str, Any], event: dict[str, Any]) -> bool:
    """Take one event into `doc`. False when it was already seen (nothing changed)."""
    ledger = doc["ledger"]
    if event["id"] in ledger["recent_ids"]:
        return False
    ledger["recent_ids"] = [*ledger["recent_ids"], event["id"]][-RECENT_IDS:]
    ledger["events"] += 1
    doc["seq"] += 1
    doc["updated_at"] = max(doc["updated_at"], event["at"])
    data = event["data"]
    kind = event["type"]
    if kind == "ticket.updated":
        ticket = data["ticket"]
        current = _find(doc, ticket["issue"])
        if ticket["issue"] in doc.get("archived_ids", []):
            return True  # archived tickets stay in archive.json, whatever reconcile says
        # Older facts never overwrite newer ones (events from a retried invocation can arrive late).
        if current is None or ticket.get("updated_at", "") >= current.get("updated_at", ""):
            if current is not None:
                _keep_richer(ticket, current)
            doc["tickets"] = [t for t in doc["tickets"] if t["issue"] != ticket["issue"]] + [ticket]
    elif kind == "summary.written":
        doc["summaries"][str(event["issue"])] = {"digest": data["digest"], "text": data["text"], "at": event["at"]}
    elif kind == "summary.failed":
        doc["summaries"][str(event["issue"])] = {"digest": data["digest"], "text": None, "failed_at": event["at"]}
    elif kind == "env.changed":
        doc["deploy"] = data["deploy"]
    elif kind == "tick.finished":
        _apply_tick(doc, event)
    elif kind == "billing.observed":
        doc["cost"]["billing"] = {
            k: data.get(k) for k in ("source", "billed_usd", "currency", "as_of", "by_meter", "scope")
        }
    elif kind == "metrics.observed":
        doc["cost"]["metrics"] = {k: data.get(k) for k in ("usd", "orchestrator_usd", "issues", "generated_at")}
    elif kind == "ledger.invoked":
        led = doc["cost"]["ledger"]
        led["invocations"] += 1
        led["seconds"] = round(led["seconds"] + float(data["seconds"]), 3)
        led["usd"] = round(led["usd"] + float(data["usd"]), 6)
        led["last_at"] = event["at"]
        led.setdefault("by_issue", {})
        issues = [int(i) for i in data.get("issues", [])]
        for i in issues:
            led["by_issue"][str(i)] = round(led["by_issue"].get(str(i), 0.0) + float(data["usd"]) / len(issues), 6)
        doc["ledger"]["last_ingest_at"] = event["at"]
        doc["ledger"]["mode"] = data.get("mode", doc["ledger"]["mode"])
    return True


def _keep_richer(new: dict[str, Any], old: dict[str, Any]) -> None:
    """The orchestrator's record has no commits, PR title or coder-log link; reconcile's has. A thinner
    record for the same head must not blank them."""
    if (
        not new.get("commits")
        and old.get("commits")
        and (new.get("pr") or {}).get("head") == (old.get("pr") or {}).get("head")
    ):
        new["commits"] = old["commits"]
    if (
        new.get("pr")
        and old.get("pr")
        and not new["pr"].get("title")
        and new["pr"].get("number") == old["pr"].get("number")
    ):
        new["pr"]["title"] = old["pr"].get("title")


def _find(doc: dict[str, Any], issue: int) -> dict[str, Any] | None:
    return next((t for t in doc["tickets"] if t["issue"] == issue), None)


def _apply_tick(doc: dict[str, Any], event: dict[str, Any]) -> None:
    data = event["data"]
    counters = doc["ledger"]["counters"]
    last_calls: dict[str, int] = defaultdict(int)
    for call in data.get("calls", []):
        last_calls[str(call.get("agent"))] += 1
    errors: dict[str, dict[str, Any]] = {}
    for obj in data.get("objects", []):
        agent = ACTION_AGENT.get(str(obj.get("action")))
        result = obj.get("result")
        if agent is None or result not in ("error", "deferred", "capped"):
            continue
        row = counters.setdefault(agent, {"errors": 0, "retries": 0})
        row["retries" if result in ("deferred", "capped") else "errors"] += 1
        errors[agent] = {
            "at": data["finished_at"],
            "object": obj.get("number"),
            "result": result,
            "detail": model.clean(obj.get("detail", ""), 300),
        }
    for message in data.get("errors", []):
        counters.setdefault("sdlc-orchestrator", {"errors": 0, "retries": 0})["errors"] += 1
        errors["sdlc-orchestrator"] = {
            "at": data["finished_at"],
            "object": None,
            "result": "error",
            "detail": model.clean(message, 300),
        }
    doc["ledger"]["last_tick"] = {
        "started_at": data["started_at"],
        "finished_at": data["finished_at"],
        "lock": data.get("lock", ""),
        "objects": [
            {"number": o.get("number"), "kind": o.get("kind"), "action": o.get("action"), "result": o.get("result")}
            for o in data.get("objects", [])[:60]
        ],
        "calls_by_agent": dict(last_calls),
        "errors": errors,
        "model_calls": int(data.get("model_calls", 0) or 0),
        "usd_this_tick": float(data.get("usd_this_tick", 0) or 0),
        "orchestrator_usd": float(data.get("orchestrator_usd", 0) or 0),
    }


# ---------------------------------------------------------------------------
# Environments and per-ticket hops from the CD record (deploy.json)
# ---------------------------------------------------------------------------


def _relevant(entry: dict[str, Any], ticket: dict[str, Any]) -> bool:
    pr = ticket.get("pr") or {}
    merge_sha = pr.get("merge_sha")
    if merge_sha and entry.get("sha") == merge_sha:
        return True
    for inc in entry.get("includes") or []:
        if pr.get("number") and inc.get("pr") == pr["number"]:
            return True
        if inc.get("issue") == ticket["issue"] and ticket["kind"] == "issue":
            return True
    return entry.get("issue") == ticket["issue"] and ticket["kind"] == "issue"


def _merged_at(ticket: dict[str, Any]) -> str | None:
    for row in ticket["stage_history"]:
        if row.get("sdlc_stage") in ("stage:merged", "stage:released"):
            return row["at"]
    return None


def overlay(ticket: dict[str, Any], deploy: dict[str, Any] | None) -> dict[str, Any]:
    """The ticket with its environment hops, env and board column worked out from the CD record."""
    t = copy.deepcopy(ticket)
    if (t.get("escalation") or {}).get("synthetic"):
        t["escalation"] = None
    t["hops"] = [h for h in t.get("hops", []) if h.get("source") != "deploy"]
    t["gates"] = {k: v for k, v in t["gates"].items() if k not in ("smoke", "soak")}
    merged_at = _merged_at(t)
    history = sorted((deploy or {}).get("history", []), key=lambda e: e.get("at", ""))
    mine = [e for e in history if _relevant(e, t)]
    env = "none"
    hops: list[dict[str, Any]] = []
    smoke = soak = None
    for e in mine:
        action, where = e.get("action"), e.get("env", "staging")
        status = {
            "stage": "success",
            "promote": "success",
            "rollback": "rolled_back",
            "skip": "skipped",
            "fail": "failed",
        }.get(str(action), "success")
        hops.append(
            {
                "env": where,
                "status": status,
                "action": action,
                "at": e.get("at"),
                "sha": e.get("sha"),
                "version": e.get("version"),
                "run_url": e.get("run_url"),
                "detail": model.clean(e.get("reason") or "", 200) or None,
                "source": "deploy",
            }
        )
        if action == "stage":
            env, smoke, soak = "staging", None, None
        elif action == "promote":
            env, smoke, soak = "prod", "success", "success"
        elif action in ("rollback", "fail"):
            env = "rolled-back"
            reason = str(e.get("reason") or "").lower()
            if "soak" in reason:
                smoke, soak = "success", "failure"
            elif "smoke" in reason:
                smoke, soak = "failure", None
            elif "promote" in reason:
                smoke, soak = "success", "success"
            else:
                smoke = "failure"
    in_flight = (deploy or {}).get("staging") or {}
    if env == "staging" and in_flight and _relevant(in_flight, t):
        status = in_flight.get("status")
        if status in ("smoke-passed", "soaking"):
            smoke = "success"
        if status == "soaking":
            soak = "in_progress"
    if not mine and merged_at and t["sdlc_stage"] in ("stage:merged", "stage:released"):
        first_cd = history[0]["at"] if history else None
        if first_cd is None or merged_at < first_cd:
            # Before CD existed, pages.yml published main straight to the site root.
            env = "prod"
            done = next((r["at"] for r in t["stage_history"] if r.get("sdlc_stage") == "stage:released"), merged_at)
            hops.append(
                {
                    "env": "prod",
                    "status": "success",
                    "action": "legacy-publish",
                    "at": done,
                    "sha": (t.get("pr") or {}).get("merge_sha"),
                    "version": (t.get("release") or {}).get("tag"),
                    "run_url": None,
                    "detail": "published straight from main by pages.yml, before the CD pipeline existed",
                    "source": "deploy",
                }
            )
    t["hops"] = hops
    t["env"] = env
    if smoke:
        t["gates"]["smoke"] = smoke
    if soak:
        t["gates"]["soak"] = soak
    esc = t.get("escalation")
    label = (esc or {}).get("label") if esc else None
    if env == "rolled-back" and esc is not None and not esc.get("reasons"):
        # Flagged by CD with no state comment of its own: the reason and evidence are the failed run's.
        last = next((h for h in reversed(hops) if h["status"] in ("rolled_back", "failed")), None)
        if last is not None:
            esc["reasons"] = [
                f"Release {last.get('version') or ''} rolled back: {last.get('detail') or 'a gate failed'}".replace(
                    "  ", " "
                )
            ]
            esc["evidence_url"] = last.get("run_url") or esc.get("evidence_url")
            esc["tried"] = esc.get("tried") or [
                "CD built the release, deployed it to staging and ran the smoke tests.",
                "The failed gate triggered the automatic rollback to the previous artifact.",
            ]
    if env == "rolled-back" and (esc is None or esc.get("resolved") is not None):
        last = next((h for h in reversed(hops) if h["status"] in ("rolled_back", "failed")), hops[-1])
        t["escalation"] = {
            "label": model.DEPLOY_FAILED_LABEL,
            "reasons": [last.get("detail") or "Release rolled back after a failed check"],
            "at": last.get("at"),
            "attempts": 0,
            "tried": [],
            "evidence_url": last.get("run_url") or t["url"],
            "synthetic": True,
            "resolved": None,
            "open": True,
        }
        label = model.DEPLOY_FAILED_LABEL
    sdlc = t["sdlc_stage"]
    t["stage"] = model.board_stage(
        sdlc, label, env, labels=(model.DEPLOY_FAILED_LABEL,) if "deploy-failed" in t.get("flags", []) else ()
    )
    flags = [f for f in t.get("flags", []) if f != "rolled-back"]
    if env == "rolled-back":
        flags.append("rolled-back")
    t["flags"] = flags
    return t


def environments(deploy: dict[str, Any] | None) -> dict[str, Any]:
    if not deploy:
        return {"staging": None, "prod": None, "history": [], "source": "none"}
    history = sorted(deploy.get("history", []), key=lambda e: e.get("at", ""))
    rollbacks = [e for e in history if e.get("action") in ("rollback", "fail")]
    staging, prod = deploy.get("staging"), deploy.get("prod")
    return {
        "staging": _env_row("staging", staging),
        "prod": _env_row("prod", prod),
        "previous_prod": _env_row("prod", deploy.get("previous_prod")),
        "history": list(reversed(history[-60:])),
        "rollbacks": len(rollbacks),
        "source": "deploy.json",
    }


def _env_row(name: str, entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not entry:
        return None
    return {
        "name": name,
        "version": entry.get("version"),
        "sha": entry.get("sha"),
        "short": entry.get("short"),
        "promoted_at": entry.get("promoted_at") or entry.get("deployed_at"),
        "run_url": entry.get("run_url"),
        "status": entry.get("status") or ("live" if name == "prod" else None),
        "gates_cleared": list(
            entry.get("gates")
            or (
                []
                if name == "prod"
                else (["smoke"] if entry.get("status") in ("smoke-passed", "soaking", "promoted") else [])
            )
        ),
        "pr": entry.get("pr"),
        "issue": entry.get("issue"),
        "tag": entry.get("tag"),
        "includes": entry.get("includes") or [],
    }


# ---------------------------------------------------------------------------
# Derived sections
# ---------------------------------------------------------------------------


def _agents(doc: dict[str, Any], now: str) -> list[dict[str, Any]]:
    tickets = doc["tickets"]
    usage: dict[str, dict[str, Any]] = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "usd": 0.0})
    for t in tickets:
        for row in t["cost"]["by_agent"]:
            u = usage[row["agent"]]
            u["calls"] += row["calls"]
            u["in"] += row["in"]
            u["out"] += row["out"]
            u["usd"] = round(u["usd"] + row["usd"], 6)
    tick = doc["ledger"]["last_tick"]
    counters = doc["ledger"]["counters"]
    running = next(
        (t for t in tickets if (t.get("coder") or {}).get("status") in CODER_RUNNING and t["stage"] == "building"), None
    )
    rows = []
    for name, kind, role in AGENTS:
        row: dict[str, Any] = {
            "name": name,
            "kind": kind,
            "role": role,
            "state": "idle",
            "last_active_at": None,
            "calls_total": 0,
            "calls_last_tick": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "usd": 0.0,
            "current_object": None,
            "lock_holder": None,
            "errors": 0,
            "retries": 0,
            "last_error": None,
        }
        u = usage.get(name)
        if u:
            row.update(calls_total=u["calls"], tokens_in=u["in"], tokens_out=u["out"], usd=u["usd"])
        c = counters.get(name)
        if c:
            row.update(errors=c["errors"], retries=c["retries"])
        if tick:
            row["calls_last_tick"] = tick["calls_by_agent"].get(name, 0)
            if row["calls_last_tick"] or name == "sdlc-orchestrator":
                row["last_active_at"] = tick["finished_at"]
            row["last_error"] = tick["errors"].get(name)
        if name == "sdlc-orchestrator":
            if tick:
                row["lock_holder"] = f"{tick['lock']} (tick {tick['started_at']})"
                touched = [
                    o["number"]
                    for o in tick["objects"]
                    if o["result"] == "ok" and o["action"] not in ("none", "noop", "wait")
                ]
                row["current_object"] = touched[-1] if touched else None
                row["state"] = (
                    "error"
                    if tick["errors"].get(name)
                    else ("stale" if seconds_between(tick["finished_at"], now) > STALE_AFTER_S else "idle")
                )
            else:
                row["state"] = "unknown"
        elif name == "sdlc-coder":
            if running:
                row["state"] = "running"
                row["current_object"] = running["issue"]
        elif name == "sdlc-ledger":
            led = doc["cost"]["ledger"]
            row.update(calls_total=led["invocations"], usd=led["usd"], last_active_at=doc["ledger"]["last_ingest_at"])
            row["state"] = "idle" if led["invocations"] else "unknown"
        elif row["last_error"]:
            row["state"] = "error"
        elif not row["calls_total"]:
            row["state"] = "unknown"
        rows.append(row)
    return rows


def _cost(doc: dict[str, Any]) -> dict[str, Any]:
    cost = doc["cost"]
    led = cost["ledger"]
    tickets = doc["tickets"]
    by_issue = led.get("by_issue", {})
    issues_usd = round(sum(t["cost"]["usd"] for t in tickets), 6)
    ledger_usd = round(led["usd"], 6)
    metrics = cost.get("metrics") or {}
    # The orchestrator's own estimate covers its issues and its compute; the ledger's compute is added.
    # metrics.json's total already holds the ledger calls the orchestrator made (its totals.ledger_usd), so it
    # is not added again; calls nobody booked (a manual reconcile) can only make the sum larger.
    own = issues_usd + float(metrics.get("orchestrator_usd", 0) or 0) + ledger_usd
    estimate = round(max(float(metrics.get("usd", 0) or 0), own), 6)
    billing = cost.get("billing")
    gap = None
    if billing and billing.get("billed_usd") is not None:
        billed = float(billing["billed_usd"])
        gap = {
            "billed_usd": round(billed, 4),
            "ledger_usd": estimate,
            "gap_usd": round(billed - estimate, 4),
            "ratio": round(billed / estimate, 2) if estimate else None,
            "note": "Azure billed spend lags by hours and counts every meter; the ledger estimates from list prices.",
        }
    caps = _caps()
    shown = float(billing["billed_usd"]) if billing and billing.get("billed_usd") is not None else estimate
    totals = {
        "usd": estimate,
        "issues_usd": issues_usd,
        "orchestrator_usd": round(float(metrics.get("orchestrator_usd", 0) or 0), 6),
        "ledger_usd": ledger_usd,
        "billed_usd": round(shown, 4) if billing else None,
        "halted": shown >= caps["halt_usd"],
        "over_cap": shown >= caps["total_usd"],
    }
    del by_issue
    return {**cost, "totals": totals, "caps": caps, "gap": gap}


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def _flow(doc: dict[str, Any], now: str) -> dict[str, Any]:
    tickets = doc["tickets"]
    lead: list[dict[str, Any]] = []
    stage_secs: dict[str, list[float]] = defaultdict(list)
    first_gate: dict[str, list[bool]] = defaultdict(list)
    defects = []
    for t in tickets:
        prod = next((h for h in t["hops"] if h["env"] == "prod" and h["status"] == "success"), None)
        if prod and prod.get("at"):
            lead.append({"issue": t["issue"], "seconds": max(seconds_between(t["opened_at"], prod["at"]), 0)})
        per_stage: dict[str, int] = defaultdict(int)
        for row in t["stage_history"]:
            if row["seconds"] is not None and row["stage"] != "escalated":
                per_stage[row["stage"]] += row["seconds"]
        for stage, secs in per_stage.items():
            stage_secs[stage].append(secs)
        seen: set[str] = set()
        for entry in t.get("gate_history") or []:
            for gate, result in (entry.get("results") or {}).items():
                if gate not in seen:
                    seen.add(gate)
                    first_gate[gate].append(result == "success")
        if t["type"] == "bug" and t.get("triage"):
            defects.append(
                {
                    "issue": t["issue"],
                    "severity": t["triage"]["severity"],
                    "owner": t["triage"]["owner"],
                    "seconds": next((x["seconds"] for x in lead if x["issue"] == t["issue"]), None),
                }
            )
    releases = _releases(doc.get("deploy"))
    failed = sum(1 for r in releases if r["outcome"] == "failed")
    done = sum(1 for r in releases if r["outcome"] in ("ok", "failed"))
    counts = {
        s: sum(
            1
            for t in tickets
            if t["stage"] == s and (s != "escalated" or (t.get("escalation") or {}).get("open", True))
        )
        for s in model.BOARD_STAGES
    }
    return {
        "generated_at": now,
        "lead_time": {
            "median_s": _median([x["seconds"] for x in lead]),
            "by_ticket": sorted(lead, key=lambda x: x["issue"]),
        },
        "stage_medians_s": {s: _median(v) for s, v in stage_secs.items()},
        "gate_first_pass": {g: {"pass": sum(v), "total": len(v)} for g, v in sorted(first_gate.items())},
        "defects": defects,
        "change_failure": {
            "releases": done,
            "failed": failed,
            "rate": round(failed / done, 3) if done else None,
            "per_release": releases,
        },
        "counts": counts,
    }


def _releases(deploy: dict[str, Any] | None) -> list[dict[str, Any]]:
    """One row per built sha that reached staging: ok (promoted, never rolled back), failed, or pending/skipped."""
    out: dict[str, dict[str, Any]] = {}
    for e in sorted((deploy or {}).get("history", []), key=lambda e: e.get("at", "")):
        sha = e.get("sha")
        if not sha:
            continue
        row = out.setdefault(sha, {"sha": sha, "version": e.get("version"), "at": e.get("at"), "outcome": "pending"})
        action = e.get("action")
        if action == "promote":
            row["outcome"] = "ok"
        elif action in ("rollback", "fail"):
            row["outcome"] = "failed"
        elif action == "skip":
            row["outcome"] = "skipped"
        row["last_at"] = e.get("at")
    return list(out.values())


def archive_old(doc: dict[str, Any], now: str, days: int = ARCHIVE_AFTER_DAYS) -> list[dict[str, Any]]:
    """Remove and return finished tickets closed more than `days` ago (they go to archive.json)."""
    cutoff = format_iso(parse_iso(now) - timedelta(days=days))
    old = [t for t in doc["tickets"] if t["stage"] in ("prod", "escalated") and (t.get("closed_at") or "9") < cutoff]
    if old:
        keep = {t["issue"] for t in old}
        doc["tickets"] = [t for t in doc["tickets"] if t["issue"] not in keep]
        doc["archived"] += len(old)
        doc["archived_ids"] = sorted({*doc.get("archived_ids", []), *keep})
    return old


def finalise(doc: dict[str, Any], now: str) -> dict[str, Any]:
    """Recompute every derived section. Cheap and pure, so it runs after every ingest."""
    led_by_issue = doc["cost"]["ledger"].get("by_issue", {})
    tickets = []
    for t in doc["tickets"]:
        t = overlay(t, doc.get("deploy"))
        if t.get("escalation"):
            if "resolved" not in t["escalation"]:
                t["escalation"]["resolved"] = None
            if "open" not in t["escalation"]:
                t["escalation"]["open"] = t["escalation"]["resolved"] is None
        saved = doc.get("summaries", {}).get(str(t["issue"]))
        if saved and saved.get("digest") == t.get("digest"):
            t["summary"] = saved["text"]
        else:
            # the plain line was written before the deploy overlay moved the ticket, so say where it is now
            t["summary"] = model.summary_text(
                t["title"], t["type"], t["stage"], t.get("escalation"), t.get("release"), t["cost"]["usd"]
            )
        share = round(float(led_by_issue.get(str(t["issue"]), 0.0)), 6)
        t["cost"]["ledger_usd"] = share
        t["cost"]["total_usd"] = round(t["cost"]["usd"] + share, 6)
        t["cost"]["cap_used_pct"] = round(100.0 * t["cost"]["total_usd"] / model.ISSUE_CAP_USD, 2)
        tickets.append(t)
    doc["tickets"] = sorted(tickets, key=lambda t: t["issue"])
    doc["environments"] = environments(doc.get("deploy"))
    doc["agents"] = _agents(doc, now)
    doc["cost"] = _cost(doc)
    doc["flow"] = _flow(doc, now)
    doc["generated_at"] = now
    return doc


def fold(events: list[dict[str, Any]], now: str, base: dict[str, Any] | None = None) -> dict[str, Any]:
    doc = copy.deepcopy(base) if base else empty(now)
    for ev in events:
        apply(doc, ev)
    return finalise(doc, now)
