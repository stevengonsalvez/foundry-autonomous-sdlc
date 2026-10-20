"""
The single-object seam a durable workflow uses: `run_tick(only=N, use_lock=False)` runs the existing
tick logic for one issue or maintenance PR, with no lock ref and nothing done to any other object;
`hold` stops before a human-gated step; `object_outcome` reads the step back as data.
"""

from __future__ import annotations

import json

from conftest import World
from fakes import NoSecrets
from test_scenarios import A_BODY, UNSUITABLE, open_scenario, open_stale_test_pr
from test_transient import rate_limited

from sdlc_agents import state
from sdlc_agents.lock import LOCK_BRANCH
from sdlc_agents.ports import OWNER
from sdlc_agents.tick import ObjectOutcome, TickReport, object_outcome, run_tick


def step(world: World, number: int, *, hold: frozenset[str] = frozenset()) -> TickReport:
    report = run_tick(world.gh, world.foundry, NoSecrets(), world.clock, 240, budget=world.budget,
                      sleep=world.sleep, only=number, use_lock=False, hold=hold)
    world.clock.advance(300)
    return report


def drive_one(world: World, number: int, done, *, hold: frozenset[str] = frozenset(),
              max_steps: int = 40) -> ObjectOutcome:
    """Step one object until `done(outcome)`; the loop a workflow would run."""
    for _ in range(max_steps):
        outcome = object_outcome(step(world, number, hold=hold), number, world.gh)
        if done(outcome):
            return outcome
    raise AssertionError(f"#{number} not done after {max_steps} steps")


def untouched(world: World, number: int) -> tuple:
    return sorted(world.gh.labels(number)), json.dumps([c.body for c in world.gh.comments.get(number, [])])


def new_issue(world: World, title: str = "Show the estimated delivery date") -> int:
    return world.gh.open_issue(title, A_BODY, labels=("type:feature",))


# -- only / use_lock ------------------------------------------------------------------------------

def test_only_advances_the_named_issue_and_leaves_the_others_untouched(world: World) -> None:
    a, b = new_issue(world), new_issue(world, "Filter parcels by status")
    stranger = world.gh.open_issue("Please add dark mode", A_BODY, author="someone-else")
    before_b, before_stranger = untouched(world, b), untouched(world, stranger)

    report = step(world, a)

    assert state.READY in world.gh.labels(a)
    assert untouched(world, b) == before_b
    assert untouched(world, stranger) == before_stranger
    assert {o.number for o in report.objects} == {a}


def test_use_lock_false_creates_no_lock_ref(world: World) -> None:
    created: list[str] = []
    create_branch = world.gh.create_branch

    def spy(branch: str, *, from_sha: str) -> None:
        created.append(branch)
        create_branch(branch, from_sha=from_sha)

    world.gh.create_branch = spy        # type: ignore[method-assign]
    a = new_issue(world)

    report = step(world, a)

    assert report.lock == "skipped"
    assert LOCK_BRANCH not in created and LOCK_BRANCH not in world.gh.branches
    assert state.READY in world.gh.labels(a)


def test_use_lock_false_ignores_a_lock_held_by_someone_else(world: World) -> None:
    world.gh.plant_lock(age_s=10)
    a = new_issue(world)

    report = step(world, a)

    assert report.lock == "skipped" and not report.errors
    assert state.READY in world.gh.labels(a)


def test_default_call_still_takes_the_lock_and_steps_every_object(world: World) -> None:
    a, b = new_issue(world), new_issue(world, "Filter parcels by status")

    report = world.tick()[0]

    assert report.lock == "acquired"
    assert {o.number for o in report.objects} == {a, b}
    assert state.READY in world.gh.labels(a) and state.READY in world.gh.labels(b)
    assert LOCK_BRANCH not in world.gh.branches        # released again


def test_only_keeps_the_deferral_streaks_of_other_objects(world: World) -> None:
    a, b = new_issue(world), new_issue(world, "Filter parcels by status")
    world.foundry.errors["sdlc-req-gate"] = rate_limited()
    world.tick()
    streaks = json.loads(world.gh.files[("metrics", "metrics.json")])["deferrals"]
    assert streaks == {str(a): 1, str(b): 1}
    del world.foundry.errors["sdlc-req-gate"]

    step(world, a)

    assert state.READY in world.gh.labels(a)
    assert json.loads(world.gh.files[("metrics", "metrics.json")])["deferrals"] == {str(b): 1}


# -- hold ---------------------------------------------------------------------------------------

def test_hold_merge_stops_before_merging_until_called_without_hold(world: World) -> None:
    gh = world.gh
    n = open_scenario(world, "a")
    merge = frozenset({"merge"})

    held = drive_one(world, n, lambda o: o.result == "held", hold=merge)

    assert held.action == "merge" and held.detail == "awaiting human approval: merge"
    assert held.stage == state.IN_REVIEW and not held.terminal
    pr = gh.state_of(n)["pr"]["number"]
    assert gh.issues[pr]["state"] == "open" and not gh.merges
    comments = json.dumps({k: [c.body for c in v] for k, v in gh.comments.items()})
    again = object_outcome(step(world, n, hold=merge), n, gh)
    assert again.result == "held" and not gh.merges
    assert json.dumps({k: [c.body for c in v] for k, v in gh.comments.items()}) == comments

    merged = object_outcome(step(world, n), n, gh)

    assert merged.action == "merge" and merged.result == "ok"
    assert gh.pulls[pr]["merged"] and len(gh.merges) == 1


def test_hold_design_tests_stops_at_the_spec_gate(world: World) -> None:
    n = open_scenario(world, "a")

    held = drive_one(world, n, lambda o: o.result == "held", hold=frozenset({"design-tests"}))

    assert held.action == "design-tests" and held.detail == "awaiting human approval: design-tests"
    assert held.stage == state.FEASIBLE
    assert not world.foundry.agent_calls("sdlc-test-designer")


# -- object_outcome -----------------------------------------------------------------------------

def test_an_issue_driven_alone_to_release_is_terminal(world: World) -> None:
    n = open_scenario(world, "a")

    done = drive_one(world, n, lambda o: o.terminal)

    assert done.stage == state.RELEASED and done.result == "ok"
    assert world.gh.issues[n]["state"] == "closed"
    assert world.gh.tags == ["v0.1.0"]


def test_a_maintenance_pr_driven_alone_is_released_not_stopped_at_merge(world: World) -> None:
    pr = open_stale_test_pr(world)
    seen: list[ObjectOutcome] = []

    done = drive_one(world, pr, lambda o: seen.append(o) or o.terminal)

    assert done.stage == state.RELEASED
    merged = [o for o in seen if o.stage == state.MERGED]
    assert merged and not any(o.terminal for o in merged)     # closed by the merge, still owes a release


def test_an_escalated_issue_is_terminal(world: World) -> None:
    world.foundry.script("sdlc-feasibility", UNSUITABLE)
    n = open_scenario(world, "c")

    done = drive_one(world, n, lambda o: o.terminal)

    assert state.ESC_NOT_SUITABLE in world.gh.labels(n)
    assert done.stage == state.READY and done.terminal


def test_a_deferred_transient_failure_is_not_terminal(world: World) -> None:
    world.foundry.errors["sdlc-req-gate"] = rate_limited()
    n = new_issue(world)

    outcome = object_outcome(step(world, n), n, world.gh)

    assert outcome.result == "deferred" and outcome.action == "gate"
    assert "rate_limit_exceeded" in outcome.detail
    assert not outcome.terminal and outcome.stage is None and outcome.wait_hint_s == 60


def test_wait_hint_is_short_while_the_coder_builds(world: World) -> None:
    n = open_scenario(world, "a")

    building = drive_one(world, n, lambda o: o.stage == state.BUILDING)

    assert building.wait_hint_s == 20 and not building.terminal


def test_a_non_owner_issue_is_ignored_and_terminal(world: World) -> None:
    n = world.gh.open_issue("Please add dark mode", A_BODY, author="someone-else")

    outcome = object_outcome(step(world, n), n, world.gh)

    assert outcome.result == "ignored" and outcome.terminal
    assert world.gh.labels(n) == set() and not world.gh.comments.get(n)


def test_a_closed_issue_the_tick_never_loads_is_terminal(world: World) -> None:
    n = new_issue(world)
    world.gh.close_issue(n)

    outcome = object_outcome(step(world, n), n, world.gh)

    assert outcome.result == "skipped" and outcome.terminal
    assert world.gh.issues[n]["author"] == OWNER
