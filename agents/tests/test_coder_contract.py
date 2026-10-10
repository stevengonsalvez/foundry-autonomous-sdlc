"""
Cross-check: every coder start payload the orchestrator builds is accepted by the coder's own
JobSpec, in all four modes. The payloads come from real ticks, not hand-written fixtures, so the
orchestrator and the coder runtime cannot drift apart unnoticed.
"""

from __future__ import annotations

import re
from typing import Any

from conftest import World
from test_scenarios import open_scenario, open_stale_test_pr

from sdlc_agents import state
from sdlc_agents.coder.job import JobSpec


def start_jobs(world: World) -> list[dict[str, Any]]:
    return [body["job"] for _, body, _ in world.foundry.hosted if body["op"] == "start"]


def request_changes_once(world: World) -> None:
    world.foundry.script("sdlc-reviewer", lambda text: {
        "verdict": "request-changes", "head": re.search(r"head sha: (\w+)", text).group(1),
        "findings": [{"severity": "high", "area": "spec", "detail": "Criterion 4 is not covered."}],
        "summary": "One criterion missing."})


def test_feature_and_revise_jobs_validate_against_the_coder_jobspec(world: World) -> None:
    request_changes_once(world)
    n = open_scenario(world, "a")
    world.drive(lambda: state.RELEASED in world.gh.labels(n))
    jobs = start_jobs(world)
    assert [j["mode"] for j in jobs] == ["feature", "revise"]
    for job in jobs:
        spec = JobSpec.from_request(job)
        assert spec.job_id == job["job_id"] and spec.mode == job["mode"]


def test_bugfix_job_validates_against_the_coder_jobspec(world: World) -> None:
    n = open_scenario(world, "d")
    world.drive(lambda: state.RELEASED in world.gh.labels(n))
    (job,) = start_jobs(world)
    assert job["mode"] == "bugfix"
    assert JobSpec.from_request(job).mode == "bugfix"


def test_maintenance_job_on_a_non_agent_branch_validates_against_the_coder_jobspec(world: World) -> None:
    pr = open_stale_test_pr(world)
    world.drive(lambda: state.RELEASED in world.gh.labels(pr))
    (job,) = start_jobs(world)
    assert job["mode"] == "maintenance" and job["branch"] == "chore/update-home-heading"
    assert JobSpec.from_request(job).mode == "maintenance"


def test_rebuild_after_a_test_repair_validates_against_the_coder_jobspec(world: World) -> None:
    world.coder.outcomes = ["failed:tests-invalid"]
    n = open_scenario(world, "a")
    world.drive(lambda: state.RELEASED in world.gh.labels(n))
    jobs = start_jobs(world)
    assert [j["branch"] for j in jobs] == [f"agent/issue-{n}", f"agent/issue-{n}-r1"]
    for job in jobs:
        assert JobSpec.from_request(job).mode == "feature"
