"""Folding events into state.json: determinism, environments from the CD record, flow, archive."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from sdlc_agents.ledger import events, fold, model
from tests.ledger.conftest import NOW, ticket_event, ticket_of


def deploy_doc(history: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"version": 1, "staging": None, "prod": None, "previous_prod": None, "history": history, **extra}


def hop(
    action: str,
    sha: str,
    at: str,
    *,
    env: str = "staging",
    pr: int | None = None,
    reason: str | None = None,
    issue: int | None = None,
) -> dict[str, Any]:
    return {
        "at": at,
        "action": action,
        "env": env,
        "sha": sha,
        "version": f"main-{sha[:7]}",
        "run_url": f"https://github.com/stevengonsalvez/foundry-autonomous-sdlc/actions/runs/{sha[:4]}",
        "reason": reason,
        "issue": issue,
        "pr": pr,
        "includes": [{"pr": pr, "issue": issue, "sha": sha}] if pr else [],
    }


def env_event(deploy: dict[str, Any], at: str) -> dict[str, Any]:
    return events.make("env.changed", at, {"deploy": deploy}, source="cd")


def all_tickets(real) -> list[dict[str, Any]]:
    return [ticket_event(item) for item in real.values()]


def test_fold_is_deterministic_and_rebuilds_from_the_event_log(real) -> None:
    evs = all_tickets(real)
    doc = fold.fold(evs, NOW)
    assert doc["ledger"]["events"] == 22 and len(doc["tickets"]) == 22
    again = fold.fold(list(evs), NOW)
    assert json.dumps(doc, sort_keys=True) == json.dumps(again, sort_keys=True)
    half = fold.fold(evs[:10], NOW)
    resumed = fold.fold(evs[10:], NOW, base=half)
    assert json.dumps(resumed, sort_keys=True) == json.dumps(doc, sort_keys=True)


def test_an_event_seen_twice_changes_nothing(real) -> None:
    ev = ticket_event(real[12])
    doc = fold.empty(NOW)
    assert fold.apply(doc, ev) is True and fold.apply(doc, ev) is False
    assert doc["seq"] == 1


def test_an_older_fact_never_overwrites_a_newer_one(real) -> None:
    newer = ticket_event(real[12])
    older_item = copy.deepcopy(real[12])
    older_item["state_data"]["stages"] = older_item["state_data"]["stages"][:3]
    older_item["state_data"]["escalation"] = None
    older = ticket_event(older_item)
    doc = fold.fold([newer, older], NOW)
    assert doc["tickets"][0]["sdlc_stage"] == "stage:released"


def test_before_cd_existed_a_release_counts_as_published_straight_to_prod(real) -> None:
    doc = fold.fold(all_tickets(real), NOW)
    t12 = next(t for t in doc["tickets"] if t["issue"] == 12)
    assert t12["env"] == "prod" and t12["stage"] == "prod"
    assert t12["hops"][0]["action"] == "legacy-publish" and "before the CD pipeline existed" in t12["hops"][0]["detail"]
    assert doc["environments"]["source"] == "none"


def test_a_merge_after_cd_started_waits_in_staging_then_reaches_prod(real) -> None:
    item = copy.deepcopy(real[12])
    sha = item["state_data"]["pr"]["merge_sha"]
    first = hop("stage", "f" * 40, "2026-10-09T10:00:00Z")  # CD began before this merge
    t_stage = hop("stage", sha, "2026-10-10T15:20:00Z", pr=13, issue=12)
    doc = fold.fold([ticket_event(item), env_event(deploy_doc([first, t_stage]), "2026-10-10T15:20:00Z")], NOW)
    t = doc["tickets"][0]
    assert t["env"] == "staging" and t["stage"] == "staging" and [h["status"] for h in t["hops"]] == ["success"]
    assert "waiting for staging" in t["summary"]
    promote = hop("promote", sha, "2026-10-10T15:35:00Z", env="prod", pr=13, issue=12)
    doc = fold.fold([env_event(deploy_doc([first, t_stage, promote]), "2026-10-10T15:35:00Z")], NOW, base=doc)
    t = doc["tickets"][0]
    assert "running in production" in t["summary"]  # the plain line follows the overlay
    assert (
        t["env"] == "prod"
        and t["stage"] == "prod"
        and t["gates"]["smoke"] == "success"
        and t["gates"]["soak"] == "success"
    )
    assert doc["environments"]["history"][0]["action"] == "promote"


@pytest.mark.parametrize(
    ("reason", "smoke", "soak"),
    [("smoke failed on staging", "failure", None), ("soak: probe failed at minute 4", "success", "failure")],
)
def test_a_failed_smoke_or_soak_rolls_back_and_shows_as_escalated(real, reason, smoke, soak) -> None:
    item = copy.deepcopy(real[12])
    sha = item["state_data"]["pr"]["merge_sha"]
    first = hop("stage", "f" * 40, "2026-10-09T10:00:00Z")
    history = [
        first,
        hop("stage", sha, "2026-10-10T15:20:00Z", pr=13, issue=12),
        hop("rollback", sha, "2026-10-10T15:30:00Z", pr=13, issue=12, reason=reason),
    ]
    doc = fold.fold([ticket_event(item), env_event(deploy_doc(history), "2026-10-10T15:30:00Z")], NOW)
    t = doc["tickets"][0]
    assert t["env"] == "rolled-back" and t["stage"] == "escalated" and "rolled-back" in t["flags"]
    assert t["escalation"]["label"] == "escalated:deploy-failed" and reason in t["escalation"]["reasons"][0]
    assert t["gates"].get("smoke") == smoke and t["gates"].get("soak") == soak
    assert doc["flow"]["change_failure"]["failed"] == 1
    assert doc["environments"]["rollbacks"] == 1
    # a later successful build that includes the change clears the flag again
    good = hop("promote", "9" * 40, "2026-10-10T16:30:00Z", env="prod", pr=13, issue=12)
    doc = fold.fold([env_event(deploy_doc([*history, good]), "2026-10-10T16:30:00Z")], NOW, base=doc)
    assert doc["tickets"][0]["env"] == "prod" and doc["tickets"][0]["escalation"] is None


def test_a_superseded_build_carries_its_tickets_to_prod_with_the_newer_build(real) -> None:
    item = copy.deepcopy(real[12])
    sha = item["state_data"]["pr"]["merge_sha"]
    first = hop("stage", "f" * 40, "2026-10-09T10:00:00Z")
    newer = hop("promote", "8" * 40, "2026-10-10T16:00:00Z", env="prod")
    newer["includes"] = [{"pr": 13, "issue": 12, "sha": sha}, {"pr": 14, "issue": None, "sha": "8" * 40}]
    history = [
        first,
        hop("stage", sha, "2026-10-10T15:20:00Z", pr=13, issue=12),
        hop("skip", sha, "2026-10-10T15:40:00Z", pr=13, issue=12),
        newer,
    ]
    doc = fold.fold([ticket_event(item), env_event(deploy_doc(history), "2026-10-10T16:00:00Z")], NOW)
    t = doc["tickets"][0]
    assert t["env"] == "prod" and [h["status"] for h in t["hops"]] == ["success", "skipped", "success"]
    outcomes = {r["sha"]: r["outcome"] for r in doc["flow"]["change_failure"]["per_release"]}
    assert outcomes[sha] == "skipped" and outcomes["8" * 40] == "ok"


def test_flow_metrics_cover_lead_time_gates_defects_and_counts(real) -> None:
    doc = fold.fold(all_tickets(real), NOW)
    flow = doc["flow"]
    assert flow["lead_time"]["median_s"] > 0 and {x["issue"] for x in flow["lead_time"]["by_ticket"]} >= {12, 24, 25}
    assert flow["gate_first_pass"]["test"]["total"] >= 3
    assert any(d["issue"] == 25 and d["severity"] == "s3" and d["owner"] == "api" for d in flow["defects"])
    assert sum(flow["counts"].values()) == 6 and flow["counts"]["prod"] == 5 and flow["counts"]["escalated"] == 1


def test_agents_view_lists_the_ten_agents_and_the_ledger(real) -> None:
    doc = fold.fold(all_tickets(real), NOW)
    names = [a["name"] for a in doc["agents"]]
    assert len(names) == 11 and "sdlc-ledger" in names and names[0] == "sdlc-orchestrator"
    gate = next(a for a in doc["agents"] if a["name"] == "sdlc-req-gate")
    assert gate["calls_total"] > 10 and gate["usd"] > 0 and gate["state"] == "idle"
    assert next(a for a in doc["agents"] if a["name"] == "sdlc-ledger")["state"] == "unknown"


def test_a_tick_event_shows_up_as_last_tick_lock_holder_errors_and_retries(real) -> None:
    tick = events.make(
        "tick.finished",
        "2026-10-10T21:00:00Z",
        {
            "started_at": "2026-10-10T20:59:00Z",
            "finished_at": "2026-10-10T21:00:00Z",
            "lock": "acquired",
            "objects": [
                {"number": 24, "kind": "issue", "action": "feasibility", "result": "ok", "detail": ""},
                {"number": 25, "kind": "issue", "action": "review", "result": "deferred", "detail": "HTTP 429"},
                {"number": 17, "kind": "issue", "action": "none", "result": "ok", "detail": ""},
            ],
            "errors": ["metrics: boom"],
            "calls": [{"agent": "sdlc-feasibility", "in": 10, "out": 5, "usd": 0.001}],
            "model_calls": 1,
        },
    )
    doc = fold.fold([*all_tickets(real), tick], "2026-10-10T21:02:00Z")
    agents = {a["name"]: a for a in doc["agents"]}
    assert agents["sdlc-orchestrator"]["state"] == "error" and "acquired" in agents["sdlc-orchestrator"]["lock_holder"]
    assert agents["sdlc-orchestrator"]["current_object"] == 24
    assert (
        agents["sdlc-feasibility"]["calls_last_tick"] == 1
        and agents["sdlc-feasibility"]["last_active_at"] == "2026-10-10T21:00:00Z"
    )
    assert agents["sdlc-reviewer"]["retries"] == 1 and agents["sdlc-reviewer"]["last_error"]["detail"] == "HTTP 429"
    stale = fold.fold([tick], "2026-10-10T21:30:00Z")
    assert next(a for a in stale["agents"] if a["name"] == "sdlc-orchestrator")["state"] == "error"


def test_billed_spend_is_shown_next_to_the_ledger_estimate_and_the_gap_is_never_hidden(real) -> None:
    billed = events.make(
        "billing.observed",
        NOW,
        {
            "source": "azure-cost-management",
            "billed_usd": 13.02,
            "currency": "USD",
            "as_of": NOW,
            "by_meter": [{"name": "Azure Container Apps", "usd": 6.74}],
        },
        source="ledger",
    )
    metrics = events.make(
        "metrics.observed",
        NOW,
        {"usd": 1.86, "orchestrator_usd": 0.76, "issues": 22, "generated_at": NOW},
        source="reconcile",
    )
    invoked = events.make(
        "ledger.invoked",
        NOW,
        {"op": "ingest", "seconds": 10, "usd": 0.004, "issues": [12], "mode": "hosted"},
        source="ledger",
    )
    doc = fold.fold([*all_tickets(real), billed, metrics, invoked], NOW)
    cost = doc["cost"]
    assert cost["gap"]["billed_usd"] == 13.02 and cost["gap"]["ledger_usd"] == pytest.approx(1.8633, abs=1e-3)
    assert cost["gap"]["gap_usd"] == pytest.approx(11.157, abs=3e-3) and cost["gap"]["ratio"] == pytest.approx(
        6.98, abs=0.02
    )
    # 13.02 USD is inside the 35 USD cap and the 32 USD halt line
    assert (
        cost["totals"]["over_cap"] is False
        and cost["totals"]["halted"] is False
        and cost["totals"]["ledger_usd"] == 0.004
    )
    later = "2026-10-11T23:00:00Z"
    over = events.make(
        "billing.observed",
        later,
        {"source": "azure-cost-management", "billed_usd": 36.0, "currency": "USD", "as_of": later, "by_meter": []},
        source="ledger",
    )
    past = fold.fold([*all_tickets(real), billed, metrics, invoked, over], later)["cost"]["totals"]
    assert past["over_cap"] is True and past["halted"] is True
    t12 = next(t for t in doc["tickets"] if t["issue"] == 12)
    assert t12["cost"]["ledger_usd"] == 0.004 and t12["cost"]["usd"] == pytest.approx(0.073015, abs=1e-6)
    assert t12["cost"]["total_usd"] == pytest.approx(0.077015, abs=1e-6)  # agents plus the state-keeper share
    assert t12["cost"]["cap_used_pct"] == pytest.approx(2.57, abs=0.05)  # of the 3 USD issue cap


def test_finished_tickets_older_than_30_days_move_to_the_archive(real) -> None:
    doc = fold.fold(all_tickets(real), "2026-12-01T00:00:00Z")
    old = fold.archive_old(doc, "2026-12-01T00:00:00Z")
    # #17 is still open (the not-agent-suitable example), so it stays on the board
    assert len(old) == 21 and [t["issue"] for t in doc["tickets"]] == [17] and doc["archived"] == 21
    fresh = fold.fold(all_tickets(real), NOW)
    assert fold.archive_old(fresh, NOW) == []


def test_the_ledgers_calls_are_not_counted_twice_when_the_orchestrator_already_booked_them(real) -> None:
    """metrics.json totals.usd already holds totals.ledger_usd, so the estimate must not add it again."""
    metrics = events.make(
        "metrics.observed",
        NOW,
        {"usd": 2.0, "orchestrator_usd": 0.5, "issues": 22, "generated_at": NOW},
        source="reconcile",
    )
    invoked = events.make(
        "ledger.invoked",
        NOW,
        {"op": "ingest", "seconds": 5, "usd": 0.01, "issues": [], "mode": "hosted"},
        source="ledger",
    )
    doc = fold.fold([*all_tickets(real), metrics, invoked], NOW)
    assert doc["cost"]["totals"]["usd"] == 2.0
    quiet = fold.fold([*all_tickets(real), invoked], NOW)  # no metrics yet: the parts add up
    assert quiet["cost"]["totals"]["usd"] == pytest.approx(quiet["cost"]["totals"]["issues_usd"] + 0.01, abs=1e-6)


def test_a_thinner_record_from_the_orchestrator_does_not_blank_commits_or_the_pr_title(real) -> None:
    rich = ticket_event(real[12])
    t = copy.deepcopy(rich["data"]["ticket"])
    t["commits"] = [{"sha": "abc", "message": "test: first", "kind": "test", "files": 1}]
    t["pr"]["title"] = "Add the thing"
    thin = copy.deepcopy(rich["data"]["ticket"])
    thin["commits"] = []
    thin["pr"]["title"] = None
    thin["digest"] = "other"
    doc = fold.fold(
        [
            events.make("ticket.updated", t["updated_at"], {"ticket": t}, issue=12, source="reconcile"),
            events.make("ticket.updated", thin["updated_at"], {"ticket": thin}, issue=12),
        ],
        NOW,
    )
    got = doc["tickets"][0]
    assert got["commits"] == t["commits"] and got["pr"]["title"] == "Add the thing"


def test_summaries_and_archives_survive_a_rebuild_from_the_log(real) -> None:
    evs = all_tickets(real)
    t12 = next(e for e in evs if e["issue"] == 12)["data"]["ticket"]
    evs.append(
        events.make(
            "summary.written", NOW, {"digest": t12["digest"], "text": "Feature 12 is live."}, issue=12, source="ledger"
        )
    )
    doc = fold.fold(evs, NOW)
    assert next(t for t in doc["tickets"] if t["issue"] == 12)["summary"] == "Feature 12 is live."
    old = fold.archive_old(doc, "2026-12-01T00:00:00Z")
    assert 12 in doc["archived_ids"] and old
    # an archived ticket stays archived when reconcile or the orchestrator mention it again
    assert fold.apply(
        doc,
        events.make(
            "ticket.updated",
            t12["updated_at"],
            {"ticket": {**t12, "title": "back again"}},
            issue=12,
            source="reconcile",
        ),
    )
    assert 12 not in [t["issue"] for t in doc["tickets"]]


def test_a_release_flagged_by_cd_without_a_state_comment_still_says_why_and_links_the_run(real) -> None:
    item = copy.deepcopy(real[40])
    item["state_data"] = None
    item["labels"] = ["escalated:deploy-failed"]
    item["is_pr"] = True
    t = ticket_event(item)["data"]["ticket"]
    t["pr"] = {"number": 40, "url": "u", "branch": "b", "head": "h", "merge_sha": "d" * 40, "title": None}
    hop = {
        "sha": "d" * 40,
        "version": "main-ddddddd",
        "run_url": "https://github.com/stevengonsalvez/foundry-autonomous-sdlc/actions/runs/7",
        "pr": 40,
        "includes": [{"pr": 40, "issue": None, "sha": "d" * 40}],
    }
    history = [
        {"at": "2026-10-11T22:00:00Z", "action": "stage", "env": "staging", **hop},
        {"at": "2026-10-11T22:05:00Z", "action": "rollback", "env": "staging", "reason": "smoke", **hop},
    ]
    doc = fold.fold(
        [
            events.make("ticket.updated", t["updated_at"], {"ticket": t}, issue=40),
            env_event(deploy_doc(history), "2026-10-11T22:05:00Z"),
        ],
        NOW,
    )
    esc = doc["tickets"][0]["escalation"]
    assert (
        esc["reasons"] == ["Release main-ddddddd rolled back: smoke"]
        and esc["evidence_url"].endswith("/runs/7")
        and esc["tried"]
    )


def test_escalation_resolution_recomputed_on_fold_and_does_not_stick(real) -> None:
    # 1. Ticket with resolved escalation
    t17 = copy.deepcopy(ticket_of(real[17]))
    t17["escalation"]["resolved"] = {"at": "2026-10-10T16:00:00Z", "by": "simulated-human", "how": "closed"}
    t17["escalation"]["open"] = False
    ev_resolved = events.make("ticket.updated", t17["updated_at"], {"ticket": t17}, issue=17, source="reconcile")
    doc1 = fold.fold([ev_resolved], NOW)
    folded17 = next(t for t in doc1["tickets"] if t["issue"] == 17)
    assert folded17["escalation"]["resolved"] is not None
    assert folded17["escalation"]["open"] is False
    assert doc1["flow"]["counts"]["escalated"] == 0

    # 2. Re-opened / re-escalated ticket arriving later (without resolved) must NOT stick via _keep_richer
    t17_reopened = copy.deepcopy(t17)
    t17_reopened["closed_at"] = None
    t17_reopened["updated_at"] = "2026-10-14T20:00:00Z"
    t17_reopened["escalation"] = {
        "label": "escalated:not-agent-suitable",
        "reasons": ["reopened and escalated again"],
        "at": "2026-10-14T20:00:00Z",
        "attempts": 0,
        "tried": [],
        "evidence_url": t17["url"],
        "resolved": None,
        "open": True,
    }
    ev_reopened = events.make(
        "ticket.updated", "2026-10-14T20:00:00Z", {"ticket": t17_reopened}, issue=17, source="orchestrator"
    )
    doc2 = fold.fold([ev_resolved, ev_reopened], NOW)
    folded17_reopened = next(t for t in doc2["tickets"] if t["issue"] == 17)
    assert folded17_reopened["escalation"]["resolved"] is None
    assert folded17_reopened["escalation"]["open"] is True
    assert doc2["flow"]["counts"]["escalated"] == 1

    # Determinism: rebuilding from scratch produces identical state
    doc3 = fold.fold([ev_resolved, ev_reopened], NOW)
    assert doc2 == doc3


def test_old_state_json_without_resolved_backwards_compatible(real) -> None:
    # Simulate an old state where tickets have escalation without "resolved" key
    ev17 = ticket_event(real[17])
    # Deliberately remove resolved and open from event ticket data
    ev17["data"]["ticket"]["escalation"].pop("resolved", None)
    ev17["data"]["ticket"]["escalation"].pop("open", None)

    doc = fold.fold([ev17], NOW)
    t17 = next(t for t in doc["tickets"] if t["issue"] == 17)
    assert "resolved" in t17["escalation"]
    assert t17["escalation"]["resolved"] is None
    assert t17["escalation"]["open"] is True


def test_rollback_on_ticket_with_earlier_resolved_escalation_replaces_with_open_synthetic_escalation(
    real,
) -> None:
    item = copy.deepcopy(real[12])
    sha = item["state_data"]["pr"]["merge_sha"]
    t = ticket_of(item)
    t["escalation"] = {
        "label": "escalated:build-failed",
        "reasons": ["earlier build failure"],
        "at": "2026-10-10T14:00:00Z",
        "attempts": 1,
        "tried": [],
        "evidence_url": t["url"],
        "resolved": {"at": "2026-10-10T14:30:00Z", "by": "human", "how": "closed"},
        "open": False,
    }
    t_ev = events.make("ticket.updated", "2026-10-10T14:30:00Z", {"ticket": t}, issue=12)
    first = hop("stage", "f" * 40, "2026-10-09T10:00:00Z")
    history = [
        first,
        hop("stage", sha, "2026-10-10T15:20:00Z", pr=13, issue=12),
        hop("rollback", sha, "2026-10-10T15:30:00Z", pr=13, issue=12, reason="smoke failed on staging"),
    ]
    doc = fold.fold([t_ev, env_event(deploy_doc(history), "2026-10-10T15:30:00Z")], NOW)
    ticket12 = doc["tickets"][0]
    assert ticket12["env"] == "rolled-back"
    assert ticket12["stage"] == "escalated"
    assert ticket12["escalation"]["label"] == model.DEPLOY_FAILED_LABEL
    assert ticket12["escalation"]["synthetic"] is True
    assert ticket12["escalation"]["resolved"] is None
    assert ticket12["escalation"]["open"] is True
    assert "smoke failed on staging" in ticket12["escalation"]["reasons"][0]


def test_the_caps_block_carries_3_32_and_35_usd() -> None:
    from sdlc_agents.ledger import fold, model

    assert (model.ISSUE_CAP_USD, model.HALT_USD, model.TOTAL_CAP_USD) == (3.0, 32.0, 35.0)
    assert fold._caps() == {"issue_usd": 3.0, "halt_usd": 32.0, "total_usd": 35.0}

