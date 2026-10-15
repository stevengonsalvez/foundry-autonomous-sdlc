"""
A revise job with merge_main merges origin/main into the PR branch (a real merge commit: no rebase,
no force push) so a PR GitHub reports as conflicting can merge. The engine only resolves conflicts,
keeping both sides; everything else of the merge is main's own content.
"""

from __future__ import annotations

from .gitfixture import advance_main, git, make_remote, remote_file, remote_log
from .test_runner import ETA_TEST, SEED, ScriptedEngine, World, job, start, wait, world  # noqa: F401

from sdlc_agents.ports import REPO

STYLES = "app/web/src/styles.txt"
BRANCH = "agent/issue-40"


def conflicting_world(world: World) -> World:
    """agent/issue-40 appended a line to styles.txt; main (a theme toggle, merged first) appended another."""
    world.remote_root = world.tmp / "remote-merge"
    world.base_url = make_remote(world.remote_root, {**SEED, STYLES: "base\n"}, branches={
        BRANCH: [("test: add failing tests for #40", {ETA_TEST: "expect web/src/eta.txt == 2026-10-12\n"}),
                 ("feat: Show the ETA (#40)", {"app/web/src/eta.txt": "2026-10-12\n", STYLES: "base\neta-style\n"})],
    })
    return world


def merge_job(**overrides: object) -> dict[str, object]:
    return job(**{"job_id": "j-40-3", "mode": "revise", "branch": BRANCH, "tests": [], "pr": {"number": 41},
                  "issue": {"number": 40, "title": "Show the ETA", "body": "Show it."},
                  "spec": {"acceptance_criteria": ["ETA visible"], "notes": "PR has merge conflicts with main."},
                  "merge_main": True, **overrides})


def parents(world: World, ref: str) -> list[str]:
    return git(world.remote_root / f"{REPO}.git", "rev-list", "--parents", "-n", "1", ref).split()[1:]


def main_sha(world: World) -> str:
    return git(world.remote_root / f"{REPO}.git", "rev-parse", "main").strip()


def test_a_clean_merge_needs_no_engine_and_pushes_a_two_parent_merge_commit(world: World) -> None:
    conflicting_world(world)
    tip = git(world.remote_root / f"{REPO}.git", "rev-parse", BRANCH).strip()
    advance_main(world.remote_root, "feat: theme toggle (#95)", {"app/web/src/theme.txt": "dark\n"})
    world.engines = [ScriptedEngine("agy", [])]
    service = world.service()
    start(service, merge_job())
    status = wait(service, "j-40-3")
    assert status["status"] == "succeeded", status
    assert status["pr"]["number"] == 41 and world.engines[0].prompts == []
    assert parents(world, BRANCH) == [tip, main_sha(world)]
    assert remote_file(world.remote_root, BRANCH, "app/web/src/theme.txt") == "dark\n"
    assert remote_log(world.remote_root, BRANCH)[:2] == ["test: add failing tests for #40", "feat: Show the ETA (#40)"]


def test_conflicts_are_resolved_by_the_engine_keeping_both_sides(world: World) -> None:
    conflicting_world(world)
    tip = git(world.remote_root / f"{REPO}.git", "rev-parse", BRANCH).strip()
    advance_main(world.remote_root, "feat: theme toggle (#95)", {STYLES: "base\ntheme-style\n"})
    world.engines = [ScriptedEngine("agy", [{STYLES: "base\ntheme-style\neta-style\n"}])]
    service = world.service()
    start(service, merge_job())
    status = wait(service, "j-40-3")
    assert status["status"] == "succeeded", status
    prompt = world.engines[0].prompts[0]
    assert "merge conflicts" in prompt and STYLES in prompt and "both" in prompt.lower()
    assert remote_file(world.remote_root, BRANCH, STYLES) == "base\ntheme-style\neta-style\n"
    # One merge commit on top of the branch: no wip commit with markers, no rewritten history.
    assert parents(world, BRANCH) == [tip, main_sha(world)]
    assert remote_log(world.remote_root, BRANCH) == [
        "test: add failing tests for #40", "feat: Show the ETA (#40)", f"Merge origin/main into {BRANCH}"]


def test_markers_left_in_a_conflicted_file_stop_the_job_before_anything_is_pushed(world: World) -> None:
    conflicting_world(world)
    tip = git(world.remote_root / f"{REPO}.git", "rev-parse", BRANCH).strip()
    advance_main(world.remote_root, "feat: theme toggle (#95)", {STYLES: "base\ntheme-style\n"})
    world.engines = [ScriptedEngine("agy", [{"app/web/src/unrelated.txt": "x\n"}])]    # leaves styles.txt alone
    service = world.service()
    start(service, merge_job())
    status = wait(service, "j-40-3")
    assert status["status"] == "failed" and status["reason"] == "unresolved-conflicts", status
    assert "styles.txt" in status["detail"]
    assert git(world.remote_root / f"{REPO}.git", "rev-parse", BRANCH).strip() == tip


def test_an_engine_cannot_resolve_a_conflict_by_editing_a_protected_test(world: World) -> None:
    conflicting_world(world)
    advance_main(world.remote_root, "feat: theme toggle (#95)", {STYLES: "base\ntheme-style\n"})
    world.engines = [ScriptedEngine("agy", [{STYLES: "base\ntheme-style\neta-style\n",
                                              ETA_TEST: "expect web/src/eta.txt == anything\n"}])]
    service = world.service()
    start(service, merge_job())
    status = wait(service, "j-40-3")
    assert status["status"] == "failed" and status["reason"] == "scope-violation", status


def test_a_revise_without_merge_main_still_squashes_to_one_commit(world: World) -> None:
    world.engines = [ScriptedEngine("agy", [{"app/web/src/eta-label.txt": "Estimated delivery\n"}])]
    service = world.service()
    start(service, merge_job(merge_main=False, job_id="j-40-2"))
    assert wait(service, "j-40-2")["status"] == "succeeded"
    assert len(parents(world, "agent/issue-40")) == 1


