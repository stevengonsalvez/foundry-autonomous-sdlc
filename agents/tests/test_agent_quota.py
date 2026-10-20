"""
agy runs on one Antigravity account's quota (Key Vault secret agy-cli-token). When that is spent both agy
engines die at once and the model-loop fallback cannot do the work (live issue 96: j-96-3 and j-96-4, about
0.16 USD each for nothing). The coder fails such a job fast as `agent-quota`. The orchestrator escalates it
(`escalated:agent-quota`, terminal) instead of retrying: the reset can be a week away, so a deferral would
start a new coder session every tick for nothing; the owner rotates the token or waits, then requeues.
"""

from __future__ import annotations

from conftest import World
from test_scenarios import A_BODY

from sdlc_agents import machine, state


def starts(world: World) -> list[str]:
    return [body["job"]["job_id"] for _, body, _ in world.foundry.hosted if body["op"] == "start"]


def test_the_label_is_a_terminal_escalation() -> None:
    assert state.ESC_AGENT_QUOTA == "escalated:agent-quota"
    assert state.ESC_AGENT_QUOTA in state.ESCALATIONS
    assert "agent-quota" in __import__("sdlc_agents.tick", fromlist=["CODER_REASONS"]).CODER_REASONS


def test_after_coder_maps_agent_quota_to_its_own_escalation() -> None:
    out = machine.after_coder("failed", "agent-quota")
    assert out.escalate == state.ESC_AGENT_QUOTA and not out.retry and not out.resume


def test_an_agent_quota_failure_escalates_once_without_another_job_or_attempt(world: World) -> None:
    gh = world.gh
    world.coder.outcomes = ["failed:agent-quota"]
    n = gh.open_issue("Show the estimated delivery date", A_BODY)

    world.drive(lambda: state.ESC_AGENT_QUOTA in gh.labels(n), max_ticks=30)
    world.tick(3)

    assert starts(world) == [f"j-{n}-1"]                       # no retry, no second job
    esc = gh.state_of(n)["escalation"]
    assert esc["label"] == state.ESC_AGENT_QUOTA and "agent-quota" in esc["reasons"][0]
    assert state.ESC_BUILD_FAILED not in gh.labels(n) and gh.merges == []
