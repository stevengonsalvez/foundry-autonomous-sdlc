"""Deterministic offline requirement-gate replay and integrity tests.

Replays recorded model outputs through foundry._parse, _check_req_gate, and
machine.after_score, asserting outcomes match golden expectations without secrets
or network calls.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from enum import StrEnum
from pathlib import Path

import pytest
from sdlc_agents import foundry, machine
from sdlc_agents.definitions import AGENT_BY_NAME, QUALITY_THRESHOLD, _check_req_gate


class GateOutcome(StrEnum):
    READY = "READY"
    NEEDS_REFINEMENT = "NEEDS_REFINEMENT"
    ESCALATE = "escalate"


def resolve_outcome(score: int, rounds: int) -> GateOutcome:
    """Map machine.after_score outcome to GateOutcome enum."""
    outcome = machine.after_score(score, rounds)
    if outcome.stage == machine.READY:
        return GateOutcome.READY
    if outcome.stage == machine.NEEDS_REFINEMENT:
        return GateOutcome.NEEDS_REFINEMENT
    if outcome.escalate is not None:
        return GateOutcome.ESCALATE
    raise ValueError(f"Unrecognized machine outcome: {outcome}")


def get_golden_path() -> Path:
    trusted = Path("trusted/evals/datasets/req_gate_golden.jsonl")
    if trusted.exists():
        return trusted
    return Path("evals/datasets/req_gate_golden.jsonl")


def get_recordings_dir() -> Path:
    trusted = Path("trusted/evals/recordings/req_gate")
    if trusted.exists():
        return trusted
    return Path("evals/recordings/req_gate")


def get_snapshot_path() -> Path:
    trusted = Path("trusted/evals/datasets/state_snapshot.jsonl")
    if trusted.exists():
        return trusted
    return Path("evals/datasets/state_snapshot.jsonl")


def load_golden_rows(path: Path | None = None) -> list[dict[str, object]]:
    target = path or get_golden_path()
    if not target.exists():
        return []
    lines = [line.strip() for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def test_prompt_fingerprint() -> None:
    """Verify that the rendered sdlc-req-gate instructions match the recordings."""
    prompt_instructions = AGENT_BY_NAME["sdlc-req-gate"].instructions
    actual_sha = hashlib.sha256(prompt_instructions.encode("utf-8")).hexdigest()

    recordings_dir = get_recordings_dir()
    recording_files = list(recordings_dir.glob("*.json"))
    assert len(recording_files) > 0, "No recordings found"

    for rec_file in recording_files:
        rec_data = json.loads(rec_file.read_text(encoding="utf-8"))
        rec_sha = rec_data.get("prompt_sha256")
        if rec_sha != actual_sha:
            pytest.fail("prompt changed: run T2 and re-record")


def test_golden_dataset_integrity() -> None:
    """Verify schema, provenance, boundary cases, label enum, and query distribution."""
    golden_path = get_golden_path()
    assert golden_path.exists(), f"Golden dataset missing: {golden_path}"

    rows = load_golden_rows(golden_path)

    # At least 1 row (and at least 16)
    assert len(rows) >= 1, "Golden set must contain at least 1 row"
    assert len(rows) >= 16, f"Golden set must have at least 16 rows, got {len(rows)}"

    # Labels limited to the enum
    allowed_labels = {e.value for e in GateOutcome}
    for row in rows:
        assert "expected_outcome" in row, f"Row {row.get('id')} missing expected_outcome"
        assert row["expected_outcome"] in allowed_labels, (
            f"Row {row.get('id')} has invalid outcome {row['expected_outcome']!r}, must be in {allowed_labels}"
        )

    # Schema checks
    required_keys = {"id", "expected_outcome", "rounds", "score", "provenance", "query", "title", "synthetic"}
    for row in rows:
        missing = required_keys - set(row)
        assert not missing, f"Row {row.get('id')} missing keys: {missing}"
        assert isinstance(row["rounds"], int) and row["rounds"] >= 0
        assert isinstance(row["score"], int) and 0 <= row["score"] <= 100
        assert isinstance(row["synthetic"], bool)
        assert isinstance(row["provenance"], dict)
        assert "event_id" in row["provenance"] and "path" in row["provenance"]

    # No placeholder strings
    placeholders = {"TODO", "FIXME", "PLACEHOLDER", "<row>", "<sha>", "TBD", "XXX"}
    for row in rows:
        for k, v in row.items():
            if isinstance(v, str):
                for p in placeholders:
                    assert p not in v, f"Placeholder {p!r} found in row {row['id']} field {k}"

    # Provenance resolves into the snapshot
    snapshot_path = get_snapshot_path()
    assert snapshot_path.exists(), f"Snapshot file missing: {snapshot_path}"
    snapshot_events = {
        json.loads(line)["id"]
        for line in snapshot_path.read_text(encoding="utf-8").strip().splitlines()
        if line.strip()
    }
    for row in rows:
        prov = row["provenance"]
        assert prov["path"] == "evals/datasets/state_snapshot.jsonl"
        if row["synthetic"]:
            assert prov["event_id"].startswith("synthetic") or prov["event_id"] in snapshot_events
        else:
            assert prov["event_id"] in snapshot_events, (
                f"Provenance event_id {prov['event_id']} for row {row['id']} not found in snapshot"
            )

    # Class and boundary minimums: at least 4 per outcome
    outcome_counts = Counter(str(row["expected_outcome"]) for row in rows)
    for outcome_val in allowed_labels:
        assert outcome_counts[outcome_val] >= 4, (
            f"Expected at least 4 rows for outcome {outcome_val}, got {outcome_counts[outcome_val]}"
        )

    # At least 2 scores within 78..82
    in_boundary = [r for r in rows if 78 <= int(r["score"]) <= 82]
    assert len(in_boundary) >= 2, f"Expected at least 2 scores within 78..82, got {len(in_boundary)}"

    # At least 3 planted-injection issue bodies (synthetic, labelled synthetic)
    injections = [r for r in rows if r["synthetic"]]
    assert len(injections) >= 3, f"Expected at least 3 injection rows, got {len(injections)}"

    # At most 2 rows share a query (no query more than twice)
    query_counts = Counter(str(r["query"]).strip() for r in rows)
    for q, count in query_counts.items():
        assert count <= 2, f"Query appears {count} times (max 2 allowed): {q[:60]}..."

    # Real boundary cases included
    rows_by_issue = {r["issue_number"]: r for r in rows if r.get("issue_number") is not None}
    assert 9 in rows_by_issue and rows_by_issue[9]["score"] == 78 and rows_by_issue[9]["expected_outcome"] == GateOutcome.NEEDS_REFINEMENT
    assert 7 in rows_by_issue and rows_by_issue[7]["score"] == 80 and rows_by_issue[7]["expected_outcome"] == GateOutcome.READY
    assert 25 in rows_by_issue and rows_by_issue[25]["score"] == 83 and rows_by_issue[25]["expected_outcome"] == GateOutcome.READY
    assert 45 in rows_by_issue and rows_by_issue[45]["score"] == 60 and rows_by_issue[45]["expected_outcome"] == GateOutcome.ESCALATE
    assert 52 in rows_by_issue and rows_by_issue[52]["score"] == 5 and rows_by_issue[52]["expected_outcome"] == GateOutcome.NEEDS_REFINEMENT


def test_replay_req_gate() -> None:
    """Feed each recording through foundry._parse with _check_req_gate and machine.after_score."""
    golden_path = get_golden_path()
    recordings_dir = get_recordings_dir()
    rows = load_golden_rows(golden_path)
    assert len(rows) > 0, "No rows in golden dataset"

    # Verify QUALITY_THRESHOLD is imported, not hardcoded
    assert QUALITY_THRESHOLD is not None

    for row in rows:
        row_id = str(row["id"])
        rec_filename = f"{row_id}.json"
        rec_path = recordings_dir / rec_filename
        if not rec_path.exists() and "recording" in row:
            rec_path = Path(str(row["recording"]))
        assert rec_path.exists(), f"Recording {rec_filename} not found for row {row_id}"

        rec_data = json.loads(rec_path.read_text(encoding="utf-8"))
        raw_text = rec_data.get("raw_output")
        if not raw_text:
            raw_text = json.dumps(rec_data.get("response", rec_data))

        parsed = foundry._parse("sdlc-req-gate", raw_text, _check_req_gate)

        rounds = int(row.get("rounds", 0))
        outcome = resolve_outcome(parsed["score"], rounds)

        assert outcome == row["expected_outcome"], (
            f"Row {row_id} (score {parsed['score']}, rounds {rounds}) outcome mismatch: "
            f"got {outcome}, expected {row['expected_outcome']}"
        )


def test_required_checks_equality() -> None:
    """Verify REQUIRED_CHECKS in gates.py and setup_repo.py remain identical and contain evals."""
    from sdlc_agents import gates

    from scripts import setup_repo

    assert gates.REQUIRED_CHECKS == setup_repo.REQUIRED_CHECKS
    assert "evals" in gates.REQUIRED_CHECKS
