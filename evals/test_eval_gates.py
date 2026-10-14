"""
Tests for SDLC evaluation gates and regression detection.

Demonstrates how evaluation gates catch prompt regressions and score drift
in continuous integration without requiring live Azure calls during unit testing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.evaluators.score_band import ScoreBandEvaluator

DATASET_PATH = Path(__file__).parent / "datasets" / "req_gate_golden.jsonl"


@pytest.fixture
def golden_dataset() -> list[dict]:
    """Load golden evaluation dataset rows."""
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_score_band_evaluator_golden_pass(golden_dataset: list[dict]) -> None:
    """Validate that all golden items pass the score band and gate verdict checks."""
    evaluator = ScoreBandEvaluator(tolerance=10, quality_threshold=80)

    for item in golden_dataset:
        res = evaluator(
            score=item["score"],
            expected_min=item["expected_min"],
            expected_max=item["expected_max"],
            expected_gate=item["expected_gate"],
        )
        assert res["score_in_band"] == 1.0, (
            f"Issue #{item['issue_number']} score {item['score']} fell outside expected band "
            f"[{item['expected_min']}, {item['expected_max']}] with delta {res['score_delta']}"
        )
        assert res["gate_match"] == 1.0, (
            f"Issue #{item['issue_number']} gate verdict mismatch: got {res['actual_gate']}, "
            f"expected {item['expected_gate']}"
        )


def test_score_band_evaluator_failing_regression_caught() -> None:
    """Demonstrate that prompt regression or score drift fails the CI eval gate.

    Scenario: A modified prompt causes vague issues (like Issue #5 or Issue #52) to be
    over-scored at 85 (passing the 80-point gate instead of failing).
    """
    evaluator = ScoreBandEvaluator(tolerance=10, quality_threshold=80)

    # Simulated regressed output for vague issue #52 (expected band 0..20, expected gate: fail)
    regressed_score = 85  # Prompt drift erroneously inflated requirement score

    res = evaluator(
        score=regressed_score,
        expected_min=0,
        expected_max=20,
        expected_gate="fail",
    )

    # Eval gate detects that score is far outside the tolerance band (+55 delta)
    assert res["score_in_band"] == 0.0
    assert res["score_delta"] == 55.0

    # Eval gate detects that an unacceptable requirement bypassed the 80-point threshold
    assert res["actual_gate"] == "pass"
    assert res["gate_match"] == 0.0


def test_score_band_evaluator_boundary_conditions() -> None:
    """Test boundary conditions for 80-point gate threshold and tolerance bands."""
    evaluator = ScoreBandEvaluator(tolerance=10, quality_threshold=80)

    # Exactly on boundary 80
    at_threshold = evaluator(score=80, expected_min=80, expected_max=90, expected_gate="pass")
    assert at_threshold["score_in_band"] == 1.0
    assert at_threshold["actual_gate"] == "pass"
    assert at_threshold["gate_match"] == 1.0

    # Just below boundary 79
    below_threshold = evaluator(score=79, expected_min=75, expected_max=85, expected_gate="fail")
    assert below_threshold["actual_gate"] == "fail"
    assert below_threshold["gate_match"] == 1.0

    # Within tolerance of band: expected 80..90, tolerance 10 -> lower bound 70
    within_tolerance = evaluator(score=72, expected_min=80, expected_max=90)
    assert within_tolerance["score_in_band"] == 1.0
    assert within_tolerance["score_delta"] == 0.0
