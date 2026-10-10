"""
ci-triage names the test files a maintenance job may change, and a model can name a path that does
not exist (live: "app/tests/parcel-page.test.tsx"). The orchestrator hands it the real test file
list, then validates its answer against that list and the failing log: exact path, else a unique
basename, plus every test file the log reports failing. Nothing outside the list reaches the coder;
with no valid file left the PR escalates agent-error.
"""

from __future__ import annotations

from conftest import World
from test_scenarios import REPO_TEST_FILES, open_stale_test_pr

from sdlc_agents import state
from sdlc_agents.paths import resolve_test_files

REAL = [*REPO_TEST_FILES, "app/core/tests/parcel-page.test.ts"]
VITEST_LOG = """
 ✓ |core| tests/tracking-number.test.ts (4 tests) 6ms
 ❯ |web| tests/home-page.test.tsx (3 tests | 1 failed) 120ms
 FAIL  |web| tests/home-page.test.tsx > Home > shows the heading
 FAIL  |web| tests/parcel-page.test.tsx > ParcelPage > shows the page title
"""


def start_jobs(world: World) -> list[dict]:
    return [body["job"] for _, body, _ in world.foundry.hosted if body["op"] == "start"]


def test_a_nonexistent_triage_path_is_replaced_by_every_failing_test_file(world: World) -> None:
    gh, foundry = world.gh, world.foundry
    foundry.script("sdlc-ci-triage", {"cause": "stale-test", "explanation": "Heading copy changed.",
                                      "test_files": ["app/tests/parcel-page.test.tsx"]})
    pr = open_stale_test_pr(world)
    gh.logs[(gh.head_of(pr), "test")] = VITEST_LOG
    world.drive(lambda: state.RELEASED in gh.labels(pr))

    [job] = start_jobs(world)
    assert job["allowed_paths"] == ["app/web/tests/home-page.test.tsx", "app/web/tests/parcel-page.test.tsx"]
    triage_input = foundry.agent_calls("sdlc-ci-triage")[0]
    assert "name=repo_test_files>" in triage_input and "app/web/tests/parcel-page.test.tsx" in triage_input
    st = gh.state_of(pr)
    assert st["ci_triage"]["test_files"] == job["allowed_paths"]
    assert st["ci_triage"]["claimed"] == ["app/tests/parcel-page.test.tsx"]


def test_no_real_test_file_anywhere_escalates_agent_error_without_a_coder_job(world: World) -> None:
    gh, foundry = world.gh, world.foundry
    foundry.script("sdlc-ci-triage", {"cause": "stale-test", "explanation": "x", "test_files": ["app/nope.test.tsx"]})
    pr = open_stale_test_pr(world)
    gh.logs[(gh.head_of(pr), "test")] = "Error: process exited with code 1"
    world.drive(lambda: state.ESC_AGENT_ERROR in gh.labels(pr))
    assert start_jobs(world) == []
    assert "no test file" in gh.state_of(pr)["escalation"]["reasons"][0]


def test_resolution_rules() -> None:
    # exact match kept; unique basename mapped; ambiguous basename and unknown names dropped
    assert resolve_test_files(["app/web/tests/home-page.test.tsx"], REAL, "") == ["app/web/tests/home-page.test.tsx"]
    assert resolve_test_files(["tests/home-page.test.tsx"], REAL, "") == ["app/web/tests/home-page.test.tsx"]
    assert resolve_test_files(["home-page.test.tsx"], REAL, "") == ["app/web/tests/home-page.test.tsx"]
    assert resolve_test_files(["app/tests/parcel-page.test.tsx"], REAL, "") == ["app/web/tests/parcel-page.test.tsx"]
    assert resolve_test_files(["parcel-page.test.ts"], REAL, "") == ["app/core/tests/parcel-page.test.ts"]
    assert resolve_test_files(["app/x/../../etc/passwd", "README.md"], REAL, "") == []
    # failing files from the log are always added; passing ones (✓) are not
    assert resolve_test_files([], REAL, VITEST_LOG) == ["app/web/tests/home-page.test.tsx",
                                                        "app/web/tests/parcel-page.test.tsx"]
    assert resolve_test_files([], REAL, "FAIL app/core/tests/parcel-page.test.ts > x") == [
        "app/core/tests/parcel-page.test.ts"]
    assert resolve_test_files([], REAL, "FAIL |web| tests/missing.test.tsx > x") == []
