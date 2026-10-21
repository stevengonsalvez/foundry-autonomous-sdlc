"""Tests for the release backfill orchestration (scripts/ui/backfill_history.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts.tests.ui.test_publish_proof import write_set
from scripts.ui import backfill_history

BASE = {"home-default": ("Home", "Home page default.", "home", 0)}
NEXT = {
    "home-default": ("Home", "Home page default.", "home", 0),
    "home-dark": ("Home, dark theme", "Home page in dark theme.", "home", 0),
}


def test_backfill_defaults_to_every_tag() -> None:
    with (
        patch.object(backfill_history, "run_backfill") as run,
        patch("sys.argv", ["backfill_history.py", "--no-local-history"]),
    ):
        backfill_history.main()
    assert run.call_args.kwargs["max_tag"] is None
    assert run.call_args.kwargs["tags"] is None


def test_backfill_records_changes_between_consecutive_tags(tmp_path: Path) -> None:
    def fake_capture(tag: str, dest: Path) -> dict[str, Any]:
        write_set(dest, BASE if tag == "v0.1.0" else NEXT)
        manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
        manifest.update(tag=tag, reproducible=True)
        (dest / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return manifest

    with (
        patch.object(backfill_history, "capture_tag", side_effect=fake_capture),
        patch.object(backfill_history, "commit_to_pr_screenshots_branch"),
    ):
        backfill_history.run_backfill(
            tags=["v0.1.0", "v0.2.0"], output_dir=tmp_path, update_local_history=False
        )

    first = json.loads((tmp_path / "v0.1.0" / "manifest.json").read_text(encoding="utf-8"))
    second = json.loads((tmp_path / "v0.2.0" / "manifest.json").read_text(encoding="utf-8"))
    assert first["changes"]["vs"] is None
    assert second["changes"]["vs"] == "v0.1.0"
    assert second["changes"]["states"]["home-dark"]["status"] == "new"
    assert second["changes"]["states"]["home-default"]["status"] == "unchanged"


def test_overlay_keeps_files_from_earlier_captures(tmp_path: Path) -> None:
    stored = tmp_path / "stored"
    stored.mkdir()
    (stored / "home-desktop.png").write_bytes(b"old capture linked from the README")
    (stored / "manifest.json").write_text("old", encoding="utf-8")

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "home-default-desktop.png").write_bytes(b"new")
    (fresh / "manifest.json").write_text("new", encoding="utf-8")

    backfill_history.overlay_release(fresh, stored)

    assert (stored / "home-desktop.png").read_bytes() == b"old capture linked from the README"
    assert (stored / "home-default-desktop.png").read_bytes() == b"new"
    assert (stored / "manifest.json").read_text(encoding="utf-8") == "new"
