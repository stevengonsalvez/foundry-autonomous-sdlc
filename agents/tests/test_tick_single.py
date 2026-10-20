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


# -- meter: a surrogate price for the step's engine calls -------------------------------------------

def metered_step(world: World, number: int, usd_per_call: float) -> TickReport:
    """One step whose engine calls are priced by a meter, as run_step prices CliFoundry's calls."""
    start = len(world.foundry.calls)
    report = run_tick(world.gh, world.foundry, NoSecrets(), world.clock, 240, budget=world.budget,
                      sleep=world.sleep, only=number, use_lock=False,
                      meter=lambda: usd_per_call * (len(world.foundry.calls) - start))
    world.clock.advance(300)
    return report


def test_a_meter_prices_the_steps_calls_instead_of_their_tokens(world: World) -> None:
    n = new_issue(world)

    metered_step(world, n, 0.05)

    calls = len(world.foundry.calls)
    cost = world.gh.state_of(n)["cost"]
    assert calls >= 1
    assert cost["usd"] == round(0.05 * calls, 6)          # no token price on top: not counted twice
    assert all(c["in"] and c["out"] for c in cost["calls"])  # the tokens are still on record


def test_a_meter_that_pushes_an_issue_over_its_cap_escalates_cost_cap(world: World) -> None:
    n = open_scenario(world, "a")

    for _ in range(10):
        metered_step(world, n, 1.6)
        if state.ESC_COST_CAP in world.gh.labels(n):
            break

    assert state.ESC_COST_CAP in world.gh.labels(n)
    assert world.gh.state_of(n)["cost"]["usd"] >= 3.0
    assert len(world.foundry.calls) <= 3                  # stopped at the cap, not after it


def test_a_meter_under_the_cap_does_not_escalate(world: World) -> None:
    n = open_scenario(world, "a")

    for _ in range(40):
        metered_step(world, n, 0.01)
        if state.RELEASED in world.gh.labels(n):
            break

    assert state.RELEASED in world.gh.labels(n)
    assert not any(label.startswith("escalated:") for label in world.gh.labels(n))
    assert world.gh.state_of(n)["cost"]["usd"] > 0


def test_a_meter_charges_engine_calls_that_returned_nothing(world: World) -> None:
    n = new_issue(world)
    metered_step(world, n, 0.05)
    spent = world.gh.state_of(n)["cost"]["usd"]
    world.foundry.errors["sdlc-feasibility"] = rate_limited()

    outcome = object_outcome(metered_step(world, n, 0.05), n, world.gh)

    assert outcome.result == "deferred"
    failed = len(world.foundry.agent_calls("sdlc-feasibility"))
    assert failed >= 1
    assert world.gh.state_of(n)["cost"]["usd"] == round(spent + 0.05 * failed, 6)


def test_a_meter_charge_counts_in_the_published_totals(world: World) -> None:
    n = new_issue(world)

    report = metered_step(world, n, 0.5)

    doc = json.loads(world.gh.files[("metrics", "metrics.json")])
    calls = len(world.foundry.calls)
    assert report.usd_this_tick == round(0.5 * calls, 8)
    assert doc["totals"]["usd"] >= 0.5 * calls


def test_without_a_meter_the_tokens_are_the_price(world: World) -> None:
    n = new_issue(world)

    step(world, n)

    cost = world.gh.state_of(n)["cost"]
    tokens_in, tokens_out = world.foundry.usage
    assert cost["usd"] == round(len(world.foundry.calls) * (tokens_in * 0.25 + tokens_out * 2.00) / 1e6, 6)


def test_a_new_issue_whose_metered_calls_all_fail_keeps_their_spend_against_its_cap(world: World) -> None:
    world.foundry.errors["sdlc-req-gate"] = rate_limited()
    n = new_issue(world)

    outcome = object_outcome(metered_step(world, n, 0.05), n, world.gh)

    assert outcome.result == "deferred"
    calls = len(world.foundry.agent_calls("sdlc-req-gate"))
    assert calls >= 1
    assert world.gh.state_of(n)["cost"]["usd"] == round(0.05 * calls, 6)   # on the issue, not totals only
    assert not any(label.startswith("stage:") for label in world.gh.labels(n))


def test_unbilled_meter_growth_counts_against_the_cap_before_a_retry(world: World) -> None:
    n = new_issue(world)
    metered_step(world, n, 1.6)
    world.foundry.errors["sdlc-feasibility"] = rate_limited()

    report = metered_step(world, n, 1.6)

    assert len(world.foundry.agent_calls("sdlc-feasibility")) == 1      # 1.6 + 1.6 is past the cap: no retry
    assert report.objects[0].result == "capped"
    assert report.model_calls == 0                 # an unanswered charge is spend, not a model call
