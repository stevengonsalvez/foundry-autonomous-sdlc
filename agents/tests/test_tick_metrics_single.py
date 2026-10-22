"""
metrics.json under `run_tick(only=N)`: a single-object step merges its one fresh entry into the
published document. Every other entry, its spend and its gate counts stay as published; totals never
go down; a full tick (only=None) still rebuilds the whole document from every object it loads.
"""

from __future__ import annotations

import itertools
import json
from typing import Any

from conftest import World
from test_scenarios import open_scenario
from test_tick_single import new_issue, step

from sdlc_agents import state

METRICS = ("metrics", "metrics.json")


def published(world: World) -> dict[str, Any]:
    return json.loads(world.gh.files[METRICS])


def entry(doc: dict[str, Any], number: int) -> dict[str, Any]:
    return next(e for e in doc["issues"] if (e["pr"] if e["kind"] == "pr" else e["number"]) == number)


def numbers(doc: dict[str, Any]) -> list[int]:
    return [e["pr"] if e["kind"] == "pr" else e["number"] for e in doc["issues"]]


def test_a_single_object_step_keeps_every_other_entry_as_published(world: World) -> None:
    a, b = new_issue(world), new_issue(world, "Filter parcels by status")
    world.tick()
    before = published(world)

    step(world, a)

    after = published(world)
    assert numbers(after) == [a, b]
    assert entry(after, b) == entry(before, b)
    assert after["totals"]["issues"] == 2


def test_a_single_object_step_keeps_the_spend_of_objects_it_did_not_load(world: World) -> None:
    a, b = new_issue(world), new_issue(world, "Filter parcels by status")
    world.tick()
    b_usd = entry(published(world), b)["cost"]["usd"]
    assert b_usd > 0

    for _ in range(3):
        step(world, a)

    after = published(world)
    assert entry(after, b)["cost"]["usd"] == b_usd
    assert after["totals"]["usd"] >= entry(after, a)["cost"]["usd"] + b_usd


def test_totals_never_decrease_across_single_object_steps(world: World) -> None:
    a = open_scenario(world, "a")
    b = new_issue(world, "Filter parcels by status")
    world.tick()
    seen = [published(world)["totals"]]

    for _ in range(25):
        step(world, a)
        seen.append(published(world)["totals"])
        if state.RELEASED in world.gh.labels(a):
            break

    assert state.RELEASED in world.gh.labels(a)
    for older, newer in itertools.pairwise(seen):
        for key in ("usd", "issues", "released", "orchestrator_usd"):
            assert newer[key] >= older[key], (key, older, newer)
    assert seen[-1]["issues"] == 2 and seen[-1]["released"] == 1
    assert entry(published(world), b)["outcome"] == "open"


def test_a_step_of_another_object_keeps_the_gate_counts_already_published(world: World) -> None:
    a = open_scenario(world, "a")
    for _ in range(25):
        step(world, a)
        if state.RELEASED in world.gh.labels(a):
            break
    rates = published(world)["gate_pass_rates"]
    assert sum(r["pass"] for r in rates.values()) > 0
    b = new_issue(world, "Filter parcels by status")

    step(world, b)

    after = published(world)
    assert after["gate_pass_rates"] == rates
    assert numbers(after) == [a, b]


def test_single_object_gate_counts_match_what_a_full_tick_recomputes(world: World) -> None:
    a = open_scenario(world, "a")
    b = new_issue(world, "Filter parcels by status")
    world.tick()
    for _ in range(25):
        step(world, a)
        if state.RELEASED in world.gh.labels(a):
            break
    merged = published(world)

    world.tick()          # rebuilds every entry and every gate count from the state comments

    full = published(world)
    assert full["gate_pass_rates"] == merged["gate_pass_rates"]
    assert entry(full, a) == entry(merged, a)
    assert numbers(full) == numbers(merged) == [a, b]


def test_a_step_of_an_object_the_tick_never_loads_changes_no_entry(world: World) -> None:
    a, b = new_issue(world), new_issue(world, "Filter parcels by status")
    world.tick()
    before = published(world)
    closed = new_issue(world, "Old idea")
    world.gh.close_issue(closed)

    step(world, closed)

    after = published(world)
    assert after["issues"] == before["issues"]
    assert after["gate_pass_rates"] == before["gate_pass_rates"]
    assert after["totals"]["usd"] >= before["totals"]["usd"]
    assert numbers(after) == [a, b]


def test_a_quiet_step_writes_no_per_issue_change_and_dispatches_no_pages_build(world: World) -> None:
    n = open_scenario(world, "a")
    other = new_issue(world, "Filter parcels by status")
    world.tick()
    for _ in range(25):
        step(world, n)
        if state.RELEASED in world.gh.labels(n):
            break
    step(world, n)
    before = published(world)
    dispatched = len(world.gh.dispatches)

    report = step(world, n)

    assert report.objects[0].action == "noop"
    after = published(world)
    assert {k: v for k, v in after.items() if k not in ("generated_at", "totals", "ledger")} == \
        {k: v for k, v in before.items() if k not in ("generated_at", "totals", "ledger")}
    assert len(world.gh.dispatches) == dispatched
    assert numbers(after) == [n, other]


def test_a_malformed_published_entry_is_dropped_and_the_step_still_publishes(world: World) -> None:
    a, b = new_issue(world), new_issue(world, "Filter parcels by status")
    world.tick()
    doc = published(world)
    entry(doc, b).pop("title")
    doc["gate_pass_rates"]["test"]["pass"] = "lots"
    world.gh.files[METRICS] = json.dumps(doc)

    report = step(world, a)

    assert not report.errors
    after = published(world)
    assert numbers(after) == [a]
    assert after["totals"]["usd"] >= doc["totals"]["usd"]
    assert after["gate_pass_rates"]["test"]["pass"] == 0
