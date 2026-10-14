"""Unit tests for the UI screenshot artifact validator (scripts/ui/validate_artifact.py)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from scripts.ui.validate_artifact import (
    MAX_FILE_COUNT,
    MAX_SINGLE_FILE_BYTES,
    PNG_MAGIC_BYTES,
    validate_artifact_dir,
)

# Minimal 1x1 valid PNG bytes
MINIMAL_PNG_BYTES = (
    PNG_MAGIC_BYTES
    + b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
    + b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
    + b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_valid_artifact(dir_path: Path, count: int = 2) -> dict[str, Any]:
    screenshots = []
    for i in range(count):
        fn = f"screen-{i}.png"
        data = MINIMAL_PNG_BYTES + bytes([i])  # distinct content
        p = dir_path / fn
        p.write_bytes(data)
        screenshots.append({
            "filename": fn,
            "route": f"route-{i}",
            "viewport": "desktop",
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        })

    manifest = {"version": 1, "head_sha": "abc12345", "screenshots": screenshots}
    (dir_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_valid_artifact_passes(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=4)
    result = validate_artifact_dir(tmp_path)
    assert result.valid is True
    assert result.errors == []
    assert len(result.screenshots) == 4
    assert len(result.manifest_sha256) == 64


def test_manifest_schema_fields(tmp_path: Path) -> None:
    manifest = _make_valid_artifact(tmp_path, count=1)
    result = validate_artifact_dir(tmp_path)
    assert result.valid is True
    assert result.manifest == manifest
    item = result.screenshots[0]
    for key in ("filename", "route", "viewport", "sha256", "size"):
        assert key in item
    assert item["route"] == "route-0"
    assert item["viewport"] == "desktop"


def test_malicious_fixture_non_png_with_png_name(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    # Overwrite the PNG file with text / fake data lacking PNG magic bytes
    fake_png = tmp_path / "screen-0.png"
    fake_data = b"<html><script>alert(1)</script></html>"
    fake_png.write_bytes(fake_data)

    # Update manifest to match fake size & sha to isolate the magic bytes check
    manifest = {
        "version": 1,
        "screenshots": [
            {
                "filename": "screen-0.png",
                "route": "home",
                "viewport": "desktop",
                "sha256": hashlib.sha256(fake_data).hexdigest(),
                "size": len(fake_data),
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("magic bytes" in err for err in result.errors)


def test_malicious_fixture_path_traversal_filename_in_manifest(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    manifest = {
        "version": 1,
        "screenshots": [
            {
                "filename": "../../etc/passwd.png",
                "route": "home",
                "viewport": "desktop",
                "sha256": "a" * 64,
                "size": 100,
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("unsafe filename" in err or "Illegal file name" in err for err in result.errors)


def test_malicious_fixture_symlink(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    target_outside = tmp_path.parent / "outside_target.png"
    target_outside.write_bytes(MINIMAL_PNG_BYTES)

    symlink_file = tmp_path / "symlink-attack.png"
    try:
        os.symlink(target_outside, symlink_file)
    except OSError:
        pytest.skip("Symlink creation not permitted in this environment")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("Symlink detected" in err for err in result.errors)


def test_malicious_fixture_huge_file(tmp_path: Path) -> None:
    huge_file = tmp_path / "huge-file.png"
    # Create sparse file exceeding MAX_SINGLE_FILE_BYTES
    with open(huge_file, "wb") as f:
        f.seek(MAX_SINGLE_FILE_BYTES + 1024)
        f.write(b"\x00")

    manifest = {
        "version": 1,
        "screenshots": [
            {
                "filename": "huge-file.png",
                "route": "home",
                "viewport": "desktop",
                "sha256": "0" * 64,
                "size": MAX_SINGLE_FILE_BYTES + 1025,
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("exceeds max" in err for err in result.errors)


def test_malicious_disallowed_file_extension(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    (tmp_path / "payload.sh").write_text("#!/bin/bash\necho evil", encoding="utf-8")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("Disallowed file" in err for err in result.errors)


def test_subdirectories_rejected(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    nested = tmp_path / "nested_dir"
    nested.mkdir()

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("Subdirectories not permitted" in err for err in result.errors)


def test_missing_manifest_rejected(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    (tmp_path / "manifest.json").unlink()

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("Missing manifest.json" in err for err in result.errors)


def test_unlisted_png_rejected(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    # Add extra png on disk that is not in manifest
    extra = tmp_path / "unlisted.png"
    extra.write_bytes(MINIMAL_PNG_BYTES)

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("unlisted on disk" in err for err in result.errors)


def test_sha256_mismatch_rejected(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["screenshots"][0]["sha256"] = "f" * 64
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("sha256 mismatch" in err for err in result.errors)


def test_size_mismatch_rejected(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["screenshots"][0]["size"] = 999999
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("size mismatch" in err for err in result.errors)


def test_exceeding_max_file_count(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=MAX_FILE_COUNT + 1)
    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("exceeds limit" in err for err in result.errors)
