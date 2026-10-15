"""Unit tests for UI screenshot proof formatting and pruning (scripts/ui/publish_proof.py)."""

from __future__ import annotations

import datetime
import hashlib
import json
import struct
import zlib
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from scripts.tests.ui.test_validate_artifact import _make_valid_artifact
from scripts.ui import publish_proof
from scripts.ui.publish_proof import (
    MARKER,
    compare_screenshots,
    format_pr_comment,
    prune_old_prs,
    publish,
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

    # Mismatched sha in pull_requests_json returns None (patched run_cmd: hermetic)
    mismatch_payload = json.dumps(
        [{"number": 99, "head": {"ref": "agent/issue-1", "sha": "00000000"}}]
    )
    with patch("scripts.ui.publish_proof.run_cmd", return_value=""):
        assert resolve_pr_number("abcdef12", "owner/repo", mismatch_payload) is None

    # Ambiguous multiple PR matches return None
    multi_payload = json.dumps([
        {"number": 99, "head": {"sha": "abcdef12"}},
        {"number": 100, "head": {"sha": "abcdef12"}},
    ])
    assert resolve_pr_number("abcdef12", "owner/repo", multi_payload) is None

    # From empty json (patched run_cmd so fallback does not call gh api)
    with patch("scripts.ui.publish_proof.run_cmd", return_value=""):
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


def test_publish_comment_hash_matches_published_manifest(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    _make_valid_artifact(artifact_dir, count=2)
    raw_manifest_bytes = (artifact_dir / "manifest.json").read_bytes()
    raw_hash = hashlib.sha256(raw_manifest_bytes).hexdigest()

    posted_comments: list[str] = []
    written_manifest_bytes: list[bytes] = []
    orig_write_bytes = Path.write_bytes

    def record_write_bytes(self: Path, b: bytes) -> int:
        if self.name == "manifest.json":
            written_manifest_bytes.append(b)
        return orig_write_bytes(self, b)

    with (
        patch("scripts.ui.publish_proof.run_cmd", return_value=""),
        patch(
            "scripts.ui.publish_proof.post_or_update_comment",
            side_effect=lambda repo, pr, body: posted_comments.append(body),
        ),
        patch.object(Path, "write_bytes", side_effect=record_write_bytes, autospec=True),
    ):
        publish(
            artifacts_dir=str(artifact_dir),
            head_sha="0123456789abcdef0123456789abcdef01234567",
            repo="stevengonsalvez/foundry-autonomous-sdlc",
            pr_number=42,
        )

    assert written_manifest_bytes, "No manifest.json was written"
    published_hash = hashlib.sha256(written_manifest_bytes[-1]).hexdigest()
    assert len(posted_comments) == 1
    comment = posted_comments[0]
    assert f"- Manifest SHA-256: `{published_hash}`" in comment
    assert published_hash != raw_hash
    assert raw_hash not in comment


# ---- before/after state comparison ---------------------------------------------------

REPO = "stevengonsalvez/foundry-autonomous-sdlc"
HEAD = "0123456789abcdef0123456789abcdef01234567"
SIZES = {"desktop": (1280, 800), "mobile": (390, 844)}


def solid_png(viewport: str, color: tuple[int, int, int], band_rows: int = 0) -> bytes:
    """Fast valid RGB PNG; the first band_rows rows are red (a known changed region)."""
    width, height = SIZES[viewport]
    body = bytes([0]) + bytes(color) * width
    red = bytes([0]) + bytes([255, 0, 0]) * width
    raw = red * band_rows + body * (height - band_rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def write_set(
    directory: Path,
    states: dict[str, tuple[str, str, str, int]],
    *,
    skipped: list[str] | None = None,
) -> dict[str, Any]:
    """states: id -> (title, caption, route, band_rows). Writes both viewports + manifest."""
    directory.mkdir(parents=True, exist_ok=True)
    shots = []
    for sid, (title, caption, route, band) in states.items():
        for vp in ("desktop", "mobile"):
            data = solid_png(vp, (240, 240, 240), band)
            fn = f"{sid}-{vp}.png"
            (directory / fn).write_bytes(data)
            shots.append(
                {
                    "filename": fn,
                    "state": sid,
                    "route": route,
                    "viewport": vp,
                    "title": title,
                    "caption": caption,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size": len(data),
                }
            )
    manifest = {"version": 1, "screenshots": shots, "skipped": skipped or []}
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def load(directory: Path) -> list[dict[str, Any]]:
    return json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["screenshots"]


STATES_AFTER = {
    "home-default": ("Home", "Home page default.", "home", 0),
    "home-dark": ("Home, dark theme", "Home page in dark theme.", "home", 0),
    "parcel-timeline": ("Parcel timeline", "Parcel shipment history.", "parcel-found", 40),
}
STATES_BEFORE = {
    "home-default": ("Home", "Home page default.", "home", 0),
    "parcel-timeline": ("Parcel timeline", "Parcel shipment history.", "parcel-found", 0),
}


def test_compare_flags_changed_new_and_unchanged(tmp_path: Path) -> None:
    after, before = tmp_path / "after", tmp_path / "before"
    write_set(after, STATES_AFTER)
    write_set(before, STATES_BEFORE)

    report = compare_screenshots(load(after), after, load(before), before)
    by_id = {s["state"]: s for s in report}

    assert by_id["home-default"]["status"] == "unchanged"
    assert by_id["home-default"]["viewports"]["desktop"]["pct"] == 0.0
    assert by_id["home-dark"]["status"] == "new"
    changed = by_id["parcel-timeline"]
    assert changed["status"] == "changed"
    # 40 of 800 desktop rows are red: 5% of pixels
    assert changed["viewports"]["desktop"]["pct"] == pytest.approx(5.0)
    assert changed["viewports"]["mobile"]["before"] == "parcel-timeline-mobile.png"
    # changed states come first, then new, then unchanged
    assert [s["status"] for s in report] == ["changed", "new", "unchanged"]


def test_identical_screenshots_are_not_decoded(tmp_path: Path) -> None:
    after, before = tmp_path / "after", tmp_path / "before"
    write_set(after, STATES_BEFORE)
    write_set(before, STATES_BEFORE)
    with patch(
        "scripts.ui.publish_proof.diff_pngs", side_effect=AssertionError("must not decode")
    ):
        report = compare_screenshots(load(after), after, load(before), before)
    assert {s["status"] for s in report} == {"unchanged"}


def test_undecodable_png_reads_as_changed_with_unknown_amount(tmp_path: Path) -> None:
    after, before = tmp_path / "after", tmp_path / "before"
    write_set(after, STATES_BEFORE)
    write_set(before, STATES_BEFORE)
    # same dimensions but a different, unsupported (16-bit) encoding
    raw = bytes([0]) + bytes(6) * 1280
    ihdr = struct.pack(">IIBBBBB", 1280, 800, 16, 2, 0, 0, 0)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    weird = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw * 800))
        + chunk(b"IEND", b"")
    )
    (after / "home-default-desktop.png").write_bytes(weird)
    items = load(after)
    items[0]["sha256"] = hashlib.sha256(weird).hexdigest()

    report = compare_screenshots(items, after, load(before), before)
    home = next(s for s in report if s["state"] == "home-default")
    assert home["status"] == "changed"
    assert home["viewports"]["desktop"]["pct"] is None


def _comment(tmp_path: Path, **kwargs: Any) -> str:
    after, before = tmp_path / "after", tmp_path / "before"
    manifest = write_set(after, STATES_AFTER, skipped=["home-left-nav"])
    write_set(before, STATES_BEFORE)
    report = compare_screenshots(load(after), after, load(before), before)
    return format_pr_comment(
        repo=REPO,
        pr_number=42,
        head_sha=HEAD,
        manifest_sha256="deadbeef" * 8,
        screenshots=manifest["screenshots"],
        report=report,
        skipped=manifest["skipped"],
        **kwargs,
    )


def test_comment_leads_with_changed_states_before_and_after(tmp_path: Path) -> None:
    comment = _comment(tmp_path)
    assert comment.startswith(MARKER)
    changed_at = comment.index("What this PR changed")
    unchanged_at = comment.index("Unchanged states")
    assert changed_at < unchanged_at

    changed_block = comment[changed_at:unchanged_at]
    base = f"https://raw.githubusercontent.com/{REPO}/pr-screenshots/pr-42/01234567"
    # changed state: before (from the baseline dir) and after side by side, with percentage
    assert "Parcel timeline" in changed_block
    assert "5.00%" in changed_block
    assert f"{base}/before/parcel-timeline-desktop.png" in changed_block
    assert f"{base}/parcel-timeline-desktop.png" in changed_block
    assert "Before" in changed_block and "After" in changed_block
    # new state has no before image
    assert "Home, dark theme" in changed_block
    assert "New" in changed_block
    assert f"{base}/before/home-dark-desktop.png" not in comment
    # unchanged state is in the collapsed list, not in the changed block
    assert "Home" in comment[unchanged_at:]
    assert "home-default-desktop.png" not in changed_block
    # unchanged section is collapsed (a plain <details>, not open)
    assert "<details>\n<summary><b>Unchanged states (1)" in comment
    # skipped states are listed so a missing feature is visible
    assert "home-left-nav" in comment


def test_comment_with_nothing_changed_says_so(tmp_path: Path) -> None:
    after, before = tmp_path / "after", tmp_path / "before"
    manifest = write_set(after, STATES_BEFORE)
    write_set(before, STATES_BEFORE)
    report = compare_screenshots(load(after), after, load(before), before)
    comment = format_pr_comment(
        repo=REPO,
        pr_number=7,
        head_sha=HEAD,
        manifest_sha256="a" * 64,
        screenshots=manifest["screenshots"],
        report=report,
        skipped=[],
    )
    assert "No visual changes" in comment
    assert "Unchanged states (2)" in comment


def test_comment_without_baseline_keeps_flat_table(tmp_path: Path) -> None:
    after = tmp_path / "after"
    manifest = write_set(after, STATES_AFTER)
    comment = format_pr_comment(
        repo=REPO,
        pr_number=7,
        head_sha=HEAD,
        manifest_sha256="a" * 64,
        screenshots=manifest["screenshots"],
        report=None,
        skipped=[],
    )
    assert "No baseline" in comment
    assert "<details open>" in comment
    assert "What this PR changed" not in comment
    assert "home-dark-desktop.png" in comment


def test_comment_escapes_hostile_state_text() -> None:
    shots = [
        {
            "filename": "x-desktop.png",
            "state": "x",
            "route": "home",
            "viewport": "desktop",
            "title": "<img src=x onerror=alert(1)> @everyone",
            "caption": "[click](https://evil.example) <!-- ui-proof:v1 -->",
        },
        {
            "filename": "../../etc/passwd.png",
            "state": "../../etc",
            "route": "home",
            "viewport": "desktop",
        },
    ]
    comment = format_pr_comment(
        repo=REPO,
        pr_number=7,
        head_sha=HEAD,
        manifest_sha256="a" * 64,
        screenshots=shots,
        report=None,
        skipped=["../../etc", "ok-state"],
    )
    assert "@everyone" not in comment
    assert "evil.example" not in comment
    assert "onerror" not in comment
    assert "etc/passwd" not in comment
    assert comment.count(MARKER) == 1
    assert "ok-state" in comment


def test_publish_copies_before_images_only_for_changed_states(tmp_path: Path) -> None:
    after, before = tmp_path / "after", tmp_path / "before"
    write_set(after, STATES_AFTER)
    write_set(before, STATES_BEFORE)

    copied: list[str] = []
    real_copy2 = publish_proof.shutil.copy2
    posted: list[str] = []

    def spy_copy2(src: Any, dst: Any, *a: Any, **k: Any) -> Any:
        copied.append(str(dst))
        return real_copy2(src, dst, *a, **k)

    with (
        patch("scripts.ui.publish_proof.run_cmd", return_value=""),
        patch("scripts.ui.publish_proof.shutil.copy2", side_effect=spy_copy2),
        patch(
            "scripts.ui.publish_proof.post_or_update_comment",
            side_effect=lambda repo, pr, body: posted.append(body),
        ),
    ):
        publish(
            artifacts_dir=str(after),
            base_dir=str(before),
            head_sha=HEAD,
            repo=REPO,
            pr_number=42,
        )

    before_copies = sorted(Path(p).name for p in copied if "/before/" in p)
    assert before_copies == ["parcel-timeline-desktop.png", "parcel-timeline-mobile.png"]
    after_copies = sorted(Path(p).name for p in copied if "/before/" not in p)
    assert len(after_copies) == 6  # 3 states x 2 viewports
    assert len(posted) == 1
    assert "What this PR changed" in posted[0]


def test_publish_ignores_an_invalid_baseline(tmp_path: Path) -> None:
    after, before = tmp_path / "after", tmp_path / "before"
    write_set(after, STATES_AFTER)
    before.mkdir()
    (before / "manifest.json").write_text("{not json", encoding="utf-8")

    posted: list[str] = []
    with (
        patch("scripts.ui.publish_proof.run_cmd", return_value=""),
        patch(
            "scripts.ui.publish_proof.post_or_update_comment",
            side_effect=lambda repo, pr, body: posted.append(body),
        ),
    ):
        publish(
            artifacts_dir=str(after),
            base_dir=str(before),
            head_sha=HEAD,
            repo=REPO,
            pr_number=42,
        )
    assert len(posted) == 1
    assert "No baseline" in posted[0]
    assert "What this PR changed" not in posted[0]
