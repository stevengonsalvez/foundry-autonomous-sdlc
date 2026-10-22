"""
The four demo scenarios (a, d, b+c, d-maintenance) driven through the REAL Temporal workflows on the
time-skipping test server, with the activities bound to the agents test fakes (decision D9).

    PollWorkflow ──▶ list_work ──▶ WorkItemWorkflow(issue-N | pr-N) ──▶ run_step ... terminal

Each test proves discovery (one poll starts exactly the expected child workflow), waits for the child to
finish, then asserts the same end state as the matching test in agents/tests/test_scenarios.py, plus
the workflow-only properties: the lock ref is never created and the issue stays under its cost cap.
"""

from __future__ import annotations

import concurrent.futures
import json
from collections.abc import Callable

from conftest import World
from sdlc_agents import state
from sdlc_agents.gates import REQUIRED_CHECKS
from sdlc_agents.ledger.emitter import InlineEmitter
from sdlc_agents.ledger.service import Ledger
from sdlc_agents.ledger.store import STATE_FILE, MemoryBranchStore
from sdlc_agents.lock import LOCK_BRANCH
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from test_scenarios import (
    ISSUE_FLOW,
    LOW_SCORE,
    REFINED_SCORE,
    UNSUITABLE,
    metrics_doc,
    open_scenario,
    open_stale_test_pr,
    snapshot,
    stages,
    state_comments,
)

from sdlc_factory.activities import StepInput, StepOutput, build_activities
from sdlc_factory.deps import FactoryDeps
from sdlc_factory.workflows import TASK_QUEUE, PollInput, PollWorkflow, WorkItemWorkflow
from tests.test_activities import fake_deps, spaced

Around = Callable[[Callable[[StepInput], StepOutput], StepInput], StepOutput]
REPO_URL = "https://github.com/stevengonsalvez/foundry-autonomous-sdlc"


def factory_worker(env: WorkflowEnvironment, world: World, *, around: Around | None = None) -> tuple[Worker,
                                                                                                    FactoryDeps]:
    """The foreman worker over the world's fakes: one activity slot, as in production (D6)."""
    deps = fake_deps(world)
    activities = spaced(world, build_activities(deps), around=around)
    worker = Worker(env.client, task_queue=TASK_QUEUE, workflows=[WorkItemWorkflow, PollWorkflow],
                    activities=activities, activity_executor=concurrent.futures.ThreadPoolExecutor(2),
                    max_concurrent_activities=1)
    return worker, deps


async def poll_once(env: WorkflowEnvironment, expected: str, *, gate_merge: bool = False,
                    poll_id: str = "poll-1") -> WorkflowHandle:
    """One PollWorkflow run; it must discover and start exactly `expected`, whose handle is returned."""
    result = await env.client.execute_workflow(PollWorkflow.run, PollInput(gate_spec=False, gate_merge=gate_merge),
                                               id=poll_id, task_queue=TASK_QUEUE)
    assert result == {"listed": 1, "started": 1, "running": 0}
    handle = env.client.get_workflow_handle(expected)
    assert (await handle.describe()).status.name in ("RUNNING", "COMPLETED")
    return handle


async def finished(env: WorkflowEnvironment, handle: WorkflowHandle) -> dict:
    """The result of a child the poll started. Only handles returned by start_workflow unlock time
    skipping while their result is awaited; a handle looked up by id needs the unlock done here."""
    async with env.time_skipping_unlocked():  # type: ignore[attr-defined]
        return await handle.result()


async def status_when(env: WorkflowEnvironment, handle: WorkflowHandle, done: Callable[[dict], bool],
                      *, max_polls: int = 400) -> dict:
    """Skip workflow time until the status query satisfies `done`."""
    status: dict = {}
    for _ in range(max_polls):
        status = await handle.query(WorkItemWorkflow.status)
        if done(status):
            return status
        await env.sleep(30)
    raise AssertionError(f"status never matched; last: {status}")


def assert_settled_without_lock_and_under_cap(world: World, deps: FactoryDeps, number: int,
                                              created_branches: list[str]) -> None:
    assert LOCK_BRANCH not in created_branches and LOCK_BRANCH not in world.gh.branches
    cost = world.gh.state_of(number)["cost"]["usd"]
    assert 0 < cost < deps.budget.usd_cap_issue


# -- scenario a: well-formed feature, built and released ------------------------------------------

def assert_scenario_a(world: World, n: int) -> None:
    """agents/tests/test_scenarios.py::test_scenario_a_well_formed_feature_is_built_reviewed_merged_and_released"""
    gh = world.gh
    st = gh.state_of(n)
    assert stages(world, n) == ISSUE_FLOW
    assert st["scenario"] == "a"
    assert st["quality"]["score"] == 90 and st["quality"]["rounds"] == 0
    assert gh.issues[n]["state"] == "closed"
    assert gh.labels(n) >= {"stage:released", "type:feature"}
    assert not [label for label in gh.labels(n) if label.startswith("stage:") and label != "stage:released"]
    assert state_comments(world, n) == 1

    start = next(body for _, body, _ in world.foundry.hosted if body["op"] == "start")
    job = start["job"]
    assert job["mode"] == "feature" and job["branch"] == f"agent/issue-{n}" and job["allowed_paths"] == ["app/"]
    assert job["tests"][0]["path"] == f"app/web/tests/issue-{n}.test.tsx"
    assert job["repo"] == "stevengonsalvez/foundry-autonomous-sdlc" and job["deadline_s"] == 7_200
    assert job["workdir"] == "app" and job["test_cmd"] == "npm test" and 0 < job["max_model_usd"] <= 0.5
    pr = st["pr"]["number"]
    messages = [gh.commits[sha]["message"] for sha in gh.pr_commits(pr)]
    assert messages[0].startswith("test:") and messages[1].startswith("feat:")

    head = st["pr"]["head"]
    assert any(body.startswith(f'<!-- sdlc-review:v1 {{"verdict":"approve","head":"{head}"}} -->')
               for body in gh.bodies(pr))
    assert gh.merges == [(pr, head, "merge")] and gh.pulls[pr]["merged"]
    assert gh.tags == ["v0.1.0"]
    assert gh.releases[0]["target"] == st["pr"]["merge_sha"]
    assert "Pull request #" in gh.releases[0]["body"]
    assert st["release"] == {"tag": "v0.1.0", "pending": False, "url": f"{REPO_URL}/releases/tag/v0.1.0"}
    assert st["gates"] == dict.fromkeys(REQUIRED_CHECKS, "success")

    doc = metrics_doc(world)
    entry = doc["issues"][0]
    assert entry["outcome"] == "released" and entry["scenario"] == "a" and entry["release"] == "v0.1.0"
    assert entry["coder_engine"] == "agy" and entry["cost"]["calls"] == 5
    assert doc["totals"]["released"] == 1
    assert doc["gate_pass_rates"]["tdd-order"] == {"pass": 1, "fail": 0, "first_pass": 1, "first_fail": 0}
    assert ("pages.yml", "main") in gh.dispatches


async def test_scenario_a_poll_discovers_the_feature_and_the_workflow_releases_it(
        env: WorkflowEnvironment, world: World, created_branches: list[str]) -> None:
    n = open_scenario(world, "a")
    worker, deps = factory_worker(env, world)
    async with worker:
        handle = await poll_once(env, f"issue-{n}")
        summary = await finished(env, handle)

    assert summary["terminal"] and summary["reason"] == "settled" and summary["stage"] == state.RELEASED
    assert summary["holds"] == 0
    assert_scenario_a(world, n)
    assert f"agent/issue-{n}" in created_branches      # the recorder sees every branch the run creates
    assert_settled_without_lock_and_under_cap(world, deps, n, created_branches)


async def test_scenario_a_with_gate_merge_waits_for_the_human_then_merges_and_releases(
        env: WorkflowEnvironment, world: World, created_branches: list[str]) -> None:
    gh = world.gh
    n = open_scenario(world, "a")
    worker, deps = factory_worker(env, world)
    async with worker:
        handle = await poll_once(env, f"issue-{n}", gate_merge=True)
        held = await status_when(env, handle, lambda s: s["waiting_for"] == "merge")
        await env.sleep(2 * 24 * 3600)          # days pass and nobody approves
        still = await handle.query(WorkItemWorkflow.status)
        pr = gh.state_of(n)["pr"]["number"]

        assert held["gates"] == ["merge"] and still["waiting_for"] == "merge" and still["steps"] == held["steps"]
        assert not gh.pulls[pr]["merged"] and gh.merges == [] and gh.tags == []
        assert state.IN_REVIEW in gh.labels(n) and gh.issues[n]["state"] == "open"

        await handle.signal(WorkItemWorkflow.human_approved, "merge")
        summary = await finished(env, handle)

    assert summary["terminal"] and summary["stage"] == state.RELEASED and summary["holds"] >= 1
    assert_scenario_a(world, n)
    assert_settled_without_lock_and_under_cap(world, deps, n, created_branches)


async def test_scenario_a_state_keeper_folds_the_released_ticket_to_prod(
        env: WorkflowEnvironment, world: World) -> None:
    store = MemoryBranchStore()
    world.emitter = InlineEmitter(Ledger(store, world.clock, github=world.gh, mode="inline"))
    n = open_scenario(world, "a")
    worker, _ = factory_worker(env, world)
    async with worker:
        summary = await finished(env, await poll_once(env, f"issue-{n}"))

    assert summary["stage"] == state.RELEASED
    board = json.loads(store.files[STATE_FILE])
    ticket = next(t for t in board["tickets"] if t["issue"] == n)
    # no CD record in this world: a merged and released change counts as published straight to prod
    assert ticket["stage"] == "prod"
    assert [h["stage"] for h in ticket["stage_history"]][:7] == [
        "backlog", "refining", "feasible", "tests", "building", "review", "staging"]
    assert ticket["release"]["tag"] == "v0.1.0"
    assert ticket["cost"]["usd"] == world.gh.state_of(n)["cost"]["usd"] and ticket["cost"]["calls"] == 5
    assert board["ledger"]["last_tick"]["lock"] == "skipped"


# -- scenario d: bug triaged, regression test first, fixed ------------------------------------------

async def test_scenario_d_bug_is_triaged_then_fixed_with_the_regression_test_first(
        env: WorkflowEnvironment, world: World, created_branches: list[str]) -> None:
    gh, foundry = world.gh, world.foundry
    after_first_step: list[set[str]] = []

    def watch_first(original, inp):
        out = original(inp)
        if not after_first_step:
            after_first_step.append(set(gh.labels(inp.number)))
        return out

    n = open_scenario(world, "d")
    worker, deps = factory_worker(env, world, around=watch_first)
    async with worker:
        summary = await finished(env, await poll_once(env, f"issue-{n}"))

    assert summary["terminal"] and summary["stage"] == state.RELEASED
    # triage is the first step and the first agent call
    assert after_first_step[0] >= {"bug:triaged", "severity:s3", "owner:api", "type:bug"}
    assert foundry.calls[0][0] == "sdlc-triage"
    triage = next(b for b in gh.bodies(n) if b.startswith("<!-- sdlc-triage:v1 -->"))
    assert "severity `s3`, owner `api`" in triage

    st = gh.state_of(n)
    assert stages(world, n) == ISSUE_FLOW
    assert "name=mode>" not in foundry.agent_calls("sdlc-test-designer")[0]
    assert "## mode\nbugfix" in foundry.agent_calls("sdlc-test-designer")[0]
    job = next(body["job"] for _, body, _ in foundry.hosted if body["op"] == "start")
    assert job["mode"] == "bugfix"
    # tdd order: the regression test commit lands before the fix
    messages = [gh.commits[sha]["message"] for sha in gh.pr_commits(st["pr"]["number"])]
    assert messages[0].startswith("test:") and messages[1].startswith("fix:")
    entry = metrics_doc(world)["issues"][0]
    assert entry["severity"] == "s3" and entry["owner"] == "api" and entry["scenario"] == "d"
    assert entry["resolution_seconds"] > 0
    assert metrics_doc(world)["gate_pass_rates"]["tdd-order"]["pass"] == 1
    assert gh.labels(n) >= {"bug:triaged", "severity:s3", "owner:api", "stage:released"}
    assert_settled_without_lock_and_under_cap(world, deps, n, created_branches)


# -- scenario b: vague requirement refined by the simulated product owner, then built ----------------

async def test_scenario_b_vague_requirement_is_refined_by_the_product_owner_then_built(
        env: WorkflowEnvironment, world: World, created_branches: list[str]) -> None:
    gh, foundry = world.gh, world.foundry
    foundry.script("sdlc-req-gate", LOW_SCORE, REFINED_SCORE)
    n = open_scenario(world, "b")
    worker, deps = factory_worker(env, world)
    async with worker:
        summary = await finished(env, await poll_once(env, f"issue-{n}"))

    assert summary["terminal"] and summary["stage"] == state.RELEASED
    st = gh.state_of(n)
    assert stages(world, n) == [state.NEEDS_REFINEMENT, *ISSUE_FLOW]
    assert st["type"] == "feature" and "type:feature" in gh.labels(n)
    quality = st["quality"]
    assert quality["score"] == 85 >= 80 and quality["rounds"] == 1
    assert quality["history"][0]["score"] == 5
    assert quality["history"][0]["questions"] == LOW_SCORE["questions"]

    questions = next(b for b in gh.bodies(n) if b.startswith("<!-- sdlc-questions:v1 round=1 -->"))
    assert "5 / 100" in questions and "1. Which user task is hardest today?" in questions
    po = next(b for b in gh.bodies(n) if b.startswith("<!-- sdlc-po:v1 round=1 -->"))
    visible = po.split("\n", 1)[1]
    assert visible.startswith("[Simulated product owner]")
    assert [line for line in visible.splitlines() if line and not line.startswith(("**Q", "["))] == []
    assert all(a.startswith("[Simulated product owner]") for a in quality["history"][0]["answers"])

    rescore_input = foundry.agent_calls("sdlc-req-gate")[1]
    assert "name=clarifications>" in rescore_input and "[Simulated product owner]" in rescore_input
    assert metrics_doc(world)["issues"][0]["scenario"] == "b"
    assert gh.issues[n]["state"] == "closed" and gh.tags == ["v0.1.0"]
    assert_settled_without_lock_and_under_cap(world, deps, n, created_branches)


# -- scenario c: not suitable for an agent -------------------------------------------------------

async def test_scenario_c_unsuitable_request_is_escalated_terminal_and_never_built(
        env: WorkflowEnvironment, world: World, created_branches: list[str]) -> None:
    gh, foundry = world.gh, world.foundry
    foundry.script("sdlc-feasibility", UNSUITABLE)
    n = open_scenario(world, "c")
    main_before, commits_before = gh.branches["main"], set(gh.commits)
    worker, deps = factory_worker(env, world)
    async with worker:
        summary = await finished(env, await poll_once(env, f"issue-{n}"))
        before = snapshot(world)
        # the escalated issue is no longer work: a later poll starts nothing and nothing changes
        again = await env.client.execute_workflow(PollWorkflow.run, PollInput(gate_spec=False, gate_merge=False),
                                                  id="poll-2", task_queue=TASK_QUEUE)

    assert again == {"listed": 0, "started": 0, "running": 0}
    assert snapshot(world)[:5] == before[:5]
    assert summary["terminal"] and summary["reason"] == "settled"
    assert stages(world, n) == [state.READY, state.ESC_NOT_SUITABLE]
    assert gh.labels(n) >= {state.ESC_NOT_SUITABLE, state.READY}
    assert gh.issues[n]["state"] == "open"
    escalation = next(b for b in gh.bodies(n) if b.startswith("<!-- sdlc-escalation:v1"))
    for reason in UNSUITABLE["reasons"]:
        assert reason in escalation
    # zero code edits: no test design, no coder job, no branch or PR, main untouched; the only new
    # commits are the metrics.json writes every step makes
    assert not foundry.agent_calls("sdlc-test-designer") and not foundry.hosted
    assert gh.pulls == {} and gh.merges == [] and gh.tags == []
    assert set(gh.branches) == {"main", "metrics"} and gh.branches["main"] == main_before
    assert {f for sha in set(gh.commits) - commits_before for f in gh.commits[sha]["files"]} == {"metrics.json"}
    entry = metrics_doc(world)["issues"][0]
    assert entry["outcome"] == "escalated" and entry["escalation"] == state.ESC_NOT_SUITABLE
    assert entry["scenario"] == "c"
    assert_settled_without_lock_and_under_cap(world, deps, n, created_branches)


# -- scenario d-maintenance: stale test repaired on the owner PR, merged, released ------------------

async def test_scenario_d_maintenance_pr_is_repaired_merged_and_released_by_its_pr_workflow(
        env: WorkflowEnvironment, world: World, created_branches: list[str]) -> None:
    gh, foundry = world.gh, world.foundry
    pr = open_stale_test_pr(world)
    worker, deps = factory_worker(env, world)
    async with worker:
        summary = await finished(env, await poll_once(env, f"pr-{pr}"))

    assert summary["terminal"] and summary["stage"] == state.RELEASED and summary["number"] == pr
    ci_input = foundry.agent_calls("sdlc-ci-triage")[0]
    assert "expected 'Track your parcel'" in ci_input and "test files changed: no" in ci_input
    job = next(body["job"] for _, body, _ in foundry.hosted if body["op"] == "start")
    assert job["mode"] == "maintenance" and job["branch"] == "chore/update-home-heading"
    assert job["allowed_paths"] == ["app/web/tests/home-page.test.tsx"] and job["pr"] == {"number": pr}
    messages = [gh.commits[sha]["message"] for sha in gh.pr_commits(pr)]
    assert messages == ["feat(web): update home page heading copy", "test: repair stale test"]
    assert gh.commits[gh.pr_commits(pr)[-1]]["files"] == ("app/web/tests/home-page.test.tsx",)
    assert gh.pulls[pr]["merged"] and gh.merges[0][2] == "merge"
    assert gh.tags == ["v0.1.0"]
    st = gh.state_of(pr)
    assert st["type"] == "maintenance" and st["ci_triage"]["cause"] == "stale-test"
    assert [s["stage"] for s in st["stages"]] == [state.BUILDING, state.IN_REVIEW, state.MERGED, state.RELEASED]
    assert any(b.startswith("<!-- sdlc-ci-triage:v1 -->") for b in gh.bodies(pr))
    entry = metrics_doc(world)["issues"][0]
    assert entry["type"] == "maintenance" and entry["scenario"] == "d-maintenance"
    assert entry["kind"] == "pr" and entry["number"] is None and entry["pr"] == pr
    assert entry["gate_attempts"]["test"] == ["failure", "success"]
    assert entry["gate_attempts"]["e2e"] == ["success", "success"]
    rates = metrics_doc(world)["gate_pass_rates"]
    assert rates["test"] == {"pass": 1, "fail": 1, "first_pass": 0, "first_fail": 1}
    assert_settled_without_lock_and_under_cap(world, deps, pr, created_branches)
