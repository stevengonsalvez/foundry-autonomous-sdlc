"""Tests for the Phase 2 advisory vision UI tester agent (sdlc-ui-tester) and orchestrator tick step."""

from __future__ import annotations

import pytest
from conftest import World

from sdlc_agents import gates, state
from sdlc_agents.ports import OWNER, REPO, CheckRun, Comment
from sdlc_agents.tick import (
    UI_PROOF_MARKER,
    UI_TESTER_FEATURE_FLAG,
    is_ui_tester_enabled,
    render_ui_tester_marker,
)


def _setup_open_agent_pr(
    world: World,
    *,
    branch: str = "agent/issue-1",
    author: str = OWNER,
    labels: tuple[str, ...] = (gates.AGENT_PR_LABEL,),
    ui_proof: bool = True,
) -> tuple[int, int, str]:
    """Sets up an issue in IN_REVIEW with an associated open agent PR."""
    n = world.gh.open_issue("Test issue", "Body", labels=("type:feature", f"stage:{state.IN_REVIEW}"))
    head_sha = world.gh._commit("feat: test", ("app/web/src/Home.tsx",), world.gh.branches["main"])
    world.gh.branches[branch] = head_sha
    pr_num = world.gh.open_pr("feat: test", f"Closes #{n}", branch, [], author=author, labels=labels)

    # Set all required checks to success so review step proceeds cleanly
    world.gh.check_runs[head_sha] = [
        CheckRun(check, "completed", "success", world.clock.now_iso(), (pr_num,))
        for check in gates.REQUIRED_CHECKS
    ]

    st = state.State.new(n, "feature", None)
    st.enter(state.READY, world.clock.now_iso())
    st.enter(state.FEASIBLE, world.clock.now_iso())
    st.enter(state.TESTS_WRITTEN, world.clock.now_iso())
    st.enter(state.BUILDING, world.clock.now_iso())
    st.enter(state.IN_REVIEW, world.clock.now_iso())
    st.data["pr"] = {"number": pr_num, "branch": branch, "head": head_sha}
    world.gh.comments[n] = [Comment(100, OWNER, state.render(st), world.clock.now_iso())]

    if ui_proof:
        head_short = head_sha[:8]
        base_url = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/pr-screenshots/pr-{pr_num}/{head_short}"
        proof_comment = (
            f"{UI_PROOF_MARKER}\n"
            f"### UI Screenshots for `{head_short}`\n\n"
            f"- Head commit: `{head_sha}`\n"
            "| Route | Desktop | Mobile |\n"
            "| --- | --- | --- |\n"
            f'| home | <img src="{base_url}/home-desktop-1280.png" /> | '
            f'<img src="{base_url}/home-mobile-390.png" /> |\n'
            "</details>"
        )
        world.gh.comments[pr_num] = [Comment(101, OWNER, proof_comment, world.clock.now_iso())]

    return n, pr_num, head_sha


def test_is_ui_tester_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(UI_TESTER_FEATURE_FLAG, raising=False)
    assert not is_ui_tester_enabled()

    for val in ("0", "false", "no", "off", "random"):
        monkeypatch.setenv(UI_TESTER_FEATURE_FLAG, val)
        assert not is_ui_tester_enabled()

    for val in ("1", "true", "yes", "on", "TRUE", "Yes"):
        monkeypatch.setenv(UI_TESTER_FEATURE_FLAG, val)
        assert is_ui_tester_enabled()


def test_ui_tester_disabled_by_default(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(UI_TESTER_FEATURE_FLAG, raising=False)
    _, pr_num, head_sha = _setup_open_agent_pr(world, ui_proof=True)

    world.tick()

    assert not world.foundry.agent_calls("sdlc-ui-tester")
    marker = render_ui_tester_marker(head_sha)
    assert not any(marker in c.body for c in world.gh.comments[pr_num])


def test_ui_tester_triggered_when_enabled(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(UI_TESTER_FEATURE_FLAG, "1")
    n, pr_num, head_sha = _setup_open_agent_pr(world, ui_proof=True)

    world.tick()

    calls = world.foundry.agent_calls("sdlc-ui-tester")
    assert len(calls) == 1
    input_text = calls[0]
    assert head_sha in input_text
    assert f"pr-{pr_num}" in input_text
    assert "home-desktop-1280.png" in input_text

    marker = render_ui_tester_marker(head_sha)
    tester_comments = [c for c in world.gh.comments[pr_num] if marker in c.body]
    assert "**PASS** (advisory)" in tester_comments[0].body
    assert "No visual UI anomalies detected." in tester_comments[0].body

    # Check state recorded
    st = world.gh.state_of(n)
    assert st["ui_tester"]["verdict"] == "pass"
    assert st["ui_tester"]["head"] == head_sha


def test_ui_tester_is_idempotent_for_same_head_sha(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(UI_TESTER_FEATURE_FLAG, "1")
    _, pr_num, head_sha = _setup_open_agent_pr(world, ui_proof=True)

    world.tick()
    assert len(world.foundry.agent_calls("sdlc-ui-tester")) == 1

    world.tick()
    # No additional call made
    assert len(world.foundry.agent_calls("sdlc-ui-tester")) == 1
    marker = render_ui_tester_marker(head_sha)
    assert sum(marker in c.body for c in world.gh.comments[pr_num]) == 1


def test_ui_tester_runs_for_new_head_sha(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(UI_TESTER_FEATURE_FLAG, "1")
    n, pr_num, head_sha_1 = _setup_open_agent_pr(world, ui_proof=True)

    world.tick()
    assert len(world.foundry.agent_calls("sdlc-ui-tester")) == 1

    # Push new commit to PR
    branch = f"agent/issue-{n}"
    head_sha_2 = world.gh._commit("feat: update", ("app/web/src/Home.tsx",), head_sha_1)
    world.gh.branches[branch] = head_sha_2
    world.gh.pulls[pr_num]["head_sha"] = head_sha_2
    world.gh.check_runs[head_sha_2] = [
        CheckRun(check, "completed", "success", world.clock.now_iso(), (pr_num,))
        for check in gates.REQUIRED_CHECKS
    ]
    st = world.gh.state_of(n)
    st_obj = state.State(st)
    world.gh.comments[n][0] = Comment(100, OWNER, state.render(st_obj), world.clock.now_iso())

    head_short_2 = head_sha_2[:8]
    base_url_2 = f"https://raw.githubusercontent.com/{OWNER}/{REPO}/pr-screenshots/pr-{pr_num}/{head_short_2}"
    new_proof = (
        f"{UI_PROOF_MARKER}\n"
        f"### UI Screenshots for `{head_short_2}`\n\n"
        f"- Head commit: `{head_sha_2}`\n"
        f'| home | <img src="{base_url_2}/home-desktop-1280.png" /> |\n'
    )
    world.gh.comments[pr_num].append(Comment(105, OWNER, new_proof, world.clock.now_iso()))

    world.tick()

    assert len(world.foundry.agent_calls("sdlc-ui-tester")) == 2
    marker_2 = render_ui_tester_marker(head_sha_2)
    assert any(marker_2 in c.body for c in world.gh.comments[pr_num])


def test_ui_tester_skips_when_no_ui_proof(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(UI_TESTER_FEATURE_FLAG, "1")
    _, pr_num, _ = _setup_open_agent_pr(world, ui_proof=False)

    world.tick()

    assert not world.foundry.agent_calls("sdlc-ui-tester")
    assert not any("ui-tester:v1" in c.body for c in world.gh.comments[pr_num])


def test_ui_tester_skips_non_agent_pr(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(UI_TESTER_FEATURE_FLAG, "1")
    # Human PR: branch is not agent/* and no agent:pr label
    _, pr_num, _ = _setup_open_agent_pr(
        world,
        branch="feature/human-change",
        labels=(),
        ui_proof=True,
    )

    world.tick()

    assert not world.foundry.agent_calls("sdlc-ui-tester")
    assert not any("ui-tester:v1" in c.body for c in world.gh.comments[pr_num])


def test_ui_tester_concerns_verdict_is_advisory_and_does_not_block_merge(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(UI_TESTER_FEATURE_FLAG, "1")
    world.foundry.script(
        "sdlc-ui-tester",
        {
            "verdict": "concerns",
            "findings": [
                {
                    "route": "home",
                    "viewport": "mobile",
                    "issue": "Tracking button overflows on small screen",
                    "severity": "high",
                }
            ],
            "summary": "Visual alignment flaw on mobile viewport.",
        },
    )

    n, pr_num, head_sha = _setup_open_agent_pr(world, ui_proof=True)

    world.tick()

    marker = render_ui_tester_marker(head_sha)
    comment = next(c for c in world.gh.comments[pr_num] if marker in c.body)
    assert "**CONCERNS** (advisory)" in comment.body
    assert "Tracking button overflows on small screen" in comment.body
    assert "[high] home/mobile" in comment.body

    # Verification of merge: gates are unaffected because ui-tester is strictly advisory
    pr = world.gh.get_pull(pr_num)
    review_marker = Comment(
        200,
        OWNER,
        gates.render_review_marker("approve", head_sha),
        world.clock.now_iso(),
    )
    comments = [*world.gh.comments[pr_num], review_marker]
    check_runs = world.gh.check_runs[head_sha]
    res = gates.verify_merge(
        pr=pr,
        issue=world.gh.get_issue(n),
        check_runs=check_runs,
        pr_comments=comments,
        pr_files=tuple(world.gh.commits[head_sha]["files"]),
        object_usd=0.1,
        usd_cap=1.0,
    )
    assert res.passed, f"Merge should pass despite advisory concerns: {res.reasons}"
