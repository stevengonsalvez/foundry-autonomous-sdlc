"""
A merge GitHub refuses with 405 'Pull Request has merge conflicts' can never succeed by retrying (live
run: PR #101 for issue 96 failed three times after #95 landed on the same files and was escalated
build-failed). The ticket goes back into a revise round instead: the coder merges origin/main into the
agent branch keeping both intents, tests and gates run on the new head, it is reviewed again, then merged.
At most MAX_MERGE_CONFLICT_ROUNDS rounds, then escalated:merge-conflict.
"""

from __future__ import annotations

from conftest import World
from test_core import GREEN, HEAD, ctx, make_state, pull
from test_scenarios import A_BODY

from sdlc_agents import machine, state
from sdlc_agents.machine import Kind


def jobs(world: World) -> list[dict]:
    return [body["job"] for _, body, _ in world.foundry.hosted if body["op"] == "start"]


def test_escalation_label_is_known() -> None:
    assert state.ESC_MERGE_CONFLICT == "escalated:merge-conflict"
    assert state.ESC_MERGE_CONFLICT in state.ESCALATIONS
    assert machine.MAX_MERGE_CONFLICT_ROUNDS == 2


def test_machine_restarts_the_coder_for_a_recorded_conflict_on_this_head() -> None:
    st = make_state(state.IN_REVIEW)
    st.data["review"] = {"verdict": "approve", "head": HEAD, "rounds": 0}
    st.data["merge_conflict"] = {"rounds": 1, "head": HEAD}
    action = machine.next_action(ctx(st, pr=pull(), checks=GREEN))
    assert action.kind is Kind.START_CODER and action.mode == "revise"


def test_machine_merges_again_once_the_conflict_record_is_for_an_older_head() -> None:
    st = make_state(state.IN_REVIEW)
    st.data["review"] = {"verdict": "approve", "head": HEAD, "rounds": 0}
    st.data["merge_conflict"] = {"rounds": 1, "head": "c" * 40}
    assert machine.next_action(ctx(st, pr=pull(), checks=GREEN)).kind is Kind.MERGE


def test_a_conflict_is_not_counted_as_a_failed_step(world: World) -> None:
    gh = world.gh
    gh.merge_conflict = True
    n = gh.open_issue("Show the estimated delivery date", A_BODY)
    world.drive(lambda: gh.state_of(n).get("merge_conflict") is not None)
    st = gh.state_of(n)
    assert gh.calls.count("merge_pull") == 1
    assert st["failures"] is None and st["escalation"] is None
    assert st["stages"][-1]["stage"] == state.IN_REVIEW
    assert st["merge_conflict"]["rounds"] == 1


def test_conflict_sends_the_coder_to_merge_main_then_the_new_head_is_reviewed_and_merged(world: World) -> None:
    gh = world.gh
    gh.merge_conflict = True
    n = gh.open_issue("Show the estimated delivery date", A_BODY)

    world.drive(lambda: state.RELEASED in gh.labels(n))

    started = jobs(world)
    assert [j["mode"] for j in started] == ["feature", "revise"]
    revise = started[1]
    assert revise["merge_main"] is True and "merge conflicts" in revise["spec"]["notes"]
    assert "both" in revise["spec"]["notes"].lower()
    assert "merge_main" not in started[0]
    assert gh.calls.count("merge_pull") == 2 and len(gh.merges) == 1
    assert len(world.foundry.agent_calls("sdlc-reviewer")) == 2        # the merged head is reviewed again
    st = gh.state_of(n)
    assert st["merge_conflict"]["rounds"] == 1 and st["escalation"] is None
    assert gh.merges[0][1] == st["pr"]["head"] != st["merge_conflict"]["head"]


def test_a_conflict_that_survives_two_rounds_escalates_merge_conflict(world: World) -> None:
    gh = world.gh
    gh.merge_conflict = True
    world.coder.resolve_conflicts = False       # the coder's new heads still conflict
    n = gh.open_issue("Show the estimated delivery date", A_BODY)

    world.drive(lambda: state.ESC_MERGE_CONFLICT in gh.labels(n), max_ticks=60)

    assert [j["mode"] for j in jobs(world)] == ["feature", "revise", "revise"]
    assert gh.calls.count("merge_pull") == 3 and gh.merges == []
    esc = gh.state_of(n)["escalation"]
    assert esc["label"] == state.ESC_MERGE_CONFLICT
    assert "after 2 merge conflict rounds" in esc["reasons"][0]
    assert state.ESC_BUILD_FAILED not in gh.labels(n)


def test_a_coder_that_fails_the_merge_job_escalates_merge_conflict_not_build_failed(world: World) -> None:
    gh = world.gh
    gh.merge_conflict = True
    world.coder.outcomes = ["succeeded", "failed:unresolved-conflicts"]     # the feature job, then the merge job
    n = gh.open_issue("Show the estimated delivery date", A_BODY)

    world.drive(lambda: state.ESC_MERGE_CONFLICT in gh.labels(n), max_ticks=40)

    assert [j["mode"] for j in jobs(world)] == ["feature", "revise"]
    assert gh.merges == [] and state.ESC_BUILD_FAILED not in gh.labels(n)
    assert gh.state_of(n)["escalation"]["label"] == state.ESC_MERGE_CONFLICT

