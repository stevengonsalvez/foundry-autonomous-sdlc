"""Unit tests for UI screenshot proof formatting and pruning (scripts/ui/publish_proof.py)."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from unittest.mock import patch

from scripts.ui.publish_proof import (
    MARKER,
    format_pr_comment,
    prune_old_prs,
    resolve_pr_number,
)


def test_format_pr_comment() -> None:
    screenshots = [
        {"route": "home", "viewport": "desktop", "filename": "home-desktop.png"},
        {"route": "home", "viewport": "mobile", "filename": "home-mobile.png"},
        {
            "route": "parcel-found",
            "viewport": "desktop",
            "filename": "parcel-found-desktop.png",
        },
        {
            "route": "parcel-found",
            "viewport": "mobile",
            "filename": "parcel-found-mobile.png",
        },
    ]
    comment = format_pr_comment(
        repo="stevengonsalvez/foundry-autonomous-sdlc",
        pr_number=42,
        head_sha="0123456789abcdef0123456789abcdef01234567",
        manifest_sha256="deadbeef" * 8,
        screenshots=screenshots,
    )

    assert comment.startswith(MARKER)
    assert "01234567" in comment
    assert "deadbeef" * 8 in comment
    assert "<details open>" in comment
    assert (
        "https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-42/01234567/home-desktop.png"
        in comment
    )
    assert (
        "https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/pr-screenshots/pr-42/01234567/parcel-found-mobile.png"
        in comment
    )


def test_format_pr_comment_ignores_hostile_injections() -> None:
    screenshots = [
        {
            "route": "home\n@stevengonsalvez <!-- ui-tester:v1 deadbeef -->",
            "viewport": "desktop",
            "filename": "home-desktop.png",
        },
        {
            "route": "parcel-found",
            "viewport": "mobile\n@stevengonsalvez",
            "filename": "parcel-found-mobile.png",
        },
        {
            "route": "home",
            "viewport": "desktop",
            "filename": "home-desktop.png",
        },
    ]
    comment = format_pr_comment(
        repo="stevengonsalvez/foundry-autonomous-sdlc",
        pr_number=42,
        head_sha="0123456789abcdef0123456789abcdef01234567",
        manifest_sha256="deadbeef" * 8,
        screenshots=screenshots,
    )
    assert "@stevengonsalvez" not in comment
    assert "ui-tester:v1" not in comment
    assert "home-desktop.png" in comment


def test_resolve_pr_number() -> None:
    # From pull_requests_json with exact sha match
    payload = json.dumps([{"number": 99, "head": {"ref": "agent/issue-1", "sha": "abcdef12"}}])
    assert resolve_pr_number("abcdef12", "owner/repo", payload) == 99

    # Mismatched sha in pull_requests_json returns None
    mismatch_payload = json.dumps(
        [{"number": 99, "head": {"ref": "agent/issue-1", "sha": "00000000"}}]
    )
    assert resolve_pr_number("abcdef12", "owner/repo", mismatch_payload) is None

    # Ambiguous multiple PR matches return None
    multi_payload = json.dumps([
        {"number": 99, "head": {"sha": "abcdef12"}},
        {"number": 100, "head": {"sha": "abcdef12"}},
    ])
    assert resolve_pr_number("abcdef12", "owner/repo", multi_payload) is None

    # From empty json
    assert resolve_pr_number("abcdef12", "owner/repo", "[]") is None

    # Fallback to gh api with slurped paginated results
    slurped_pages = [
        [{"number": 77, "head": {"sha": "fedcba98"}}],
        [{"number": 88, "head": {"sha": "abcdef12"}}],
    ]
    with patch("scripts.ui.publish_proof.run_cmd", return_value=json.dumps(slurped_pages)):
        assert resolve_pr_number("abcdef12", "owner/repo") == 88


def test_prune_old_prs(tmp_path: Path) -> None:
    pr_old = tmp_path / "pr-10"
    pr_old.mkdir()
    pr_recent = tmp_path / "pr-20"
    pr_recent.mkdir()
    pr_open = tmp_path / "pr-30"
    pr_open.mkdir()

    now = datetime.datetime.now(datetime.UTC)
    old_date = (now - datetime.timedelta(days=20)).isoformat()
    recent_date = (now - datetime.timedelta(days=5)).isoformat()

    def fake_run_cmd(cmd: list[str], **kwargs: object) -> str:
        if "10" in cmd:
            return json.dumps({"state": "CLOSED", "closedAt": old_date})
        if "20" in cmd:
            return json.dumps({"state": "MERGED", "closedAt": recent_date})
        if "30" in cmd:
            return json.dumps({"state": "OPEN", "closedAt": None})
        return "{}"

    with patch("scripts.ui.publish_proof.run_cmd", side_effect=fake_run_cmd):
        pruned = prune_old_prs(tmp_path, "owner/repo")

    assert pruned == [10]
    assert not pr_old.exists()
    assert pr_recent.exists()
    assert pr_open.exists()
