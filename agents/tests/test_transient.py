"""
Transient failures (rate limits, timeouts, 5xx, dropped connections) are retried with backoff
inside the tick and, if they persist, defer the object to the next tick untouched. They never count
toward a failure threshold and never change a verdict. Only bad agent output (after one repair
retry) or a refusal counts, and three of those escalate `escalated:agent-error`.
"""

from __future__ import annotations

import json

import pytest
from conftest import World
from test_scenarios import A_BODY

from sdlc_agents import state
from sdlc_agents.foundry import AgentRunError
from sdlc_agents.ports import GitHubError


def rate_limited(retry_after: float | None = None) -> AgentRunError:
    return AgentRunError("sdlc-req-gate: HTTP 429: rate_limit_exceeded", transient=True, retry_after=retry_after)


def labels_and_comments(world: World, n: int) -> tuple:
    return sorted(world.gh.labels(n)), json.dumps([c.body for c in world.gh.comments[n]])


def ready_issue(world: World) -> int:
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))
    world.tick()
    assert state.READY in world.gh.labels(n)
    return n


def test_rate_limit_twice_then_success_is_absorbed_inside_the_tick(world: World) -> None:
    world.foundry.fail_next["sdlc-req-gate"] = [rate_limited(retry_after=5), rate_limited()]
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY, labels=("type:feature",))

    report = world.tick()[0]

    assert [o.result for o in report.objects if o.number == n] == ["ok"]
    assert state.READY in world.gh.labels(n)
    assert world.sleeps[0] == 5                      # Retry-After honoured
    assert 2.0 <= world.sleeps[1] <= 4.0             # then exponential backoff with jitter
    st = world.gh.state_of(n)
    assert st["failures"] is None and len(st["cost"]["calls"]) == 1


def test_persistent_rate_limit_leaves_the_issue_in_its_stage_with_nothing_written(world: World) -> None:
    n = ready_issue(world)
    before = labels_and_comments(world, n)
    world.foundry.errors["sdlc-feasibility"] = rate_limited()

    reports = world.tick(6)

    assert labels_and_comments(world, n) == before
    assert {o.result for r in reports for o in r.objects if o.number == n} == {"deferred"}
    assert "rate_limit_exceeded" in reports[0].objects[0].detail
    st = world.gh.state_of(n)
    assert st["failures"] is None and st["escalation"] is None and st["stages"][-1]["stage"] == state.READY
    doc = json.loads(world.gh.files[("metrics", "metrics.json")])
    assert doc["issues"][0]["deferred"].startswith("AgentRunError") and doc["totals"]["deferred"] == 1

    del world.foundry.errors["sdlc-feasibility"]
    world.tick()
    assert state.FEASIBLE in world.gh.labels(n)
    assert json.loads(world.gh.files[("metrics", "metrics.json")])["issues"][0]["deferred"] is None


def test_new_issue_under_a_rate_limit_gets_no_comment_and_no_label(world: World) -> None:
    world.foundry.errors["sdlc-req-gate"] = rate_limited()
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    world.tick(3)
    assert world.gh.comments[n] == [] and world.gh.labels(n) == set()


def test_backoff_never_waits_past_the_tick_budget(world: World) -> None:
    world.foundry.fail_next["sdlc-req-gate"] = [rate_limited(retry_after=600)]
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    report = world.tick()[0]
    assert world.sleeps == [] and [o.result for o in report.objects if o.number == n] == ["deferred"]


@pytest.mark.parametrize("error", [
    AgentRunError("HTTP 503: service unavailable", transient=True),
    AgentRunError("request failed: APITimeoutError", transient=True),
    GitHubError(502, "POST /issues/1/comments: bad gateway"),
    GitHubError(429, "GET /issues: rate limited, retry after 900 s"),
    ConnectionResetError("connection reset by peer"),
])
def test_other_transient_errors_defer_without_counting(world: World, error: Exception) -> None:
    n = ready_issue(world)
    world.foundry.errors["sdlc-feasibility"] = error
    reports = world.tick(4)
    assert {o.result for r in reports for o in r.objects if o.number == n} == {"deferred"}
    assert world.gh.state_of(n)["failures"] is None


def test_coder_status_outage_defers_and_does_not_count(world: World) -> None:
    gh, foundry = world.gh, world.foundry
    world.coder.polls_to_finish = 10_000
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.BUILDING in gh.labels(n))
    foundry.hosted_fail_next = [AgentRunError("sdlc-coder: invocation returned HTTP 503", transient=True)] * 100
    reports = world.tick(8)
    assert {o.result for r in reports for o in r.objects if o.number == n} == {"deferred"}
    assert gh.state_of(n)["failures"] is None and state.BUILDING in gh.labels(n)


def test_invalid_output_gets_one_repair_retry_in_the_same_step(world: World) -> None:
    gh, foundry = world.gh, world.foundry
    foundry.script("sdlc-req-gate", '{"score": 100}')
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.tick()
    assert state.READY in gh.labels(n)
    calls = foundry.agent_calls("sdlc-req-gate")
    assert len(calls) == 2 and "## repair" in calls[1] and "missing keys" in calls[1]
    assert len(gh.state_of(n)["cost"]["calls"]) == 2      # both answers are billed


def test_three_steps_with_bad_output_escalate_agent_error_not_a_verdict(world: World) -> None:
    gh, foundry = world.gh, world.foundry
    n = ready_issue(world)
    foundry.defaults["sdlc-feasibility"] = "not json"
    world.tick(5)
    assert len(foundry.agent_calls("sdlc-feasibility")) == 6          # 3 steps x (answer + repair)
    labels = gh.labels(n)
    assert state.ESC_AGENT_ERROR in labels and state.ESC_NOT_SUITABLE not in labels
    assert "feasibility failed 3 times" in gh.state_of(n)["escalation"]["reasons"][0]


def test_a_refusal_counts_as_an_agent_failure(world: World) -> None:
    n = ready_issue(world)
    world.foundry.errors["sdlc-feasibility"] = AgentRunError("not completed: content_filter")
    world.tick(4)
    assert state.ESC_AGENT_ERROR in world.gh.labels(n)


def test_only_a_real_unsuitable_verdict_uses_the_not_suitable_label(world: World) -> None:
    world.foundry.script("sdlc-feasibility", {"suitable": False, "reasons": ["Needs production keys"],
                                              "risk": "high", "affected_paths": []})
    n = ready_issue(world)
    world.tick()
    assert state.ESC_NOT_SUITABLE in world.gh.labels(n)


def test_tick_report_logs_tokens_per_call(world: World) -> None:
    world.foundry.usage = (1466, 158)
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    report = world.tick()[0]
    assert report.calls == [{"number": n, "agent": "sdlc-req-gate", "in": 1466, "out": 158, "usd": 0.0006825}]


def test_transient_classification() -> None:
    from sdlc_agents.tick import is_transient

    assert is_transient(GitHubError(403, "GET /issues: rate limited, retry after 60 s"))
    assert not is_transient(GitHubError(403, "Resource not accessible by personal access token"))
    assert not is_transient(GitHubError(422, "Reference already exists"))
    assert is_transient(TimeoutError("read timed out"))
    assert not is_transient(ValueError("bad output"))
