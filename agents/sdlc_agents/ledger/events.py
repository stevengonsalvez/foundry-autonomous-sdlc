"""
Ledger events: the append-only record the state-keeper keeps in `events.jsonl` on branch `state`.

One line per event, schema version 1:

    {"v": 1, "id": "<16 hex>", "at": "<ISO UTC>", "type": "...", "issue": 12 | null, "source": "...", "data": {...}}

The id is a digest of the content, so sending the same event twice (a retried invocation, a
reconcile that sees what the orchestrator already reported) is recognised and dropped.

Types:
    ticket.updated    data.ticket   the full ticket record (ledger/model.py) after a stage or fact change
    env.changed       data.deploy   the deploy.json snapshot written by the CD workflow (branch `deploy`)
    tick.finished     data          one orchestrator tick: lock, per-object results, errors, spend
    billing.observed  data          what Azure Cost Management says was billed for the resource group
    metrics.observed  data          the orchestrator's own spend estimate (totals of metrics.json)
    ledger.invoked    data          the ledger's own compute for one invocation (counts toward the caps)

Events come from the orchestrator over the Invocations protocol (Entra authenticated) or are built
by the ledger itself from GitHub. Either way they are validated here and every string in them is
cleaned before it is stored. Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sdlc_agents import schema_check
from sdlc_agents.ledger import model

VERSION = 1
TYPES = (
    "ticket.updated",
    "env.changed",
    "tick.finished",
    "billing.observed",
    "metrics.observed",
    "summary.written",
    "summary.failed",
    "ledger.invoked",
)
SOURCES = ("orchestrator", "reconcile", "cd", "ledger", "operator")
MAX_EVENT_BYTES = 96_000
MAX_BATCH = 500

_TIME = {"type": "string", "minLength": 20, "maxLength": 40}

TICKET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "issue": {"type": "integer", "minimum": 1},
        "kind": {"type": "string", "enum": ["issue", "pr"]},
        "title": {"type": "string", "maxLength": 400},
        "type": {"type": "string", "enum": ["feature", "bug", "maintenance"]},
        "opened_at": _TIME,
        "stage": {"type": "string", "enum": list(model.BOARD_STAGES)},
        "env": {"type": "string", "enum": list(model.ENVS)},
        "stage_history": {
            "type": "array",
            "maxItems": 200,
            "items": {
                "type": "object",
                "properties": {"stage": {"type": "string", "enum": list(model.BOARD_STAGES)}, "at": _TIME},
                "required": ["stage", "at"],
            },
        },
        "cost": {
            "type": "object",
            "properties": {"usd": {"type": "number", "minimum": 0}, "cap_used_pct": {"type": "number", "minimum": 0}},
            "required": ["usd", "cap_used_pct"],
        },
        "gates": {"type": "object"},
        "qa": {"type": "array", "maxItems": 100},
        "hops": {"type": "array", "maxItems": 100},
    },
    "required": ["issue", "kind", "title", "type", "opened_at", "stage", "env", "stage_history", "cost", "gates"],
}

ENVELOPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "v": {"type": "integer", "enum": [VERSION]},
        "id": {"type": "string", "pattern": "^[0-9a-f]{16}$"},
        "at": _TIME,
        "type": {"type": "string", "enum": list(TYPES)},
        "issue": {"type": ["integer", "null"], "minimum": 1},
        "source": {"type": "string", "enum": list(SOURCES)},
        "data": {"type": "object"},
    },
    "required": ["v", "id", "at", "type", "issue", "source", "data"],
}


class EventError(ValueError):
    """An event is malformed or too large; it is rejected, never partly stored."""


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def event_id(type_: str, at: str, issue: int | None, data: dict[str, Any]) -> str:
    return hashlib.sha256(canonical([type_, at, issue, data]).encode()).hexdigest()[:16]


def make(
    type_: str, at: str, data: dict[str, Any], *, issue: int | None = None, source: str = "orchestrator"
) -> dict[str, Any]:
    """Build a valid event. Strings in `data` are cleaned (control characters, token shapes, length)."""
    cleaned = model.scrub(data, limit=4000)
    event = {
        "v": VERSION,
        "id": event_id(type_, at, issue, cleaned),
        "at": at,
        "type": type_,
        "issue": issue,
        "source": source,
        "data": cleaned,
    }
    validate(event)
    return event


def validate(event: Any) -> None:
    """Raise EventError unless `event` is a well-formed v1 event whose payload matches its type."""
    try:
        schema_check.check(ENVELOPE_SCHEMA, event, "event")
        if len(canonical(event)) > MAX_EVENT_BYTES:
            raise ValueError(f"event is larger than {MAX_EVENT_BYTES} bytes")
        data = event["data"]
        if event["type"] == "ticket.updated":
            ticket = data.get("ticket")
            schema_check.check(TICKET_SCHEMA, ticket, "event.data.ticket")
            if event["issue"] != ticket["issue"]:
                raise ValueError("event.issue does not match event.data.ticket.issue")
        elif event["type"] == "env.changed":
            schema_check.check({"type": "object", "required": ["deploy"]}, data, "event.data")
            schema_check.check(
                {
                    "type": "object",
                    "properties": {"version": {"type": "integer", "enum": [1]}},
                    "required": ["version"],
                },
                data["deploy"],
                "event.data.deploy",
            )
        elif event["type"] == "tick.finished":
            schema_check.check(
                {
                    "type": "object",
                    "required": ["started_at", "finished_at", "objects"],
                    "properties": {
                        "objects": {"type": "array", "maxItems": 500},
                        "errors": {"type": "array", "maxItems": 100},
                    },
                },
                data,
                "event.data",
            )
        elif event["type"] == "billing.observed":
            schema_check.check(
                {
                    "type": "object",
                    "required": ["billed_usd", "as_of", "source"],
                    "properties": {"billed_usd": {"type": "number", "minimum": 0}},
                },
                data,
                "event.data",
            )
        elif event["type"] == "metrics.observed":
            schema_check.check(
                {"type": "object", "required": ["usd"], "properties": {"usd": {"type": "number", "minimum": 0}}},
                data,
                "event.data",
            )
        elif event["type"] in ("summary.written", "summary.failed"):
            schema_check.check(
                {
                    "type": "object",
                    "required": ["digest"],
                    "properties": {
                        "digest": {"type": "string", "maxLength": 40},
                        "text": {"type": "string", "maxLength": 400},
                    },
                },
                data,
                "event.data",
            )
            if event["issue"] is None:
                raise ValueError("a summary event needs an issue")
        elif event["type"] == "ledger.invoked":
            schema_check.check(
                {
                    "type": "object",
                    "required": ["usd", "seconds"],
                    "properties": {
                        "usd": {"type": "number", "minimum": 0},
                        "seconds": {"type": "number", "minimum": 0},
                    },
                },
                data,
                "event.data",
            )
    except (ValueError, TypeError, KeyError) as exc:
        raise EventError(str(exc)) from exc


def validate_batch(events: Any) -> list[dict[str, Any]]:
    if not isinstance(events, list):
        raise EventError("events must be a list")
    if len(events) > MAX_BATCH:
        raise EventError(f"at most {MAX_BATCH} events per call")
    for ev in events:
        validate(ev)
        # Re-clean on the way in: the sender is trusted to authenticate, not to have cleaned.
        ev["data"] = model.scrub(ev["data"], limit=4000)
    return events


def dumps_line(event: dict[str, Any]) -> str:
    return canonical(event)


def loads_lines(text: str) -> list[dict[str, Any]]:
    events = []
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
            validate(ev)
        except (ValueError, EventError) as exc:
            raise EventError(f"events.jsonl line {n}: {exc}") from exc
        events.append(ev)
    return events
