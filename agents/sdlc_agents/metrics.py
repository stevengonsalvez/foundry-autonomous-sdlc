"""
metrics.json for the dashboard (docs/architecture.md, "Metrics"), built from issues and their state.

Schema version 1, validated on every build. Beyond the documented fields it adds:
- `totals.escalated` and `totals.orchestrator_usd` (the orchestrator's own compute, part of usd);
- per object `kind` (issue | pr) and `gate_attempts` (each gate's conclusion per evaluated head
  sha, oldest first, so first-attempt and eventual results are both visible), and
  `cost.coder_model_usd`;
- per gate in `gate_pass_rates`, `first_pass`/`first_fail` next to the run counts `pass`/`fail`.
The maintenance PR is its own entry: kind pr, number null, pr set, scenario d-maintenance.
The file lives on branch `metrics` and is rewritten when anything but `generated_at` changed.

A single-object tick (run_tick(only=N)) loads one object, so it merges instead of rebuilding: its
fresh entry replaces that object's published entry, every other published entry is kept as it was,
and the published gate counts move by the difference the step made to that object's gate history.
A full tick rebuilds the whole document from every object it loads.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sdlc_agents import cost, gates, schema_check, state
from sdlc_agents.clock import parse_iso, seconds_between
from sdlc_agents.ports import REPO, GitHubPort, Issue
from sdlc_agents.state import State

METRICS_BRANCH = "metrics"
METRICS_PATH = "metrics.json"

_TIME = {"type": "string", "minLength": 20}
_OPT_TIME = {"type": ["string", "null"]}
_COUNT = {"type": "integer", "minimum": 0}
_USD = {"type": "number", "minimum": 0}

METRICS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "version": {"type": "integer", "enum": [1]},
        "generated_at": _TIME,
        "repo": {"type": "string", "enum": [REPO]},
        "totals": {
            "type": "object",
            "properties": {"usd": _USD, "issues": _COUNT, "released": _COUNT, "escalated": _COUNT,
                           "orchestrator_usd": _USD, "ledger_usd": _USD, "deferred": _COUNT},
            "required": ["usd", "issues", "released"],
        },
        "issues": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "number": {"type": ["integer", "null"], "minimum": 1},
                "kind": {"type": "string", "enum": ["issue", "pr"]},
                "title": {"type": "string"},
                "scenario": {"type": ["string", "null"], "enum": [*state.SCENARIOS, None]},
                "type": {"type": "string", "enum": list(state.TYPES)},
                "outcome": {"type": "string", "enum": ["released", "escalated", "open"]},
                "escalation": {"type": ["string", "null"]},
                "opened_at": _TIME,
                "closed_at": _OPT_TIME,
                "stages": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"stage": {"type": "string"}, "entered_at": _TIME, "seconds": _COUNT},
                    "required": ["stage", "entered_at", "seconds"],
                }},
                "severity": {"type": ["string", "null"]},
                "owner": {"type": ["string", "null"]},
                "resolution_seconds": {"type": ["integer", "null"], "minimum": 0},
                "pr": {"type": ["integer", "null"]},
                "release": {"type": ["string", "null"]},
                "quality_score": {"type": ["integer", "null"]},
                "coder_engine": {"type": ["string", "null"]},
                "cost": {
                    "type": "object",
                    "properties": {"usd": _USD, "model_usd": _USD, "coder_usd": _USD, "coder_model_usd": _USD,
                                   "calls": _COUNT},
                    "required": ["usd", "model_usd", "coder_usd", "calls"],
                },
                "gates": {"type": "object"},
                "gate_attempts": {"type": "object"},
                "deferred": {"type": ["string", "null"]},
                "coder_sessions_lost": _COUNT,
            },
            "required": [
                "number", "title", "scenario", "type", "outcome", "opened_at", "closed_at", "stages",
                "severity", "owner", "resolution_seconds", "pr", "release", "quality_score",
                "coder_engine", "cost", "gates",
            ],
        }},
        "gate_pass_rates": {"type": "object"},
        "deferrals": {"type": "object"},
        "ledger": {"type": "object"},
    },
    "required": ["version", "generated_at", "repo", "totals", "issues", "gate_pass_rates"],
}


def infer_scenario(st: State) -> str:
    """The scenario an object demonstrates, when its issue body did not say."""
    if st.type == "maintenance":
        return "d-maintenance"
    if st.type == "bug":
        return "d"
    if st.escalation == state.ESC_NOT_SUITABLE:
        return "c"
    if (st.get("quality") or {}).get("rounds", 0) > 0:
        return "b"
    return "a"


def _stages(st: State) -> list[dict[str, Any]]:
    """Seconds spent in each finished stage. The current stage reports 0 and in_progress, so the
    file only changes when something happens (the dashboard measures open stages itself)."""
    entries = st.data["stages"]
    result = []
    for i, entry in enumerate(entries):
        row = {"stage": entry["stage"], "entered_at": entry["at"], "seconds": 0}
        if i + 1 < len(entries):
            row["seconds"] = max(seconds_between(entry["at"], entries[i + 1]["at"]), 0)
        elif not (entry["stage"] == state.RELEASED or entry["stage"].startswith("escalated:")):
            row["in_progress"] = True
        result.append(row)
    return result


def _issue_entry(item: Issue, st: State) -> dict[str, Any]:
    released_at = next((s["at"] for s in st.data["stages"] if s["stage"] == state.RELEASED), None)
    triage = st.get("triage") or {}
    rel = st.get("release") or {}
    pr = st.get("pr") or {}
    if st.stage == state.RELEASED:
        outcome = "released"
    elif st.escalation:
        outcome = "escalated"
    else:
        outcome = "open"
    return {
        "number": None if item.is_pull_request else item.number,
        "kind": "pr" if item.is_pull_request else "issue",
        "title": item.title,
        "scenario": st.data.get("scenario") or infer_scenario(st),
        "type": st.type,
        "outcome": outcome,
        "escalation": st.escalation,
        "opened_at": item.created_at,
        "closed_at": item.closed_at,
        "stages": _stages(st),
        "severity": triage.get("severity"),
        "owner": triage.get("owner"),
        "resolution_seconds": max(seconds_between(item.created_at, released_at), 0) if released_at else None,
        "pr": item.number if item.is_pull_request else pr.get("number"),
        "release": None if rel.get("pending") else rel.get("tag"),
        "quality_score": (st.get("quality") or {}).get("score"),
        "coder_engine": (st.get("coder") or {}).get("engine"),
        "cost": {"usd": round(st.usd, 6), "model_usd": cost.model_usd(st),
                 "coder_usd": round(float(st.data["cost"]["coder_usd"]), 6),
                 "coder_model_usd": round(float(st.data["cost"].get("coder_model_usd", 0.0)), 6),
                 "calls": cost.call_count(st)},
        "gates": dict(st.data.get("gates") or {}),
        "gate_attempts": _gate_attempts(st),
        "coder_sessions_lost": int(st.data.get("coder_sessions_lost", 0)),
    }


def _attempts(st: State) -> list[dict[str, str]]:
    return [h["results"] for h in st.data.get("gate_history") or [] if isinstance(h.get("results"), dict)]


def _gate_attempts(st: State) -> dict[str, list[str]]:
    """Each gate's conclusion on every evaluated head, oldest first (pending and missing left out)."""
    result: dict[str, list[str]] = {}
    for attempt in _attempts(st):
        for name, conclusion in attempt.items():
            if name in gates.REQUIRED_CHECKS and conclusion not in (gates.PENDING, gates.MISSING):
                result.setdefault(name, []).append(conclusion)
    return result


def _gate_pass_rates(states: list[State]) -> dict[str, dict[str, int]]:
    rates = {name: {"pass": 0, "fail": 0, "first_pass": 0, "first_fail": 0} for name in gates.REQUIRED_CHECKS}
    for st in states:
        for position, attempt in enumerate(_attempts(st)):
            for name, result in attempt.items():
                if name not in rates or result in (gates.PENDING, gates.MISSING):
                    continue
                outcome = "pass" if result == gates.SUCCESS else "fail"
                rates[name][outcome] += 1
                if position == 0:
                    rates[name][f"first_{outcome}"] += 1
    return rates


def _key(entry: dict[str, Any]) -> int:
    """The issue or PR number an entry belongs to (a maintenance PR entry has number null)."""
    return int(entry["pr"] if entry.get("kind") == "pr" else entry["number"])


def _shifted(published: dict[str, dict[str, int]], before: dict[str, dict[str, int]],
             after: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """Published gate counts with the stepped objects' old contribution swapped for their new one.
    Clamped at zero so a published file that lags the state comments never goes negative."""
    return {name: {k: max(published.get(name, {}).get(k, 0) - before[name][k], 0) + after[name][k]
                   for k in after[name]}
            for name in after}


def build(objects: list[tuple[Issue, State]], now: str, *, orchestrator_usd: float = 0.0,
          floor_usd: float = 0.0, deferred: dict[int, str] | None = None,
          deferrals: dict[int, int] | None = None, ledger_usd: float = 0.0,
          ledger_marks: dict[str, str | None] | None = None,
          merge_into: Ledger | None = None, before: Sequence[State] = ()) -> dict[str, Any]:
    """The metrics document. `orchestrator_usd` is the cumulative orchestrator compute and `ledger_usd`
    the cumulative compute of the state-keeper agent (both inside totals.usd); `floor_usd` keeps
    totals.usd monotonic when objects drop out of view. `ledger_marks` records when the ledger was last
    sent events and last reconciled, so a stateless tick knows when a heartbeat or reconcile is due.

    `merge_into` (a single-object tick): keep its published entries for every object not in `objects`
    and shift its gate counts by `objects`' states now against `before`, their states as loaded."""
    deferred = deferred or {}
    entries = [{**_issue_entry(item, st), "deferred": deferred.get(item.number)}
               for item, st in sorted(objects, key=lambda p: p[0].number)]
    rates = _gate_pass_rates([st for _, st in objects])
    if merge_into is not None:
        stepped = {_key(e) for e in entries}
        # A published entry that no longer validates is dropped, not kept: it would stop every publish.
        kept = [e for e in merge_into.issues if _key(e) not in stepped and _valid(e)]
        entries = sorted([*kept, *entries], key=_key)
        rates = _shifted(merge_into.gate_pass_rates, _gate_pass_rates(list(before)), rates)
    objects_usd = sum(e["cost"]["usd"] for e in entries)
    doc = {
        "version": 1,
        "generated_at": now,
        "repo": REPO,
        "totals": {
            "usd": round(max(objects_usd + orchestrator_usd + ledger_usd, floor_usd), 6),
            "orchestrator_usd": round(orchestrator_usd, 6),
            "ledger_usd": round(ledger_usd, 6),
            "deferred": sum(e["deferred"] is not None for e in entries),
            "issues": len(entries),
            "released": sum(e["outcome"] == "released" for e in entries),
            "escalated": sum(e["outcome"] == "escalated" for e in entries),
        },
        "issues": entries,
        "gate_pass_rates": rates,
        # Consecutive deferred ticks per object: the tick reads them back to bound transient retries.
        "deferrals": {str(k): v for k, v in sorted((deferrals or {}).items())},
        "ledger": {"emitted_at": (ledger_marks or {}).get("emitted_at"),
                   "reconciled_at": (ledger_marks or {}).get("reconciled_at")},
    }
    schema_check.check(METRICS_SCHEMA, doc, "metrics")
    return doc


@dataclass(frozen=True)
class Ledger:
    """Spend as last published: the floor under this tick's figures, so lost state never lowers them."""

    usd: float = 0.0
    orchestrator_usd: float = 0.0
    objects: dict[int, float] = field(default_factory=dict)   # issue or PR number -> usd
    deferrals: dict[int, int] = field(default_factory=dict)   # number -> consecutive deferred ticks
    ledger_usd: float = 0.0
    ledger_emitted_at: str | None = None
    ledger_reconciled_at: str | None = None
    issues: tuple[dict[str, Any], ...] = ()                    # the published entries, for a merge
    gate_pass_rates: dict[str, dict[str, int]] = field(default_factory=dict)


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ValueError(f"not a spend figure: {value!r}")
    return float(value)


def _rates(value: Any) -> dict[str, dict[str, int]]:
    """Published gate counts for a merge. Display data, not spend: what is not a count reads as zero
    rather than making the ledger unreadable (which would halt spending)."""
    rates: dict[str, dict[str, int]] = {}
    for name, counts in (value.items() if isinstance(value, dict) else ()):
        if isinstance(counts, dict):
            rates[str(name)] = {str(k): v for k, v in counts.items()
                                if isinstance(v, int) and not isinstance(v, bool) and v >= 0}
    return rates


def _valid(entry: dict[str, Any]) -> bool:
    try:
        schema_check.check(METRICS_SCHEMA["properties"]["issues"]["items"], entry, "metrics entry")
    except ValueError:
        return False
    return True


def _mark(value: Any) -> str | None:
    """A timestamp mark as written by the orchestrator, or None when it is not one (a hand edit must not
    stop the tick that reads it)."""
    try:
        if isinstance(value, str):
            parse_iso(value)
            return value
    except ValueError:
        pass
    return None


def previous_totals(github: GitHubPort) -> Ledger | None:
    """The published ledger; an empty one when nothing was published yet; None when the file exists
    but cannot be read as a ledger (the caller must then fail closed)."""
    current = github.get_file(METRICS_PATH, ref=METRICS_BRANCH) if github.get_branch_sha(METRICS_BRANCH) else None
    if current is None:
        return Ledger()
    try:
        doc = json.loads(current)
        totals = doc["totals"]
        objects = {}
        entries = tuple(doc.get("issues") or [])
        for entry in entries:
            objects[_key(entry)] = _number(entry["cost"]["usd"])
        deferrals = {int(k): int(v) for k, v in (doc.get("deferrals") or {}).items()}
        raw_marks = doc.get("ledger") if isinstance(doc.get("ledger"), dict) else {}
        marks = {k: _mark(v) for k, v in raw_marks.items()}
        return Ledger(_number(totals["usd"]), _number(totals.get("orchestrator_usd", 0.0)), objects, deferrals,
                      _number(totals.get("ledger_usd", 0.0)), marks.get("emitted_at"), marks.get("reconciled_at"),
                      entries, _rates(doc.get("gate_pass_rates")))
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


UNCHANGED, TOTALS, CHANGED = "unchanged", "totals", "changed"


def _without(doc: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in keys}


def publish(github: GitHubPort, doc: dict[str, Any]) -> str:
    """Write metrics.json to the metrics branch unless only generated_at differs.

    Returns UNCHANGED, TOTALS (only the totals moved, e.g. orchestrator spend) or CHANGED.
    """
    if github.get_branch_sha(METRICS_BRANCH) is None:
        base = github.get_branch_sha("main")
        if base is None:
            raise RuntimeError("branch main not found")
        github.create_branch(METRICS_BRANCH, from_sha=base)
    current = github.get_file(METRICS_PATH, ref=METRICS_BRANCH)
    kind = CHANGED
    if current is not None:
        try:
            old = json.loads(current)
        except ValueError:
            old = None
        if isinstance(old, dict):
            if _without(old, "generated_at") == _without(doc, "generated_at"):
                return UNCHANGED
            if _without(old, "generated_at", "totals", "ledger") == _without(doc, "generated_at", "totals", "ledger"):
                kind = TOTALS
    github.put_file(METRICS_PATH, json.dumps(doc, indent=2, sort_keys=True) + "\n",
                    branch=METRICS_BRANCH, message="chore(metrics): update metrics.json")
    return kind
