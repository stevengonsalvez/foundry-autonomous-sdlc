"""Unit tests for the UI screenshot artifact validator (scripts/ui/validate_artifact.py)."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest

from scripts.ui.validate_artifact import (
    MAX_FILE_COUNT,
    MAX_SINGLE_FILE_BYTES,
    validate_artifact_dir,
)


def make_test_png(width: int = 1280, height: int = 800, color_byte: int = 0) -> bytes:
    """Creates deterministic valid PNG bytes with the given dimensions."""
    raw_row = b"\x00" + (bytes([color_byte, 0, 0, 255]) * width)
    raw_data = raw_row * height
    compressed = zlib.compress(raw_data)

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


VALID_ROUTES = ("home", "parcel-found", "not-found", "invalid-input")


def _make_valid_artifact(dir_path: Path, count: int = 2) -> dict[str, Any]:
    screenshots = []
    for i in range(count):
        route = VALID_ROUTES[i % len(VALID_ROUTES)]
        viewport = "desktop" if (i // len(VALID_ROUTES)) % 2 == 0 else "mobile"
        width, height = (1280, 800) if viewport == "desktop" else (390, 844)
        fn = f"{route}-{viewport}-{i}.png"
        data = make_test_png(width, height, color_byte=i % 256)
        p = dir_path / fn
        p.write_bytes(data)
        screenshots.append(
            {
                "filename": fn,
                "route": route,
                "viewport": viewport,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        )

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
    assert item["route"] == "home"
    assert item["viewport"] == "desktop"


def test_malicious_fixture_non_png_with_png_name(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    # Overwrite the PNG file with text / fake data lacking PNG magic bytes
    fake_png = tmp_path / "home-desktop-0.png"
    fake_data = b"<html><script>alert(1)</script></html>"
    fake_png.write_bytes(fake_data)

    # Update manifest to match fake size & sha to isolate the magic bytes check
    manifest = {
        "version": 1,
        "screenshots": [
            {
                "filename": "home-desktop-0.png",
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
    target_outside.write_bytes(make_test_png(1280, 800))

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
    extra = tmp_path / "unlisted.png"
    extra.write_bytes(make_test_png(1280, 800))

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


def test_malicious_fixture_hostile_route_with_markdown(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["screenshots"][0]["route"] = "home\n[click](https://evil.com)"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("invalid route" in err for err in result.errors)


def test_malicious_fixture_hostile_route_with_mention(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["screenshots"][0]["route"] = "@stevengonsalvez"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("invalid route" in err for err in result.errors)


def test_malicious_fixture_hostile_route_with_fake_marker(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["screenshots"][0]["route"] = "<!-- ui-tester:v1 deadbeef -->"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("invalid route" in err for err in result.errors)


def test_malicious_fixture_hostile_viewport(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["screenshots"][0]["viewport"] = "desktop\n@stevengonsalvez"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("invalid viewport" in err for err in result.errors)


def test_malicious_fixture_png_with_appended_html(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    fn = "home-desktop-0.png"
    bad_data = make_test_png(1280, 800) + b"<html><script>alert(1)</script></html>"
    (tmp_path / fn).write_bytes(bad_data)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["screenshots"][0]["sha256"] = hashlib.sha256(bad_data).hexdigest()
    manifest["screenshots"][0]["size"] = len(bad_data)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("extraneous data appended after PNG IEND chunk" in err for err in result.errors)


def test_malicious_fixture_invalid_png_dimensions(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    fn = "home-desktop-0.png"
    bad_data = make_test_png(100, 100)
    (tmp_path / fn).write_bytes(bad_data)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["screenshots"][0]["sha256"] = hashlib.sha256(bad_data).hexdigest()
    manifest["screenshots"][0]["size"] = len(bad_data)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("dimensions" in err and "do not match expected" in err for err in result.errors)


def test_malicious_fixture_mismatched_dimensions_and_viewport(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    fn = "home-desktop-0.png"
    # Desktop viewport requires 1280x800, provide 390x844 instead
    bad_data = make_test_png(390, 844)
    (tmp_path / fn).write_bytes(bad_data)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["screenshots"][0]["sha256"] = hashlib.sha256(bad_data).hexdigest()
    manifest["screenshots"][0]["size"] = len(bad_data)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("do not match expected" in err and "for desktop" in err for err in result.errors)


def test_malicious_fixture_disallowed_png_chunk_type(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    fn = "home-desktop-0.png"
    valid_png = make_test_png(1280, 800)
    # Inject a disallowed chunk type (e.g. tEXt or evil)
    bad_tag = b"tEXt"
    bad_data = b"Some comment"
    crc = zlib.crc32(bad_tag + bad_data) & 0xFFFFFFFF
    chunk = struct.pack(">I", len(bad_data)) + bad_tag + bad_data + struct.pack(">I", crc)
    # Insert right before IEND chunk (last 12 bytes of valid_png)
    tampered_png = valid_png[:-12] + chunk + valid_png[-12:]
    (tmp_path / fn).write_bytes(tampered_png)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["screenshots"][0]["sha256"] = hashlib.sha256(tampered_png).hexdigest()
    manifest["screenshots"][0]["size"] = len(tampered_png)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("disallowed PNG chunk type" in err for err in result.errors)


def test_malicious_fixture_corrupted_png_chunk_crc(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    fn = "home-desktop-0.png"
    valid_png = bytearray(make_test_png(1280, 800))
    # Corrupt a byte in the IHDR CRC (bytes 29-32)
    valid_png[30] ^= 0xFF
    bad_data = bytes(valid_png)
    (tmp_path / fn).write_bytes(bad_data)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["screenshots"][0]["sha256"] = hashlib.sha256(bad_data).hexdigest()
    manifest["screenshots"][0]["size"] = len(bad_data)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("has invalid CRC" in err for err in result.errors)


def test_manifest_rejects_boolean_size(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["screenshots"][0]["size"] = True
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("has invalid size: True" in err for err in result.errors)


def test_png_rejects_multiple_ihdr_chunks(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    fn = "home-desktop-0.png"
    valid_png = make_test_png(1280, 800)
    # Duplicate the IHDR chunk
    ihdr_chunk = valid_png[8:33]
    tampered_png = valid_png[:33] + ihdr_chunk + valid_png[33:]
    (tmp_path / fn).write_bytes(tampered_png)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["screenshots"][0]["sha256"] = hashlib.sha256(tampered_png).hexdigest()
    manifest["screenshots"][0]["size"] = len(tampered_png)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("multiple IHDR chunks" in err for err in result.errors)


def test_png_rejects_invalid_ancillary_chunk_length(tmp_path: Path) -> None:
    _make_valid_artifact(tmp_path, count=1)
    fn = "home-desktop-0.png"
    valid_png = make_test_png(1280, 800)
    # Insert sRGB chunk with length 2 instead of 1
    tag = b"sRGB"
    data = b"\x00\x01"
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    chunk = struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)
    tampered_png = valid_png[:33] + chunk + valid_png[33:]
    (tmp_path / fn).write_bytes(tampered_png)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["screenshots"][0]["sha256"] = hashlib.sha256(tampered_png).hexdigest()
    manifest["screenshots"][0]["size"] = len(tampered_png)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = validate_artifact_dir(tmp_path)
    assert result.valid is False
    assert any("invalid length" in err for err in result.errors)

