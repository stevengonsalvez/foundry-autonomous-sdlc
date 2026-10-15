"""Tests for the per-release change annotation stored in release manifests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.tests.ui.test_publish_proof import write_set
from scripts.ui.release_changes import annotate_release, find_previous_release

BASE = {
    "home-default": ("Home", "Home page default.", "home", 0),
    "parcel-timeline": ("Parcel timeline", "Parcel shipment history.", "parcel-found", 0),
}
NEXT = {
    "home-default": ("Home", "Home page default.", "home", 0),
    "parcel-timeline": ("Parcel timeline", "Parcel shipment history.", "parcel-found", 40),
    "home-dark": ("Home, dark theme", "Home page in dark theme.", "home", 0),
}


def manifest(releases: Path, tag: str) -> dict[str, Any]:
    return json.loads((releases / tag / "manifest.json").read_text(encoding="utf-8"))


def mark_not_reproducible(releases: Path, tag: str) -> None:
    (releases / tag).mkdir(parents=True, exist_ok=True)
    (releases / tag / "manifest.json").write_text(
        json.dumps(
            {"version": 1, "reproducible": False, "reason": "build failed", "screenshots": []}
        ),
        encoding="utf-8",
    )


def test_annotates_new_changed_and_unchanged_with_pixel_percentages(tmp_path: Path) -> None:
    write_set(tmp_path / "v0.7.0", BASE)
    write_set(tmp_path / "v0.8.0", NEXT)

    changes = annotate_release(tmp_path, "v0.8.0")

    assert changes is not None and changes["vs"] == "v0.7.0"
    states = changes["states"]
    assert states["home-dark"]["status"] == "new"
    assert states["home-default"]["status"] == "unchanged"
    assert states["parcel-timeline"]["status"] == "changed"
    assert states["parcel-timeline"]["pct"]["desktop"] == pytest.approx(5.0)
    # persisted next to the screenshots, previous release untouched
    assert manifest(tmp_path, "v0.8.0")["changes"] == changes
    assert "changes" not in manifest(tmp_path, "v0.7.0")


def test_first_release_has_no_baseline(tmp_path: Path) -> None:
    write_set(tmp_path / "v0.1.0", BASE)
    changes = annotate_release(tmp_path, "v0.1.0")
    assert changes is not None and changes["vs"] is None
    assert {s["status"] for s in changes["states"].values()} == {"new"}


def test_previous_skips_uncaptured_releases(tmp_path: Path) -> None:
    write_set(tmp_path / "v0.1.0", BASE)
    mark_not_reproducible(tmp_path, "v0.2.0")
    write_set(tmp_path / "v0.3.0", NEXT)
    assert find_previous_release(tmp_path, "v0.3.0") == "v0.1.0"
    changes = annotate_release(tmp_path, "v0.3.0")
    assert changes is not None and changes["vs"] == "v0.1.0"


def test_previous_ignores_newer_and_non_semver_dirs(tmp_path: Path) -> None:
    write_set(tmp_path / "v0.1.0", BASE)
    write_set(tmp_path / "v0.9.0", BASE)
    write_set(tmp_path / "abcdef12", BASE)
    (tmp_path / "notes").mkdir()
    assert find_previous_release(tmp_path, "v0.5.0") == "v0.1.0"


def test_sha_keys_are_not_annotated(tmp_path: Path) -> None:
    write_set(tmp_path / "v0.1.0", BASE)
    write_set(tmp_path / "abcdef12", NEXT)
    assert annotate_release(tmp_path, "abcdef12") is None
    assert "changes" not in manifest(tmp_path, "abcdef12")


def test_uncaptured_release_is_left_alone(tmp_path: Path) -> None:
    write_set(tmp_path / "v0.1.0", BASE)
    mark_not_reproducible(tmp_path, "v0.2.0")
    assert annotate_release(tmp_path, "v0.2.0") is None
    assert "changes" not in manifest(tmp_path, "v0.2.0")


def test_corrupt_previous_manifest_is_skipped(tmp_path: Path) -> None:
    write_set(tmp_path / "v0.1.0", BASE)
    (tmp_path / "v0.1.0" / "manifest.json").write_text("{nope", encoding="utf-8")
    write_set(tmp_path / "v0.2.0", NEXT)
    changes = annotate_release(tmp_path, "v0.2.0")
    assert changes is not None and changes["vs"] is None


def test_annotation_is_idempotent(tmp_path: Path) -> None:
    write_set(tmp_path / "v0.7.0", BASE)
    write_set(tmp_path / "v0.8.0", NEXT)
    first = annotate_release(tmp_path, "v0.8.0")
    second = annotate_release(tmp_path, "v0.8.0")
    assert first == second
