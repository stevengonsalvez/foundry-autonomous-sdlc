"""
The one-per-object state comment (docs/architecture.md, "State comment").

Format: a bot comment whose body starts with `<!-- sdlc-state:v1`, a newline, the JSON state,
a newline and `-->`, followed by a human readable summary. The JSON is the source of truth for the
object's stage; labels are a projection of it that the orchestrator keeps in sync.

Versioning: v1 states are parsed and validated (unknown keys are preserved, so a newer v1 writer
loses nothing when an older reader saves). A higher version is refused, never overwritten.
Only comments authored by the repo owner (the identity the orchestrator writes with) count, so a
stranger cannot forge state on a public issue. Stdlib only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sdlc_agents import schema_check
from sdlc_agents.ports import OWNER, Comment
from sdlc_agents.sanitise import encode_marker_json, one_line, parse_json_strict, sanitise_markdown

VERSION = 1
MARKER_PREFIX = "<!-- sdlc-state:v"
_STATE_RE = re.compile(r"\A<!-- sdlc-state:v(\d+)\n(.*?)\n-->", re.DOTALL)

# Stage and escalation labels (docs/architecture.md, "Label set").
NEEDS_REFINEMENT = "stage:needs-refinement"
READY = "stage:ready"
FEASIBLE = "stage:feasible"
TESTS_WRITTEN = "stage:tests-written"
BUILDING = "stage:building"
IN_REVIEW = "stage:in-review"
MERGED = "stage:merged"
RELEASED = "stage:released"
STAGES = (NEEDS_REFINEMENT, READY, FEASIBLE, TESTS_WRITTEN, BUILDING, IN_REVIEW, MERGED, RELEASED)

ESC_NOT_SUITABLE = "escalated:not-agent-suitable"
ESC_REQUIREMENTS = "escalated:requirements"
ESC_REVIEW_FAILED = "escalated:review-failed"
ESC_COST_CAP = "escalated:cost-cap"
ESC_BUILD_FAILED = "escalated:build-failed"
ESC_AGENT_ERROR = "escalated:agent-error"   # a prompt agent kept answering invalidly or refusing
ESCALATIONS = (ESC_NOT_SUITABLE, ESC_REQUIREMENTS, ESC_REVIEW_FAILED, ESC_COST_CAP, ESC_BUILD_FAILED,
               ESC_AGENT_ERROR)

TYPES = ("feature", "bug", "maintenance")
SCENARIOS = ("a", "b", "c", "d", "d-maintenance")

_NULLABLE_OBJECT = {"type": ["object", "null"]}
_COUNT = {"type": "integer", "minimum": 0}

STATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "version": {"type": "integer", "minimum": 1, "maximum": VERSION},
        "issue": {"type": "integer", "minimum": 1},
        "type": {"type": "string", "enum": list(TYPES)},
        "scenario": {"type": ["string", "null"], "enum": [*SCENARIOS, None]},
        "stages": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "stage": {"type": "string", "enum": [*STAGES, *ESCALATIONS]},
                "at": {"type": "string", "minLength": 20},
            },
            "required": ["stage", "at"],
        }},
        "quality": {
            "type": ["object", "null"],
            "properties": {
                "score": {"type": ["integer", "null"], "minimum": 0, "maximum": 100},
                "rounds": _COUNT,
                "questions": {"type": "array", "items": {"type": "string"}},
                "answers": {"type": "array", "items": {"type": "string"}},
            },
        },
        "feasibility": {
            "type": ["object", "null"],
            "properties": {"suitable": {"type": "boolean"}, "reasons": {"type": "array"}},
        },
        "triage": {
            "type": ["object", "null"],
            "properties": {
                "severity": {"type": "string", "enum": ["s1", "s2", "s3", "s4"]},
                "owner": {"type": "string", "enum": ["web", "api", "carrier-mock"]},
            },
        },
        "coder": {
            "type": ["object", "null"],
            "properties": {"attempts": _COUNT, "iterations": _COUNT},
        },
        "pr": {
            "type": ["object", "null"],
            "properties": {"number": {"type": "integer", "minimum": 1}, "head": {"type": ["string", "null"]}},
        },
        "review": {
            "type": ["object", "null"],
            "properties": {
                "verdict": {"type": "string", "enum": ["approve", "request-changes"]},
                "head": {"type": "string"},
                "rounds": _COUNT,
            },
        },
        "ci_triage": _NULLABLE_OBJECT,
        "gates": {"type": "object"},
        "gate_history": {"type": "array"},
        "release": _NULLABLE_OBJECT,
        "escalation": {
            "type": ["object", "null"],
            "properties": {"label": {"type": "string", "enum": list(ESCALATIONS)}, "reasons": {"type": "array"}},
        },
        "failures": {
            "type": ["object", "null"],
            "properties": {"action": {"type": "string"}, "count": _COUNT, "error": {"type": "string"}},
        },
        "cost": {
            "type": "object",
            "properties": {
                "usd": {"type": "number", "minimum": 0},
                "calls": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "agent": {"type": "string"}, "in": _COUNT, "out": _COUNT,
                        "usd": {"type": "number", "minimum": 0},
                    },
                    "required": ["agent", "in", "out", "usd"],
                }},
                "coder_seconds": _COUNT,
                "coder_usd": {"type": "number", "minimum": 0},
            },
            "required": ["usd", "calls", "coder_seconds", "coder_usd"],
        },
    },
    "required": ["version", "issue", "type", "stages", "cost"],
}


class StateVersionError(ValueError):
    """The comment was written by a newer orchestrator; this one must not touch it."""


@dataclass
class State:
    """A validated state document. `data` is the JSON object; helpers keep the common edits in one place."""

    data: dict[str, Any]

    @classmethod
    def new(cls, number: int, type_: str, scenario: str | None) -> State:
        state = cls({
            "version": VERSION, "issue": number, "type": type_, "scenario": scenario, "stages": [],
            "quality": None, "feasibility": None, "triage": None, "coder": None, "pr": None,
            "review": None, "ci_triage": None, "gates": {}, "gate_history": [], "release": None,
            "escalation": None, "failures": None,
            "cost": {"usd": 0.0, "calls": [], "coder_seconds": 0, "coder_usd": 0.0},
        })
        state.validate()
        return state

    # -- reading ------------------------------------------------------------

    def validate(self) -> None:
        schema_check.check(STATE_SCHEMA, self.data, "state")

    @property
    def number(self) -> int:
        return int(self.data["issue"])

    @property
    def type(self) -> str:
        return str(self.data["type"])

    @property
    def stage(self) -> str | None:
        """The latest stage:* entry (escalations are recorded in the history but are not stages)."""
        for entry in reversed(self.data["stages"]):
            if entry["stage"].startswith("stage:"):
                return str(entry["stage"])
        return None

    @property
    def escalation(self) -> str | None:
        esc = self.data.get("escalation")
        return str(esc["label"]) if esc else None

    @property
    def usd(self) -> float:
        return float(self.data["cost"]["usd"])

    def section(self, name: str) -> dict[str, Any]:
        """The named object section, created empty if absent."""
        if not isinstance(self.data.get(name), dict):
            self.data[name] = {}
        return self.data[name]

    def get(self, name: str) -> dict[str, Any] | None:
        value = self.data.get(name)
        return value if isinstance(value, dict) else None

    # -- writing ------------------------------------------------------------

    def enter(self, stage: str, at: str) -> None:
        """Record a stage transition (no-op if already in that stage) and clear the failure counter."""
        if self.stage != stage:
            self.data["stages"].append({"stage": stage, "at": at})
        self.data["failures"] = None

    def escalate(self, label: str, reasons: list[str], at: str) -> None:
        self.data["escalation"] = {"label": label, "reasons": reasons, "at": at}
        self.data["stages"].append({"stage": label, "at": at})
        self.data["failures"] = None

    def record_failure(self, action: str, error: str) -> int:
        current = self.data.get("failures") or {}
        count = int(current.get("count", 0)) + 1 if current.get("action") == action else 1
        self.data["failures"] = {"action": action, "count": count, "error": one_line(error, 300)}
        return count


# ---------------------------------------------------------------------------
# Parse and render
# ---------------------------------------------------------------------------

def parse(body: str) -> State | None:
    """Return the State in a comment body, None if the body is not a state comment.

    Raises StateVersionError for a newer version and ValueError for a corrupt v1 document.
    """
    if not body.startswith(MARKER_PREFIX):
        return None
    match = _STATE_RE.match(body)
    if not match:
        raise ValueError("state comment marker present but malformed")
    version = int(match.group(1))
    if version > VERSION:
        raise StateVersionError(f"state comment is v{version}; this orchestrator understands v{VERSION}")
    data = parse_json_strict(match.group(2))
    if not isinstance(data, dict):
        raise ValueError("state comment JSON is not an object")
    state = State(data)
    state.validate()
    return state


def find(comments: list[Comment]) -> tuple[Comment | None, State | None]:
    """The first owner-authored state comment and its parsed state (others are ignored)."""
    for comment in comments:
        if comment.author == OWNER and comment.body.startswith(MARKER_PREFIX):
            return comment, parse(comment.body)
    return None, None


def render(state: State) -> str:
    state.validate()
    return f"<!-- sdlc-state:v{VERSION}\n{encode_marker_json(state.data)}\n-->\n{summary(state)}"


def summary(state: State) -> str:
    """Human readable digest. Model text is reduced to one sanitised line."""
    d = state.data
    current = state.escalation or state.stage or "new"
    lines = [
        f"**SDLC state** for #{state.number}: `{current}` ({state.type}"
        + (f", scenario {d['scenario']})" if d.get("scenario") else ")"),
        "",
        "| item | value |",
        "|------|-------|",
    ]

    def row(name: str, value: str) -> None:
        lines.append(f"| {name} | {value} |")

    if quality := state.get("quality"):
        row("requirement quality", f"{quality.get('score')} / 100 after {quality.get('rounds', 0)} refinement round(s)")
    if triage := state.get("triage"):
        row("triage", f"severity `{triage['severity']}`, owner `{triage['owner']}`")
    if feas := state.get("feasibility"):
        verdict = "suitable" if feas.get("suitable") else "not suitable"
        reasons = "; ".join(_safe(r, 120) for r in feas.get("reasons", [])[:3])
        row("feasibility", f"{verdict}: {reasons}")
    if coder := state.get("coder"):
        row("coder", f"job `{coder.get('job_id')}`, {coder.get('status', 'started')}, "
                     f"engine {coder.get('engine') or 'n/a'}, iterations {coder.get('iterations', 0)}")
    if pr := state.get("pr"):
        row("pull request", f"#{pr['number']} at `{str(pr.get('head') or '')[:7]}`")
    if review := state.get("review"):
        row("review", f"{review['verdict']} for `{review['head'][:7]}` (round {review.get('rounds', 0)})")
    if d.get("gates"):
        row("gates", ", ".join(f"{k}: {v}" for k, v in sorted(d["gates"].items())))
    if release := state.get("release"):
        row("release", f"`{release.get('tag')}`")
    if esc := state.get("escalation"):
        row("escalation", f"`{esc['label']}`: " + "; ".join(_safe(r, 160) for r in esc.get("reasons", [])[:5]))
    cost = d["cost"]
    row("cost", f"{cost['usd']:.4f} USD ({len(cost['calls'])} model calls, coder {cost['coder_seconds']} s)")
    lines += ["", "Stages: " + " → ".join(f"`{s['stage']}`" for s in d["stages"]) if d["stages"] else ""]
    return "\n".join(lines).rstrip() + "\n"


def _safe(text: Any, limit: int) -> str:
    return sanitise_markdown(one_line(str(text), limit)).replace("|", "\\|")
