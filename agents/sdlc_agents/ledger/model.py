"""
The ticket record the control center shows, derived by code from what the orchestrator already keeps.

    state comment (JSON) + issue metadata + PR facts + CD hops ──▶ ticket   (pure functions)

Every number on the board comes from here. No model writes a number; the only free text a model
may add is `summary`, and it is replaced by a deterministic sentence when no model answer exists.
All text that came from GitHub or a model is untrusted: it is bounded, stripped of control
characters and run through the secret redactor before it is stored, and the UI renders it as text.

Board stages (docs/architecture.md, "Control center"):

    backlog  refining  feasible  tests  building  review  staging  prod  escalated

Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sdlc_agents import state as sdlc_state
from sdlc_agents.clock import seconds_between
from sdlc_agents.ports import REPO
from sdlc_agents.sanitise import one_line, redact_secrets

VERSION = 1
ISSUE_CAP_USD = 1.0
HALT_USD = 4.5
TOTAL_CAP_USD = 5.0

BOARD_STAGES = ("backlog", "refining", "feasible", "tests", "building", "review", "staging", "prod", "escalated")

# `stage:ready` is a scored requirement waiting for the feasibility call, so it still belongs to
# requirement work. `stage:merged` and `stage:released` mean "merged to main": where the change is
# running depends on the environment hops (see board_stage).
_STAGE_TO_BOARD = {
    sdlc_state.NEEDS_REFINEMENT: "refining",
    sdlc_state.READY: "refining",
    sdlc_state.FEASIBLE: "feasible",
    sdlc_state.TESTS_WRITTEN: "tests",
    sdlc_state.BUILDING: "building",
    sdlc_state.IN_REVIEW: "review",
    sdlc_state.MERGED: "staging",
    sdlc_state.RELEASED: "staging",
}

ENVS = ("none", "staging", "prod", "rolled-back")
HOP_STATUSES = ("in_progress", "success", "failed", "rolled_back", "skipped")
DEPLOY_FAILED_LABEL = "escalated:deploy-failed"

# Which gate names the cost-free CI checks and CD steps report.
GATE_NAMES = ("test", "coverage", "e2e", "gitleaks", "tdd-order", "agent-scope", "review", "smoke", "soak")

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class TicketError(ValueError):
    """The input cannot become a ticket."""


# ---------------------------------------------------------------------------
# Text hygiene
# ---------------------------------------------------------------------------


def clean(text: Any, limit: int = 300) -> str:
    """Untrusted text made safe to store: no control characters, no token-shaped strings, bounded."""
    flat = _CONTROL.sub("", str(text if text is not None else ""))
    return one_line(redact_secrets(flat), limit)


def scrub(value: Any, *, limit: int = 600, depth: int = 0) -> Any:
    """Recursively clean every string in a JSON value (keys included are left alone: they are ours)."""
    if depth > 12:
        raise TicketError("value nested too deeply")
    if isinstance(value, str):
        return clean(value, limit)
    if isinstance(value, list):
        return [scrub(v, limit=limit, depth=depth + 1) for v in value]
    if isinstance(value, dict):
        return {str(k): scrub(v, limit=limit, depth=depth + 1) for k, v in value.items()}
    return value


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


def is_escalation(label: str | None) -> bool:
    return bool(label) and str(label).startswith("escalated:")


def board_stage(sdlc_stage: str | None, escalation: str | None, env: str, *, labels: tuple[str, ...] = ()) -> str:
    """The board column for an object: escalations and rolled-back releases win, then the stage label,
    and a merged change sits in staging until the environment hops say it reached prod."""
    if is_escalation(escalation) or env == "rolled-back" or DEPLOY_FAILED_LABEL in labels:
        return "escalated"
    if sdlc_stage is None:
        return "backlog"
    stage = _STAGE_TO_BOARD.get(sdlc_stage)
    if stage is None:
        raise TicketError(f"unknown stage {sdlc_stage!r}")
    if stage == "staging" and env == "prod":
        return "prod"
    return stage


def stage_history(opened_at: str, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Timestamped transitions, each with the seconds spent before the next one.

    Starts with the backlog entry at the time the issue was opened. The last entry has `seconds` None:
    the UI measures an open stage up to the time it is shown."""
    rows: list[dict[str, Any]] = [{"stage": "backlog", "sdlc_stage": None, "at": opened_at}]
    for entry in entries:
        label = str(entry["stage"])
        at = str(entry["at"])
        board = "escalated" if label.startswith("escalated:") else _STAGE_TO_BOARD.get(label, "backlog")
        rows.append({"stage": board, "sdlc_stage": label, "at": at})
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        nxt = rows[i + 1]["at"] if i + 1 < len(rows) else None
        seconds = max(seconds_between(row["at"], nxt), 0) if nxt else None
        out.append({**row, "seconds": seconds})
    return out


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


def cost_block(data: dict[str, Any], *, ledger_usd: float = 0.0) -> dict[str, Any]:
    """Per-ticket spend from the state comment, with the ledger's own compute share and the cap bar."""
    raw = data.get("cost") or {}
    calls = [c for c in raw.get("calls", []) if isinstance(c, dict)]
    by_agent: dict[str, dict[str, Any]] = {}
    tokens_in = tokens_out = 0
    for call in calls:
        agent = clean(call.get("agent", "unknown"), 60)
        row = by_agent.setdefault(agent, {"agent": agent, "calls": 0, "in": 0, "out": 0, "usd": 0.0})
        row["calls"] += int(call.get("count", 1) or 1)
        row["in"] += int(call.get("in", 0) or 0)
        row["out"] += int(call.get("out", 0) or 0)
        row["usd"] = round(row["usd"] + float(call.get("usd", 0) or 0), 6)
        tokens_in += int(call.get("in", 0) or 0)
        tokens_out += int(call.get("out", 0) or 0)
    model_usd = round(sum(r["usd"] for r in by_agent.values()), 6)
    coder_usd = round(float(raw.get("coder_usd", 0) or 0), 6)
    coder_model = round(float(raw.get("coder_model_usd", 0) or 0), 6)
    # The state comment's usd is the orchestrator's own total (it is the number the 1 USD cap checks).
    state_usd = round(float(raw.get("usd", 0) or 0), 6)
    total = round(max(state_usd, model_usd + coder_usd + coder_model) + ledger_usd, 6)
    return {
        "usd": total,
        "model_usd": model_usd,
        "coder_usd": coder_usd,
        "coder_model_usd": coder_model,
        "ledger_usd": round(ledger_usd, 6),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "calls": sum(r["calls"] for r in by_agent.values()),
        "coder_seconds": int(raw.get("coder_seconds", 0) or 0),
        "cap_usd": ISSUE_CAP_USD,
        "cap_used_pct": round(100.0 * total / ISSUE_CAP_USD, 2),
        "by_agent": sorted(by_agent.values(), key=lambda r: (-r["usd"], r["agent"])),
    }


# ---------------------------------------------------------------------------
# Trails: questions back, reviews, what the agent tried
# ---------------------------------------------------------------------------


def qa_trail(quality: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Refinement questions with their (simulated product owner) answers, one entry per question."""
    if not quality:
        return []
    out: list[dict[str, Any]] = []
    for round_ in quality.get("history", []) or []:
        if not isinstance(round_, dict):
            continue
        questions = [q for q in round_.get("questions", []) if isinstance(q, str)]
        answers = [a for a in round_.get("answers", []) if isinstance(a, str)]
        for i, question in enumerate(questions):
            answer = answers[i] if i < len(answers) else None
            if answer and answer.startswith("[Simulated product owner]"):
                answer = answer[len("[Simulated product owner]") :].strip()
            out.append(
                {
                    "round": int(round_.get("round", 0) or 0),
                    "score": round_.get("score"),
                    "question": clean(question, 500),
                    "answer": clean(answer, 900) if answer else None,
                    "answered_by": "simulated product owner" if answer else None,
                }
            )
    return out


def reviews_trail(data: dict[str, Any]) -> list[dict[str, Any]]:
    review = data.get("review")
    if not isinstance(review, dict) or not review.get("verdict"):
        return []
    findings = [
        {
            "severity": clean(f.get("severity", "info"), 20),
            "area": clean(f.get("area", ""), 40),
            "detail": clean(f.get("detail", ""), 600),
        }
        for f in review.get("findings", [])
        if isinstance(f, dict)
    ]
    return [
        {
            "verdict": review["verdict"],
            "head": str(review.get("head", ""))[:40],
            "round": int(review.get("rounds", 0) or 0),
            "findings": findings,
        }
    ]


def ci_triage_block(data: dict[str, Any]) -> dict[str, Any] | None:
    triage = data.get("ci_triage")
    revise = data.get("ci_revise")
    if not isinstance(triage, dict) and not isinstance(revise, dict):
        return None
    out: dict[str, Any] = {}
    if isinstance(triage, dict):
        out.update(
            {
                "cause": clean(triage.get("cause", ""), 40),
                "explanation": clean(triage.get("explanation", ""), 600),
                "test_files": [clean(f, 160) for f in triage.get("test_files", [])[:20]],
            }
        )
    if isinstance(revise, dict):
        out["revise_rounds"] = int(revise.get("rounds", 0) or 0)
        out["check"] = clean(revise.get("check", ""), 40)
    return out


def tried(data: dict[str, Any]) -> list[str]:
    """What the agents did before the pipeline stopped, as short deterministic sentences."""
    steps: list[str] = []
    quality = data.get("quality")
    if isinstance(quality, dict) and quality.get("score") is not None:
        steps.append(
            f"Requirement scored {quality['score']}/100 after {int(quality.get('rounds', 0) or 0)} refinement round(s)."
        )
    feas = data.get("feasibility")
    if isinstance(feas, dict) and "suitable" in feas:
        steps.append(
            "Feasibility: "
            + ("suitable" if feas["suitable"] else "not suitable")
            + (f", risk {clean(feas.get('risk'), 20)}." if feas.get("risk") else ".")
        )
    repair = data.get("tests_repair")
    if isinstance(repair, dict) and repair.get("rounds"):
        steps.append(f"Test designer repaired its tests {int(repair['rounds'])} time(s).")
    coder = data.get("coder")
    if isinstance(coder, dict) and coder.get("job_id"):
        steps.append(
            f"Coder job {clean(coder['job_id'], 40)}: {clean(coder.get('status', 'started'), 30)}, "
            f"engine {clean(coder.get('engine') or 'n/a', 30)}, {int(coder.get('iterations', 0) or 0)} "
            f"iteration(s), attempt {int(coder.get('attempts', 1) or 1)}."
        )
    revise = data.get("ci_revise")
    if isinstance(revise, dict) and revise.get("rounds"):
        steps.append(f"Fixed failing checks {int(revise['rounds'])} time(s) with the coder.")
    review = data.get("review")
    if isinstance(review, dict) and review.get("verdict"):
        steps.append(f"Reviewer verdict: {review['verdict']}.")
    failures = data.get("failures")
    if isinstance(failures, dict) and failures.get("count"):
        steps.append(f"{clean(failures.get('action', 'step'), 40)} failed {int(failures['count'])} time(s) in a row.")
    return steps


def escalation_block(
    data: dict[str, Any], *, label_only: str | None, evidence_url: str, at: str | None
) -> dict[str, Any] | None:
    esc = data.get("escalation") if isinstance(data.get("escalation"), dict) else None
    if esc is None and label_only is None:
        return None
    coder = data.get("coder") if isinstance(data.get("coder"), dict) else {}
    return {
        "label": clean((esc or {}).get("label") or label_only, 60),
        "reasons": [clean(r, 400) for r in (esc or {}).get("reasons", [])[:8]],
        "at": (esc or {}).get("at") or at,
        "attempts": int(coder.get("attempts", 0) or 0),
        "tried": tried(data),
        "evidence_url": evidence_url,
    }


def infer_scenario(type_: str, escalation: str | None, quality_rounds: int) -> str:
    """The demo scenario an object shows, when its issue body carried no marker (same rule as metrics.json)."""
    if type_ == "maintenance":
        return "d-maintenance"
    if type_ == "bug":
        return "d"
    if escalation == sdlc_state.ESC_NOT_SUITABLE:
        return "c"
    return "b" if quality_rounds > 0 else "a"


def commit_kind(message: str) -> str:
    head = message.split(":", 1)[0].split("(", 1)[0].strip().lower()
    return head if head in ("test", "feat", "fix", "chore", "docs", "refactor") else "other"


# ---------------------------------------------------------------------------
# The ticket
# ---------------------------------------------------------------------------


def summary_text(
    title: str,
    type_: str,
    stage: str,
    escalation: dict[str, Any] | None,
    release: dict[str, Any] | None,
    cost_usd: float,
) -> str:
    """Deterministic one-liner. A model summary, when present and valid, replaces it (summary.py)."""
    where = {
        "prod": "running in production",
        "staging": "merged and waiting for staging checks",
        "escalated": "stopped for a human",
        "backlog": "waiting to be picked up",
    }.get(stage, f"in {stage}")
    tail = f" Released as {release['tag']}." if release and release.get("tag") else ""
    if escalation:
        tail = f" Escalated: {escalation['label']}."
    return clean(f'{type_.capitalize()} "{title}" is {where}.{tail} Cost so far {cost_usd:.2f} USD.', 400)


def ticket(
    *,
    number: int,
    kind: str,
    title: str,
    author: str,
    opened_at: str,
    closed_at: str | None,
    labels: tuple[str, ...],
    state_data: dict[str, Any] | None,
    env: str = "none",
    hops: list[dict[str, Any]] | None = None,
    commits: list[dict[str, Any]] | None = None,
    pr_info: dict[str, Any] | None = None,
    comment_ids: dict[str, int] | None = None,
    ledger_usd: float = 0.0,
    gates_extra: dict[str, str] | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    """Build one ticket record. `state_data` is the parsed state comment (None before the first tick)."""
    data = state_data or {}
    path = "pull" if kind == "pr" else "issues"
    url = f"https://github.com/{REPO}/{path}/{number}"
    state_stages = [s for s in data.get("stages", []) if isinstance(s, dict) and "stage" in s]
    sdlc_stage = None
    for entry in reversed(state_stages):
        if str(entry["stage"]).startswith("stage:"):
            sdlc_stage = str(entry["stage"])
            break
    esc_label = None
    esc_data = data.get("escalation")
    if isinstance(esc_data, dict) and esc_data.get("label"):
        esc_label = str(esc_data["label"])
    else:
        esc_label = next((lbl for lbl in labels if lbl.startswith("escalated:")), None)
    stage = board_stage(sdlc_stage, esc_label, env, labels=labels)

    pr_state = data.get("pr") if isinstance(data.get("pr"), dict) else None
    pr_number = (pr_state or {}).get("number") or ((pr_info or {}).get("number"))
    if kind == "pr" and pr_number is None:
        pr_number = number
    pr_out = None
    if pr_number:
        pr_out = {
            "number": int(pr_number),
            "url": f"https://github.com/{REPO}/pull/{int(pr_number)}",
            "branch": clean((pr_state or {}).get("branch") or (pr_info or {}).get("branch") or "", 120) or None,
            "head": str((pr_state or {}).get("head") or (pr_info or {}).get("head") or "")[:40] or None,
            "merge_sha": str((pr_state or {}).get("merge_sha") or (pr_info or {}).get("merge_sha") or "")[:40] or None,
            "title": clean((pr_info or {}).get("title", ""), 200) or None,
        }
    release = data.get("release") if isinstance(data.get("release"), dict) else None
    release_out = None
    if release and release.get("tag"):
        release_out = {
            "tag": clean(release["tag"], 40),
            "url": f"https://github.com/{REPO}/releases/tag/{clean(release['tag'], 40)}",
        }

    cost = cost_block(data, ledger_usd=ledger_usd)
    gates = {k: clean(v, 20) for k, v in (data.get("gates") or {}).items() if isinstance(v, str)}
    for name, result in (gates_extra or {}).items():
        gates[name] = clean(result, 20)
    comment_ids = comment_ids or {}
    evidence_id = comment_ids.get("coder_log") or comment_ids.get("state")
    evidence_url = url + (f"#issuecomment-{evidence_id}" if evidence_id else "")
    last_stage_at = state_stages[-1]["at"] if state_stages else opened_at
    escalation = escalation_block(
        data,
        label_only=esc_label if is_escalation(esc_label) or DEPLOY_FAILED_LABEL in labels else None,
        evidence_url=evidence_url,
        at=last_stage_at,
    )
    if env == "rolled-back" and escalation is None:
        escalation = {
            "label": DEPLOY_FAILED_LABEL,
            "reasons": ["Release rolled back after a failed check"],
            "at": last_stage_at,
            "attempts": 0,
            "tried": tried(data),
            "evidence_url": evidence_url,
        }

    history = stage_history(opened_at, state_stages)
    coder = data.get("coder") if isinstance(data.get("coder"), dict) else None
    quality = data.get("quality") if isinstance(data.get("quality"), dict) else None
    triage = data.get("triage") if isinstance(data.get("triage"), dict) else None
    feas = data.get("feasibility") if isinstance(data.get("feasibility"), dict) else None
    updated_at = max(
        [
            now_
            for now_ in [
                opened_at,
                closed_at or opened_at,
                last_stage_at,
                *[h.get("finished_at") or h.get("at") for h in (hops or [])],
            ]
            if now_
        ]
    )
    out: dict[str, Any] = {
        "issue": number,
        "kind": kind,
        "title": clean(title, 200),
        "type": str(data.get("type") or ("maintenance" if kind == "pr" else "feature")),
        "scenario": data.get("scenario")
        or infer_scenario(
            str(data.get("type") or ("maintenance" if kind == "pr" else "feature")),
            esc_label,
            int((data.get("quality") or {}).get("rounds", 0) or 0),
        ),
        "author": clean(author, 60),
        "url": url,
        "opened_at": opened_at,
        "closed_at": closed_at,
        "updated_at": updated_at,
        "stage": stage,
        "sdlc_stage": sdlc_stage,
        "env": env,
        "escalation": escalation,
        "stage_history": history,
        "pr": pr_out,
        "commits": commits or [],
        "release": release_out,
        "hops": hops or [],
        "gates": gates,
        "gate_history": scrub(data.get("gate_history") or []),
        "cost": cost,
        "agent_runs": [
            {
                "agent": clean(c.get("agent", "unknown"), 60),
                "in": int(c.get("in", 0) or 0),
                "out": int(c.get("out", 0) or 0),
                "usd": round(float(c.get("usd", 0) or 0), 6),
            }
            for c in (data.get("cost") or {}).get("calls", [])
            if isinstance(c, dict)
        ],
        "coder": None
        if not coder
        else {
            "job_id": clean(coder.get("job_id", ""), 40) or None,
            "engine": clean(coder.get("engine") or "", 30) or None,
            "status": clean(coder.get("status", ""), 30) or None,
            "iterations": int(coder.get("iterations", 0) or 0),
            "attempts": int(coder.get("attempts", 0) or 0),
            "elapsed_s": int(coder.get("elapsed_s", 0) or 0),
            "started_at": coder.get("started_at"),
            "mode": clean(coder.get("mode", ""), 20) or None,
        },
        "qa": qa_trail(quality),
        "reviews": reviews_trail(data),
        "ci_triage": ci_triage_block(data),
        "quality": None
        if not quality
        else {
            "score": quality.get("score"),
            "rounds": int(quality.get("rounds", 0) or 0),
            "summary": clean(quality.get("summary", ""), 400) or None,
        },
        "triage": None
        if not triage
        else {
            "severity": triage.get("severity"),
            "owner": triage.get("owner"),
            "summary": clean(triage.get("summary", ""), 300) or None,
        },
        "feasibility": None
        if not feas
        else {
            "suitable": bool(feas.get("suitable")),
            "risk": clean(feas.get("risk", ""), 20) or None,
            "reasons": [clean(r, 300) for r in feas.get("reasons", [])[:6]],
        },
        "flags": [],
    }
    if env == "rolled-back":
        out["flags"].append("rolled-back")
    if DEPLOY_FAILED_LABEL in labels:
        out["flags"].append("deploy-failed")
    if cost["cap_used_pct"] > 100:
        out["flags"].append("over-cap")
    out["summary"] = (
        clean(summary, 400)
        if summary
        else summary_text(out["title"], out["type"], stage, escalation, release_out, cost["usd"])
    )
    out["digest"] = digest(out)
    return out


def digest(ticket_record: dict[str, Any]) -> str:
    """Fingerprint of what the ticket says, ignoring the summary and the digest itself, so a model summary
    is kept only while the facts it describes are unchanged."""
    body = {k: v for k, v in ticket_record.items() if k not in ("summary", "digest")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]
