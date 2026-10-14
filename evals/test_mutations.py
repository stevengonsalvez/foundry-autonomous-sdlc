"""Prove that each required mutation in the acceptance criteria fails the evaluation gate.

Mutations tested in an isolated temporary copy:
1. QUALITY_THRESHOLD = 90
2. A one-character edit to _REQ_GATE
3. An empty golden file
4. A row missing expected_outcome
5. Issue 9 relabelled READY
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from sdlc_agents import definitions, foundry, machine
from sdlc_agents.definitions import AGENT_BY_NAME

from evals.test_replay import (
    GateOutcome,
    get_golden_path,
    get_recordings_dir,
    get_snapshot_path,
    load_golden_rows,
    resolve_outcome,
)


def _copy_evals_to_tmp(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create an isolated temporary copy of the dataset and recordings."""
    evals_tmp = tmp_path / "evals"
    datasets_tmp = evals_tmp / "datasets"
    recordings_tmp = evals_tmp / "recordings" / "req_gate"
    datasets_tmp.mkdir(parents=True, exist_ok=True)
    recordings_tmp.mkdir(parents=True, exist_ok=True)

    golden_src = get_golden_path()
    snapshot_src = get_snapshot_path()
    golden_dst = datasets_tmp / "req_gate_golden.jsonl"
    snapshot_dst = datasets_tmp / "state_snapshot.jsonl"

    shutil.copyfile(golden_src, golden_dst)
    shutil.copyfile(snapshot_src, snapshot_dst)

    for rec in get_recordings_dir().glob("*.json"):
        shutil.copyfile(rec, recordings_tmp / rec.name)

    return golden_dst, recordings_tmp, snapshot_dst


def _run_gate_on_copy(golden_path: Path, recordings_dir: Path, snapshot_path: Path) -> None:
    """Run all evaluation gate checks against a specific copy of data."""
    # 1. Prompt fingerprint
    prompt_instructions = AGENT_BY_NAME["sdlc-req-gate"].instructions
    actual_sha = hashlib.sha256(prompt_instructions.encode("utf-8")).hexdigest()
    rec_files = list(recordings_dir.glob("*.json"))
    assert len(rec_files) > 0, "No recordings found"
    for rf in rec_files:
        rec_data = json.loads(rf.read_text(encoding="utf-8"))
        if rec_data.get("prompt_sha256") != actual_sha:
            pytest.fail("prompt changed: run T2 and re-record")

    # 2. Dataset integrity
    rows = [json.loads(line) for line in golden_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) >= 1, "Golden set must contain at least 1 row"
    assert len(rows) >= 16, f"Golden set must have at least 16 rows, got {len(rows)}"

    allowed_labels = {e.value for e in GateOutcome}
    for row in rows:
        assert "expected_outcome" in row, f"Row {row.get('id')} missing expected_outcome"
        assert row["expected_outcome"] in allowed_labels

    snapshot_events = {
        json.loads(line)["id"]
        for line in snapshot_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    for row in rows:
        prov = row["provenance"]
        if row["synthetic"]:
            assert prov["event_id"].startswith("synthetic") or prov["event_id"] in snapshot_events
        else:
            assert prov["event_id"] in snapshot_events

    rows_by_issue = {r["issue_number"]: r for r in rows if r.get("issue_number") is not None}
    if 9 in rows_by_issue:
        assert rows_by_issue[9]["expected_outcome"] == GateOutcome.NEEDS_REFINEMENT

    # 3. Replay
    for row in rows:
        rec_file = recordings_dir / f"{row['id']}.json"
        assert rec_file.exists(), f"Recording missing: {rec_file}"
        rec_data = json.loads(rec_file.read_text(encoding="utf-8"))
        raw_text = rec_data.get("raw_output") or json.dumps(rec_data.get("response", rec_data))
        parsed = foundry._parse("sdlc-req-gate", raw_text, definitions._check_req_gate)
        rounds = int(row.get("rounds", 0))
        outcome = resolve_outcome(parsed["score"], rounds)
        assert outcome == row["expected_outcome"]


def test_mutation_quality_threshold_90(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prove that setting QUALITY_THRESHOLD = 90 causes the gate to fail."""
    golden_dst, rec_dir, snap_dst = _copy_evals_to_tmp(tmp_path)

    # Mutate QUALITY_THRESHOLD to 90
    monkeypatch.setattr(definitions, "QUALITY_THRESHOLD", 90)
    monkeypatch.setattr(machine, "QUALITY_THRESHOLD", 90)

    with pytest.raises((ValueError, AssertionError)) as exc_info:
        _run_gate_on_copy(golden_dst, rec_dir, snap_dst)

    # Issue 7 (score 80) fails because score < 90 without questions, and after_score returns NEEDS_REFINEMENT
    assert "sdlc-req-gate" in str(exc_info.value) or "outcome mismatch" in str(exc_info.value) or "below 90" in str(exc_info.value)


def test_mutation_req_gate_prompt_edit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prove that a one-character edit to _REQ_GATE causes the gate to fail."""
    golden_dst, rec_dir, snap_dst = _copy_evals_to_tmp(tmp_path)

    orig_agent = AGENT_BY_NAME["sdlc-req-gate"]
    mutated_agent = replace(orig_agent, instructions=orig_agent.instructions + " ")
    monkeypatch.setitem(AGENT_BY_NAME, "sdlc-req-gate", mutated_agent)

    with pytest.raises(pytest.fail.Exception, match="prompt changed: run T2 and re-record"):
        _run_gate_on_copy(golden_dst, rec_dir, snap_dst)


def test_mutation_empty_golden_file(tmp_path: Path) -> None:
    """Prove that an empty golden file causes the gate to fail."""
    golden_dst, rec_dir, snap_dst = _copy_evals_to_tmp(tmp_path)

    # Empty the golden file
    golden_dst.write_text("", encoding="utf-8")

    with pytest.raises(AssertionError, match="at least 1 row"):
        _run_gate_on_copy(golden_dst, rec_dir, snap_dst)


def test_mutation_row_missing_expected_outcome(tmp_path: Path) -> None:
    """Prove that a row missing expected_outcome causes the gate to fail."""
    golden_dst, rec_dir, snap_dst = _copy_evals_to_tmp(tmp_path)

    rows = load_golden_rows(golden_dst)
    # Delete expected_outcome from the first row
    del rows[0]["expected_outcome"]
    golden_dst.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    with pytest.raises((AssertionError, KeyError)):
        _run_gate_on_copy(golden_dst, rec_dir, snap_dst)


def test_mutation_issue_9_relabelled_ready(tmp_path: Path) -> None:
    """Prove that relabelling issue 9 to READY causes the gate to fail."""
    golden_dst, rec_dir, snap_dst = _copy_evals_to_tmp(tmp_path)

    rows = load_golden_rows(golden_dst)
    for r in rows:
        if r.get("issue_number") == 9:
            r["expected_outcome"] = "READY"
    golden_dst.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    with pytest.raises(AssertionError):
        _run_gate_on_copy(golden_dst, rec_dir, snap_dst)
