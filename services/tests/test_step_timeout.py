from __future__ import annotations

from pathlib import Path

from sdlc_factory.config import load_factory
from sdlc_factory.workflows import STEP_TIMEOUT

REPO = Path(__file__).resolve().parents[2]
JSON_REPAIR_ROUNDS = 2   # run_json_agent default: one call plus two repairs


def test_step_timeout_outlasts_the_slowest_agent_with_its_repair_rounds() -> None:
    # A step that Temporal times out is cancelled mid-call and counts as a failed agent call; three of them
    # escalate the issue (live scenario a: the test designer, 600 s per call, against a 10 minute step).
    agents = load_factory(REPO / "factory" / "factory.yaml").agents.values()
    slowest = max(agent.timeout_s for agent in agents if agent.output_kind == "json")   # prompt agents
    worst_agent_s = slowest * (1 + JSON_REPAIR_ROUNDS)
    assert STEP_TIMEOUT.total_seconds() >= worst_agent_s + 300
