"""
Custom code evaluator for requirement quality gate scoring.

Validates:
1. Whether an agent score falls within the expected tolerance band (+/- 10 points).
2. Whether the agent 80-point gate decision matches the expected pass/fail verdict.
"""

from __future__ import annotations

from typing import Any


class ScoreBandEvaluator:
    """Evaluates whether an SDLC requirement score matches expected thresholds."""

    def __init__(self, tolerance: int = 10, quality_threshold: int = 80):
        self.tolerance = tolerance
        self.quality_threshold = quality_threshold

    def __call__(
        self,
        *,
        score: float,
        expected_min: float,
        expected_max: float,
        expected_gate: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Evaluate score against expected range with tolerance."""
        lower = max(0, float(expected_min) - self.tolerance)
        upper = min(100, float(expected_max) + self.tolerance)
        score_val = float(score)

        in_band = lower <= score_val <= upper
        if in_band:
            delta = 0.0
        elif score_val < lower:
            delta = lower - score_val
        else:
            delta = score_val - upper

        actual_gate = "pass" if score_val >= self.quality_threshold else "fail"
        gate_match = 1.0 if (expected_gate is None or actual_gate == expected_gate) else 0.0

        return {
            "score_in_band": 1.0 if in_band else 0.0,
            "score_delta": round(delta, 2),
            "actual_gate": actual_gate,
            "gate_match": gate_match,
        }
