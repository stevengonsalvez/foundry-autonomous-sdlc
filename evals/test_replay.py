"""Hermetic offline requirement-gate replay evaluation suite.

Replays recorded model outputs deterministically through foundry._parse,
_check_req_gate, and machine.after_score against golden expectations.
"""

from __future__ import annotations

import hashlib
import json
import os
from enum import StrEnum
from pathlib import Path

import pytest
from sdlc_agents import foundry, machine
from sdlc_agents.definitions import _check_req_gate
from sdlc_agents.foundry import AGENT_BY_NAME
from sdlc_agents.machine import ESC_REQUIREMENTS, NEEDS_REFINEMENT, READY


class GateOutcome(StrEnum):
    READY = "READY"
    NEEDS_REFINEMENT = "NEEDS_REFINEMENT"
    ESCALATE = "escalate"


ALLOWED_OUTCOMES = {o.value for o in GateOutcome}


def resolve_outcome(score: int, rounds: int) -> str:
    """Map machine.after_score outcome to evaluation gate outcome label."""
    outcome = machine.after_score(score, rounds)
    if outcome.stage == READY:
        return GateOutcome.READY.value
    if outcome.stage == NEEDS_REFINEMENT:
        return GateOutcome.NEEDS_REFINEMENT.value
    if outcome.escalate == ESC_REQUIREMENTS:
        return GateOutcome.ESCALATE.value
    raise ValueError(f"Unrecognized machine outcome: {outcome}")


def _trusted_file(name: str) -> Path:
    """Resolve trusted file path from EVALS_TRUSTED_DIR or default evals/datasets."""
    trusted_env = os.environ.get("EVALS_TRUSTED_DIR")
    if trusted_env is not None:
        trusted_dir = Path(trusted_env)
        if not trusted_dir.exists():
            raise FileNotFoundError(f"EVALS_TRUSTED_DIR {trusted_dir} does not exist")
        target = trusted_dir / "datasets" / name
    else:
        target = Path("evals/datasets") / name

    if not target.exists():
        raise FileNotFoundError(f"Dataset file not found: {target}")
    return target


def get_golden_path() -> Path:
    """Resolve golden dataset path with strict trust model."""
    return _trusted_file("req_gate_golden.jsonl")


def get_snapshot_path() -> Path:
    """Resolve state snapshot path with strict trust model."""
    return _trusted_file("state_snapshot.jsonl")


def get_issues_snapshot_path() -> Path:
    """Resolve issues snapshot path with strict trust model."""
    return _trusted_file("issues_snapshot.jsonl")


def get_recordings_dir() -> Path:
    """Resolve recordings directory from PR checkout under test."""
    recordings_dir = Path("evals/recordings/req_gate")
    if not recordings_dir.exists():
        raise FileNotFoundError(f"Recordings directory not found: {recordings_dir}")
    return recordings_dir


def load_golden_rows(path: Path | None = None) -> list[dict[str, object]]:
    """Load golden rows, failing loudly if the file is missing or empty."""
    target = path or get_golden_path()
    if not target.exists():
        raise FileNotFoundError(f"Golden dataset file not found: {target}")
    lines = [
        line.strip()
        for line in target.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not lines:
        raise ValueError(f"Golden dataset {target} is empty")
    return [json.loads(line) for line in lines]


def load_state_events(path: Path | None = None) -> dict[str, dict[str, object]]:
    """Load state snapshot events indexed by event ID, failing loudly if missing."""
    target = path or get_snapshot_path()
    if not target.exists():
        raise FileNotFoundError(f"State snapshot file not found: {target}")
    events: dict[str, dict[str, object]] = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            if "id" in entry:
                events[entry["id"]] = entry
    return events


def load_issues_snapshot(path: Path | None = None) -> dict[int, dict[str, object]]:
    """Load issues snapshot indexed by issue number, failing loudly if missing."""
    target = path or get_issues_snapshot_path()
    if not target.exists():
        raise FileNotFoundError(f"Issues snapshot file not found: {target}")
    issues: dict[int, dict[str, object]] = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            if "number" in entry:
                issues[entry["number"]] = entry
    return issues


def test_prompt_fingerprint() -> None:
    """Verify that the rendered sdlc-req-gate instructions match the recordings."""
    prompt_instructions = AGENT_BY_NAME["sdlc-req-gate"].instructions
    actual_sha = hashlib.sha256(prompt_instructions.encode("utf-8")).hexdigest()

    recordings_dir = get_recordings_dir()
    recording_files = list(recordings_dir.glob("*.json"))
    assert len(recording_files) > 0, "No recordings found in recordings directory"

    for rf in recording_files:
        rec_data = json.loads(rf.read_text(encoding="utf-8"))
        assert rec_data.get("prompt_sha256") == actual_sha, (
            "prompt changed: run T2 and re-record"
        )


def test_dataset_integrity() -> None:
    """Verify golden dataset schema, minimum counts, dedupe, and snapshot binding."""
    rows = load_golden_rows()
    assert len(rows) >= 16, f"Golden set must have at least 16 rows, got {len(rows)}"

    tuples = [(r["query"], r["score"], r["rounds"]) for r in rows]
    assert len(set(tuples)) == len(tuples), (
        "Dedupe rule violated: no two rows with the same (query, score, rounds)"
    )

    ready_rows = [r for r in rows if r["expected_outcome"] == GateOutcome.READY.value]
    refine_rows = [
        r for r in rows if r["expected_outcome"] == GateOutcome.NEEDS_REFINEMENT.value
    ]
    escalate_rows = [
        r for r in rows if r["expected_outcome"] == GateOutcome.ESCALATE.value
    ]

    assert len(ready_rows) >= 4, f"Need at least 4 READY rows, got {len(ready_rows)}"
    assert len(refine_rows) >= 4, (
        f"Need at least 4 NEEDS_REFINEMENT rows, got {len(refine_rows)}"
    )
    assert len(escalate_rows) >= 2, (
        f"Need at least 2 escalate rows, got {len(escalate_rows)}"
    )
    for row in rows:
        if row.get("issue_number") is not None and row["expected_outcome"] in (
            GateOutcome.READY.value,
            GateOutcome.NEEDS_REFINEMENT.value,
        ):
            assert row.get("synthetic") is False, (
                f"Real ticket row {row['id']} must have synthetic: false"
            )

    for er in escalate_rows:
        assert er.get("synthetic") is True, (
            f"Escalate row {er['id']} must be an explicit what-if with synthetic: true"
        )
        synth_fields = er.get("synthetic_fields", [])
        if er.get("issue_number") is not None:
            assert "rounds" in synth_fields and "expected_outcome" in synth_fields, (
                f"What-if row {er['id']} must declare rounds and expected_outcome in "
                f"synthetic_fields"
            )

    scores_in_band = [r for r in rows if 78 <= int(r["score"]) <= 82]
    assert len(scores_in_band) >= 2, (
        f"Expected at least 2 scores within 78..82, got {len(scores_in_band)}"
    )

    injection_rows = [r for r in rows if str(r["id"]).startswith("synthetic_injection")]
    assert len(injection_rows) >= 3, (
        f"Expected at least 3 planted-injection rows, got {len(injection_rows)}"
    )

    rows_by_issue = {
        r["issue_number"]: r for r in rows if r.get("issue_number") is not None
    }
    assert 9 in rows_by_issue, "Issue 9 must be present in golden rows"
    assert rows_by_issue[9]["score"] == 78
    assert rows_by_issue[9]["expected_outcome"] == GateOutcome.NEEDS_REFINEMENT.value

    assert 7 in rows_by_issue, "Issue 7 must be present in golden rows"
    assert rows_by_issue[7]["score"] == 80
    assert rows_by_issue[7]["expected_outcome"] == GateOutcome.READY.value

    assert 25 in rows_by_issue, "Issue 25 must be present in golden rows"
    assert rows_by_issue[25]["score"] == 83
    assert rows_by_issue[25]["expected_outcome"] == GateOutcome.READY.value

    assert 45 in rows_by_issue, "Issue 45 must be present in golden rows"
    assert rows_by_issue[45]["score"] == 60
    assert rows_by_issue[45]["expected_outcome"] == GateOutcome.ESCALATE.value

    assert 52 in rows_by_issue, "Issue 52 must be present in golden rows"
    assert rows_by_issue[52]["score"] == 5
    assert rows_by_issue[52]["rounds"] == 1
    assert rows_by_issue[52]["expected_outcome"] == GateOutcome.NEEDS_REFINEMENT.value

    issues_snapshot = load_issues_snapshot()
    for row in rows:
        assert row["expected_outcome"] in ALLOWED_OUTCOMES, (
            f"Invalid outcome: {row['expected_outcome']}"
        )
        num = row.get("issue_number")
        if num is not None:
            assert num in issues_snapshot, f"Issue #{num} missing from issues_snapshot"
            iss = issues_snapshot[num]
            assert row["title"] == iss["title"], (
                f"Row {row['id']} title does not match issues_snapshot"
            )
            expected_query = f"Title: {iss['title']}\n\nBody:\n{iss['body']}"
            assert row["query"] == expected_query, (
                f"Row {row['id']} query does not match issues_snapshot body exactly"
            )
            query_sha = hashlib.sha256(str(row["query"]).encode("utf-8")).hexdigest()
            assert query_sha == iss["sha256"], (
                f"Row {row['id']} query sha256 mismatch with issues_snapshot"
            )


def test_provenance_binding() -> None:
    """Verify non-synthetic rows and recordings strictly bind to snapshot provenance."""
    rows = load_golden_rows()
    events = load_state_events()
    recordings_dir = get_recordings_dir()

    for row in rows:
        row_id = str(row["id"])
        rec_path = recordings_dir / f"{row_id}.json"
        assert rec_path.exists(), f"Recording missing for row {row_id}: {rec_path}"

        rec_data = json.loads(rec_path.read_text(encoding="utf-8"))
        assert rec_data.get("synthetic") is True, (
            f"Recording {row_id} must have synthetic: true because criteria are hand-made"
        )
        assert len(rec_data.get("synthetic_fields", [])) > 0, (
            f"Recording {row_id} must list synthetic_fields"
        )

        resp = rec_data.get("response", {})
        criteria = resp.get("criteria", {})
        crit_sum = sum(int(v) for v in criteria.values())
        assert crit_sum == int(row["score"]), (
            f"Recording {row_id} criteria sum {crit_sum} != golden score {row['score']}"
        )

        prov = row.get("provenance", {})
        event_id = prov.get("event_id")
        field = str(prov.get("field", "quality"))

        if field.startswith("qa["):
            assert "summary" in rec_data.get("synthetic_fields", []), (
                f"Recording {row_id} with provenance field '{field}' "
                "must list summary in synthetic_fields"
            )

        if not row.get("synthetic"):
            assert not row.get("synthetic_fields"), (
                f"Real row {row_id} cannot have synthetic_fields"
            )
            assert event_id in events, (
                f"Event {event_id} for row {row_id} not found in state_snapshot"
            )
            event = events[event_id]
            assert event.get("type") == "ticket.updated", (
                f"Event {event_id} type is {event.get('type')}, expected ticket.updated"
            )
            assert event.get("issue") == row["issue_number"], (
                f"Event {event_id} issue {event.get('issue')} != row issue {row['issue_number']}"
            )

            ticket = event.get("data", {}).get("ticket", {})
            if field == "quality":
                q = ticket.get("quality", {})
                assert q.get("score") == row["score"], (
                    f"Row {row_id} score {row['score']} != snapshot score {q.get('score')}"
                )
                assert q.get("rounds") == row["rounds"], (
                    f"Row {row_id} rounds {row['rounds']} != snapshot rounds {q.get('rounds')}"
                )
            elif field.startswith("qa["):
                idx = int(field[3:field.index("]")])
                qa_item = ticket.get("qa", [])[idx]
                assert qa_item.get("score") == row["score"], (
                    f"Row {row_id} score {row['score']} != snapshot QA score {qa_item.get('score')}"
                )
                assert int(row["rounds"]) == 0, (
                    f"Row {row_id} qa-sourced score was round 0, got rounds {row['rounds']}"
                )
            else:
                raise ValueError(f"Unrecognized provenance field: {field}")
        else:
            if row.get("issue_number") is not None:
                assert event_id in events, (
                    f"What-if event {event_id} not in state_snapshot"
                )
                event = events[event_id]
                assert event.get("type") == "ticket.updated", (
                    f"What-if event {event_id} must have type ticket.updated"
                )
                assert event.get("issue") == row["issue_number"]
                ticket = event.get("data", {}).get("ticket", {})
                if field == "quality":
                    q = ticket.get("quality", {})
                    assert q.get("score") == row["score"]
                elif field.startswith("qa["):
                    idx = int(field[3:field.index("]")])
                    qa_item = ticket.get("qa", [])[idx]
                    assert qa_item.get("score") == row["score"]


def test_replay_gate() -> None:
    """Feed each recording through foundry._parse with _check_req_gate and machine.after_score."""
    golden_path = get_golden_path()
    recordings_dir = get_recordings_dir()
    rows = load_golden_rows(golden_path)
    assert len(rows) > 0, "No rows in golden dataset"

    for row in rows:
        row_id = str(row["id"])
        rec_path = recordings_dir / f"{row_id}.json"
        assert rec_path.exists(), f"Recording missing: {rec_path}"

        rec_data = json.loads(rec_path.read_text(encoding="utf-8"))
        raw_text = rec_data.get("raw_output")
        assert raw_text, f"Recording {row_id} missing raw_output"

        parsed = foundry._parse("sdlc-req-gate", raw_text, _check_req_gate)

        rounds = int(row.get("rounds", 0))
        outcome = resolve_outcome(parsed["score"], rounds)

        assert outcome == row["expected_outcome"], (
            f"Row {row_id} (score {parsed['score']}, rounds {rounds}) outcome mismatch: "
            f"got {outcome}, expected {row['expected_outcome']}"
        )


def test_check_req_gate_score_correction() -> None:
    """_check_req_gate corrects raw score to the exact sum of criteria."""
    data = {
        "criteria": {
            "clear_goal": 20,
            "testable_acceptance_criteria": 20,
            "defined_scope": 20,
            "edge_cases": 20,
        },
        "score": 50,  # Model mistakenly reported 50 instead of 80
        "summary": "Sample summary",
        "acceptance_criteria": ["Sample criterion"],
        "questions": ["Old question"],
    }
    _check_req_gate(data)
    assert data["score"] == 80, f"Expected score 80, got {data['score']}"
    assert data["questions"] == [], "Questions must be cleared when score >= 80"


def test_check_req_gate_rejects_sub_80_with_empty_questions() -> None:
    """_check_req_gate raises ValueError when score is below 80 and questions is empty."""
    data = {
        "criteria": {
            "clear_goal": 15,
            "testable_acceptance_criteria": 15,
            "defined_scope": 15,
            "edge_cases": 15,
        },
        "score": 60,
        "summary": "Incomplete requirements",
        "acceptance_criteria": ["Draft"],
        "questions": [],  # Sub-80 without questions must be rejected
    }
    with pytest.raises(
        ValueError,
        match=r"sdlc-req-gate: score 60 is below 80 but no questions",
    ):
        _check_req_gate(data)
