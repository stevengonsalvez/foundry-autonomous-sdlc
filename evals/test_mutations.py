"""Mutation testing suite for offline requirement-gate evaluation gate.

Proves that modifying gate code, prompt instructions, thresholds, or dataset
expectations causes the gate to fail loudly and deterministically.
Each test operates in an isolated temporary tree and executes the actual
evals/test_replay.py test suite as a subprocess.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def _setup_tmp_tree(tmp_path: Path) -> tuple[Path, Path]:
    """Copy evals and agents trees to a temporary directory."""
    evals_dst = tmp_path / "evals"
    shutil.copytree(Path("evals"), evals_dst)
    agents_dst = tmp_path / "agents"
    shutil.copytree(Path("agents"), agents_dst)
    return evals_dst, agents_dst


def _run_replay(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run pytest on the temporary evals/test_replay.py as a subprocess."""
    agents_dir = tmp_path / "agents"
    evals_test = tmp_path / "evals" / "test_replay.py"
    env = {
        **os.environ,
        "PYTHONPATH": f"{agents_dir.resolve()}:{os.environ.get('PYTHONPATH', '')}",
    }
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(evals_test)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_mutation_quality_threshold_90(tmp_path: Path) -> None:
    """Prove that setting QUALITY_THRESHOLD = 90 causes the gate to fail."""
    _, agents_dir = _setup_tmp_tree(tmp_path)
    definitions_py = agents_dir / "sdlc_agents" / "definitions.py"
    content = definitions_py.read_text(encoding="utf-8")
    assert "QUALITY_THRESHOLD = 80" in content
    definitions_py.write_text(
        content.replace("QUALITY_THRESHOLD = 80", "QUALITY_THRESHOLD = 90"),
        encoding="utf-8",
    )

    res = _run_replay(tmp_path)
    assert res.returncode != 0, "Gate unexpectedly passed when QUALITY_THRESHOLD was 90"
    out = res.stdout + res.stderr
    assert "outcome mismatch" in out or "NEEDS_REFINEMENT" in out or "below 90" in out


def test_mutation_req_gate_prompt_edit(tmp_path: Path) -> None:
    """Prove that editing the req-gate prompt instructions causes the gate to fail."""
    _, agents_dir = _setup_tmp_tree(tmp_path)
    definitions_py = agents_dir / "sdlc_agents" / "definitions.py"
    content = definitions_py.read_text(encoding="utf-8")
    assert '_REQ_GATE = f"""' in content
    definitions_py.write_text(
        content.replace('_REQ_GATE = f"""', '_REQ_GATE = f"""!'),
        encoding="utf-8",
    )

    res = _run_replay(tmp_path)
    assert res.returncode != 0, "Gate unexpectedly passed after prompt instruction edit"
    assert "prompt changed: run T2 and re-record" in (res.stdout + res.stderr)


def test_mutation_empty_golden_file(tmp_path: Path) -> None:
    """Prove that an empty golden dataset causes the gate to fail."""
    evals_dir, _ = _setup_tmp_tree(tmp_path)
    golden_path = evals_dir / "datasets" / "req_gate_golden.jsonl"
    golden_path.write_text("", encoding="utf-8")

    res = _run_replay(tmp_path)
    assert res.returncode != 0, "Gate unexpectedly passed with an empty golden file"
    out = res.stdout + res.stderr
    assert "empty" in out or "at least 16 rows" in out


def test_mutation_missing_expected_outcome(tmp_path: Path) -> None:
    """Prove that a golden row missing expected_outcome causes the gate to fail."""
    evals_dir, _ = _setup_tmp_tree(tmp_path)
    golden_path = evals_dir / "datasets" / "req_gate_golden.jsonl"
    rows = [
        json.loads(line)
        for line in golden_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    del rows[0]["expected_outcome"]
    golden_path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )

    res = _run_replay(tmp_path)
    assert res.returncode != 0, "Gate unexpectedly passed with missing expected_outcome"
    assert "expected_outcome" in (res.stdout + res.stderr)


def test_mutation_relabel_issue_9_ready(tmp_path: Path) -> None:
    """Prove that relabelling issue 9 to READY causes the gate to fail."""
    evals_dir, _ = _setup_tmp_tree(tmp_path)
    golden_path = evals_dir / "datasets" / "req_gate_golden.jsonl"
    rows = [
        json.loads(line)
        for line in golden_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for r in rows:
        if r.get("issue_number") == 9:
            r["expected_outcome"] = "READY"
    golden_path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )

    res = _run_replay(tmp_path)
    assert res.returncode != 0, "Gate unexpectedly passed when issue 9 was relabelled READY"
    out = res.stdout + res.stderr
    assert "READY" in out or "outcome mismatch" in out or "NEEDS_REFINEMENT" in out


def test_mutation_golden_score_set_to_42(tmp_path: Path) -> None:
    """Prove that changing golden score to 42 causes the gate to fail."""
    evals_dir, _ = _setup_tmp_tree(tmp_path)
    golden_path = evals_dir / "datasets" / "req_gate_golden.jsonl"
    rows = [
        json.loads(line)
        for line in golden_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for r in rows:
        if r["id"] == "issue_7":
            r["score"] = 42
    golden_path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )

    res = _run_replay(tmp_path)
    assert res.returncode != 0, "Gate unexpectedly passed with score set to 42"
    out = res.stdout + res.stderr
    assert "criteria sum" in out or "score" in out or "42" in out


def test_mutation_recording_issue_15_criteria_sum_85(tmp_path: Path) -> None:
    """Prove that mutating recording issue_15 criteria sum to 85 fails the gate."""
    evals_dir, _ = _setup_tmp_tree(tmp_path)
    rec_path = evals_dir / "recordings" / "req_gate" / "issue_15.json"
    rec_data = json.loads(rec_path.read_text(encoding="utf-8"))
    rec_data["response"]["criteria"]["clear_goal"] = 16  # Sum becomes 85 instead of 93
    rec_data["response"]["score"] = 85
    rec_data["raw_output"] = json.dumps(rec_data["response"])
    rec_path.write_text(json.dumps(rec_data, indent=2) + "\n", encoding="utf-8")

    res = _run_replay(tmp_path)
    assert res.returncode != 0, "Gate unexpectedly passed when issue_15 criteria sum was 85"
    out = res.stdout + res.stderr
    assert "criteria sum" in out or "85" in out or "93" in out


def test_mutation_provenance_pointed_to_billing_event(tmp_path: Path) -> None:
    """Prove that pointing provenance to a billing event causes the gate to fail."""
    evals_dir, _ = _setup_tmp_tree(tmp_path)
    golden_path = evals_dir / "datasets" / "req_gate_golden.jsonl"
    rows = [
        json.loads(line)
        for line in golden_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for r in rows:
        if r["id"] == "issue_7":
            r["provenance"]["event_id"] = "28731d003a0fe448"  # billing.observed event
    golden_path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )

    res = _run_replay(tmp_path)
    assert res.returncode != 0, "Gate unexpectedly passed when provenance was billing event"
    out = res.stdout + res.stderr
    assert "ticket.updated" in out or "billing" in out


def test_mutation_synthetic_flipped_on_real_row(tmp_path: Path) -> None:
    """Prove that setting synthetic: true on a real issue row causes the gate to fail."""
    evals_dir, _ = _setup_tmp_tree(tmp_path)
    golden_path = evals_dir / "datasets" / "req_gate_golden.jsonl"
    rows = [
        json.loads(line)
        for line in golden_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for r in rows:
        if r["id"] == "issue_7":
            r["synthetic"] = True
    golden_path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )

    res = _run_replay(tmp_path)
    assert res.returncode != 0, "Gate unexpectedly passed with synthetic flipped on real row"
    out = res.stdout + res.stderr
    assert "synthetic: false" in out or "Real ticket row" in out


def test_mutation_remove_check_req_gate_score_correction(tmp_path: Path) -> None:
    """Prove that removing score correction from _check_req_gate causes gate failure."""
    _, agents_dir = _setup_tmp_tree(tmp_path)
    definitions_py = agents_dir / "sdlc_agents" / "definitions.py"
    content = definitions_py.read_text(encoding="utf-8")
    target_line = '    data["score"] = sum(data["criteria"][name] for name in CRITERIA)\n'
    assert target_line in content
    definitions_py.write_text(content.replace(target_line, "    pass\n"), encoding="utf-8")

    res = _run_replay(tmp_path)
    assert res.returncode != 0, "Gate unexpectedly passed without score correction"
    out = res.stdout + res.stderr
    assert "test_check_req_gate_score_correction" in out or "score" in out


def test_mutation_remove_check_req_gate_empty_questions_check(tmp_path: Path) -> None:
    """Prove that removing the sub-80 empty questions check causes gate failure."""
    _, agents_dir = _setup_tmp_tree(tmp_path)
    definitions_py = agents_dir / "sdlc_agents" / "definitions.py"
    content = definitions_py.read_text(encoding="utf-8")
    target_block = (
        '    elif not data["questions"]:\n'
        '        raise ValueError(f"sdlc-req-gate: score {data[\'score\']} is below '
        '{QUALITY_THRESHOLD} but no questions")\n'
    )
    assert target_block in content
    definitions_py.write_text(content.replace(target_block, ""), encoding="utf-8")

    res = _run_replay(tmp_path)
    assert res.returncode != 0, "Gate unexpectedly passed without empty questions check"
    out = res.stdout + res.stderr
    assert (
        "test_check_req_gate_rejects_sub_80_with_empty_questions" in out
        or "DID NOT RAISE" in out
    )
