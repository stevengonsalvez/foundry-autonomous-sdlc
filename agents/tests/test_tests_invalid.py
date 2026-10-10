"""
Invalid designed tests are repaired, not escalated as a build failure:
- the orchestrator lints the designer's tests and re-asks once before the coder sees them;
- a coder `failed` / `tests-invalid` sends the error lines back to the test designer (up to two
  repair rounds within the cost cap), then a new coder job runs on a fresh branch, so the final PR
  starts with exactly one test commit; after two failed repairs the issue is `escalated:agent-error`.
"""

from __future__ import annotations

from conftest import World
from test_scenarios import A_BODY

from sdlc_agents import state
from sdlc_agents.definitions import AGENT_BY_NAME

NO_EXPECT_IMPORT = {"tests": [{"path": "app/web/tests/estimated-delivery.test.tsx",
                               "content": 'import { describe, it } from "vitest";\n'
                                          'describe("x", () => { it("y", () => { expect(1).toBe(2); }); });\n'}],
                    "rationale": "r"}
INVALID = "failed:tests-invalid"


def start_jobs(world: World) -> list[dict]:
    return [body["job"] for _, body, _ in world.foundry.hosted if body["op"] == "start"]


def test_designer_output_that_fails_the_lint_is_re_asked_once_with_the_errors(world: World) -> None:
    world.foundry.script("sdlc-test-designer", NO_EXPECT_IMPORT)
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.TESTS_WRITTEN in world.gh.labels(n))
    calls = world.foundry.agent_calls("sdlc-test-designer")
    assert len(calls) == 2
    assert "uses expect without importing it from vitest" in calls[1].split("name=repair_reason>", 1)[1]


def test_designer_that_keeps_failing_the_lint_counts_as_an_agent_failure(world: World) -> None:
    world.foundry.defaults["sdlc-test-designer"] = NO_EXPECT_IMPORT
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.ESC_AGENT_ERROR in world.gh.labels(n))
    assert not world.foundry.hosted


def test_coder_tests_invalid_is_repaired_and_rebuilt_on_a_fresh_branch(world: World) -> None:
    gh, foundry = world.gh, world.foundry
    world.coder.outcomes = [INVALID]
    world.coder.invalid_detail = "app/web/tests/issue-1.test.tsx: ReferenceError: expect is not defined"
    n = gh.open_issue("Show the estimated delivery date", A_BODY)

    world.drive(lambda: state.RELEASED in gh.labels(n))

    jobs = start_jobs(world)
    assert [(j["job_id"], j["branch"]) for j in jobs] == [(f"j-{n}-1", f"agent/issue-{n}"),
                                                          (f"j-{n}-2", f"agent/issue-{n}-r1")]
    repair_input = foundry.agent_calls("sdlc-test-designer")[1]
    assert "ReferenceError: expect is not defined" in repair_input.split("name=repair_reason>", 1)[1]
    assert "name=previous_tests>" in repair_input
    st = gh.state_of(n)
    assert st["tests_repair"]["rounds"] == 1 and st["pr"]["branch"] == f"agent/issue-{n}-r1"
    assert [s["stage"] for s in st["stages"]] == [
        state.READY, state.FEASIBLE, state.TESTS_WRITTEN, state.BUILDING, state.FEASIBLE, state.TESTS_WRITTEN,
        state.BUILDING, state.IN_REVIEW, state.MERGED, state.RELEASED]
    messages = [gh.commits[sha]["message"] for sha in gh.pr_commits(st["pr"]["number"])]
    assert [m for m in messages if m.startswith("test:")] == [messages[0]]
    assert f"agent/issue-{n}" not in gh.branches                      # the abandoned branch is removed
    assert not [b for b in gh.bodies(n) if b.startswith("<!-- sdlc-escalation")]


def test_two_failed_repairs_escalate_agent_error(world: World) -> None:
    gh = world.gh
    world.coder.outcomes = [INVALID, INVALID, INVALID]
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.ESC_AGENT_ERROR in gh.labels(n))
    assert len(start_jobs(world)) == 3 and len(world.foundry.agent_calls("sdlc-test-designer")) == 3
    st = gh.state_of(n)
    assert "tests still invalid after 2 repairs" in st["escalation"]["reasons"][0]
    assert state.ESC_BUILD_FAILED not in gh.labels(n) and gh.merges == []


def test_repairs_stay_within_the_issue_cap(world: World) -> None:
    from sdlc_agents.ports import Budget

    world.coder.outcomes = [INVALID]
    n = world.gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: state.FEASIBLE in world.gh.labels(n) and world.gh.state_of(n).get("tests_repair"))
    world.tick(budget=Budget(usd_cap_issue=0.001))
    assert state.ESC_COST_CAP in world.gh.labels(n)
    assert len(world.foundry.agent_calls("sdlc-test-designer")) == 1


def test_designer_prompt_states_the_vitest_and_helper_rules() -> None:
    text = AGENT_BY_NAME["sdlc-test-designer"].instructions
    for rule in ('import { describe, expect, it } from "vitest"', "globals are NOT enabled", "findBy",
                 "exact exported names", "@parcel/core", "fail on an ASSERTION", "app/<workspace>/tests/"):
        assert rule in text, rule
