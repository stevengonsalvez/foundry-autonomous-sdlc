"""
Artifact validator for UI screenshots (docs/architecture.md, ui-proof workflow).

Treats downloaded workflow artifacts as untrusted data:
- Only *.png files and manifest.json
- Strict file count, single-file size, and total size limits
- Reject path traversals, symlinks, hidden files, non-regular files
- Verify PNG magic bytes (89 50 4E 47 0D 0A 1A 0A)
- Verify manifest.json schema and exact SHA-256 and byte size matches
- State-aware manifests (scripts/ui/states.json): state ids, titles and captions come from
  a PR-controlled file and end up in PR comments, so they are restricted to a tiny safe
  charset and each filename must be exactly <state>-<viewport>.png
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PNG_MAGIC_BYTES = b"\x89PNG\r\n\x1a\n"
MAX_FILE_COUNT = 64  # manifest.json + up to 63 PNGs (states x viewports)
MIN_SCREENSHOT_COUNT = 1
MAX_SINGLE_FILE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_MANIFEST_BYTES = 64 * 1024  # 64 KB
MAX_TOTAL_BYTES = 20 * 1024 * 1024  # 20 MB

SAFE_PNG_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+\.png$")
SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
ROUTE_RE = re.compile(r"^(home|parcel-found|not-found|invalid-input)$")
VIEWPORT_RE = re.compile(r"^(desktop|mobile)$")
STATE_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_STATE_ID_LEN = 40
# Letters, digits, space and . , : ; ' ( ) / + - only: no markup, links, mentions,
# backticks, newlines or HTML comment markers can survive into a PR comment.
TEXT_RE = re.compile(r"^[A-Za-z0-9 .,:;'()/+-]+$")
MAX_TITLE_LEN = 60
MAX_CAPTION_LEN = 160
MAX_SKIPPED = 64

# Manifests written before states existed carry only a route; map them onto state ids.
LEGACY_ROUTE_STATES = {
    "home": "home-default",
    "parcel-found": "parcel-timeline",
    "not-found": "parcel-not-found",
    "invalid-input": "parcel-invalid-input",
}


def state_id_of(item: dict[str, Any]) -> str | None:
    """State id of a manifest entry, falling back to the legacy route mapping."""
    state = item.get("state")
    if isinstance(state, str) and state:
        return state
    return LEGACY_ROUTE_STATES.get(str(item.get("route")))

ALLOWED_CHUNK_TYPES: frozenset[bytes] = frozenset(
    {b"IHDR", b"IDAT", b"IEND", b"sRGB", b"gAMA", b"pHYs"}
)
EXACT_CHUNK_LENGTHS: dict[bytes, int] = {
    b"IHDR": 13,
    b"sRGB": 1,
    b"gAMA": 4,
    b"pHYs": 9,
    b"IEND": 0,
}

ALLOWED_DIMENSIONS = {
    "desktop": (1280, 800),
    "mobile": (390, 844),
}


def validate_png_bytes(
    content: bytes, filename: str, expected_viewport: str | None = None
) -> list[str]:
    """Parse PNG chunks, enforce dimensions, allowlist chunk types and verify CRC."""
    errs: list[str] = []
    if len(content) < 33 or not content.startswith(PNG_MAGIC_BYTES):
        return [f"File {filename} does not have valid PNG magic bytes header"]

    # Chunk 1 must be IHDR
    ihdr_len, ihdr_type = struct.unpack(">I4s", content[8:16])
    if ihdr_type != b"IHDR" or ihdr_len != 13:
        return [f"File {filename} missing valid PNG IHDR chunk"]

    width, height = struct.unpack(">II", content[16:24])

    if expected_viewport:
        if expected_viewport not in ALLOWED_DIMENSIONS:
            errs.append(f"File {filename} has unknown expected viewport: {expected_viewport}")
        else:
            exp_w, exp_h = ALLOWED_DIMENSIONS[expected_viewport]
            if (width, height) != (exp_w, exp_h):
                errs.append(
                    f"File {filename} dimensions {width}x{height} do not match "
                    f"expected {exp_w}x{exp_h} for {expected_viewport}"
                )
    else:
        if (width, height) not in ALLOWED_DIMENSIONS.values():
            errs.append(
                f"File {filename} dimensions {width}x{height} not permitted "
                "(must be 1280x800 or 390x844)"
            )

    # Walk chunks to ensure proper framing, allowed chunk types, CRC and IEND terminal chunk
    pos = 8
    found_iend = False
    ihdr_count = 0
    while pos + 12 <= len(content):
        chunk_len, chunk_type = struct.unpack(">I4s", content[pos : pos + 8])
        chunk_data_end = pos + 8 + chunk_len
        crc_end = chunk_data_end + 4
        if crc_end > len(content):
            errs.append(
                f"File {filename} has truncated PNG chunk "
                f"{chunk_type.decode('latin1', errors='replace')}"
            )
            return errs

        if chunk_type not in ALLOWED_CHUNK_TYPES:
            errs.append(
                f"File {filename} has disallowed PNG chunk type "
                f"{chunk_type.decode('latin1', errors='replace')}"
            )
            return errs

        if chunk_type == b"IHDR":
            ihdr_count += 1
            if ihdr_count > 1:
                errs.append(f"File {filename} has multiple IHDR chunks")
                return errs

        if chunk_type in EXACT_CHUNK_LENGTHS:
            exp_len = EXACT_CHUNK_LENGTHS[chunk_type]
            if chunk_len != exp_len:
                errs.append(
                    f"File {filename} chunk {chunk_type.decode('latin1', errors='replace')} "
                    f"has invalid length {chunk_len} (expected {exp_len})"
                )
                return errs

        chunk_data = content[pos + 8 : chunk_data_end]
        (expected_crc,) = struct.unpack(">I", content[chunk_data_end:crc_end])
        computed_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if computed_crc != expected_crc:
            errs.append(
                f"File {filename} chunk {chunk_type.decode('latin1', errors='replace')} "
                f"has invalid CRC: expected {expected_crc:#010x}, computed {computed_crc:#010x}"
            )
            return errs

        if chunk_type == b"IEND":
            found_iend = True
            if crc_end != len(content):
                errs.append(f"File {filename} has extraneous data appended after PNG IEND chunk")
            break

        pos = crc_end

    if not found_iend:
        errs.append(f"File {filename} missing PNG IEND chunk")
    if ihdr_count != 1:
        errs.append(f"File {filename} missing PNG IHDR chunk")

    return errs


class ArtifactValidationError(ValueError):
    """Raised when an artifact violates security or format rules."""


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    manifest: dict[str, Any] | None = None
    manifest_sha256: str = ""
    screenshots: list[dict[str, Any]] = field(default_factory=list)


def _check_not_symlink(path: Path) -> None:
    if path.is_symlink() or os.path.islink(path):
        raise ArtifactValidationError(f"Symlink detected: {path.name}")
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode):
        raise ArtifactValidationError(f"Symlink mode detected: {path.name}")


def validate_artifact_dir(artifact_dir: str | Path) -> ValidationResult:
    root = Path(artifact_dir).resolve()
    if not root.is_dir():
        return ValidationResult(valid=False, errors=[f"Artifact directory does not exist: {root}"])

    errors: list[str] = []

    try:
        _check_not_symlink(root)
    except ArtifactValidationError as exc:
        return ValidationResult(valid=False, errors=[str(exc)])

    # List all entries directly in root (no subdirectories allowed)
    entries: list[Path] = []
    total_size = 0
    try:
        for entry in root.iterdir():
            _check_not_symlink(entry)
            # Ensure resolved path is strictly inside root
            resolved_entry = entry.resolve()
            if not resolved_entry.is_relative_to(root):
                return ValidationResult(
                    valid=False, errors=[f"Path traversal detected: {entry.name}"]
                )

            if entry.is_dir():
                return ValidationResult(
                    valid=False,
                    errors=[f"Subdirectories not permitted in artifact: {entry.name}"],
                )

            if not entry.is_file():
                return ValidationResult(
                    valid=False, errors=[f"Non-regular file detected: {entry.name}"]
                )

            st_size = entry.stat().st_size
            if entry.name != "manifest.json" and st_size > MAX_SINGLE_FILE_BYTES:
                msg = f"File {entry.name} size {st_size} exceeds max {MAX_SINGLE_FILE_BYTES} bytes"
                return ValidationResult(valid=False, errors=[msg])

            entries.append(entry)
    except ArtifactValidationError as exc:
        return ValidationResult(valid=False, errors=[str(exc)])
    except OSError as exc:
        return ValidationResult(valid=False, errors=[f"Filesystem error scanning artifact: {exc}"])

    if len(entries) > MAX_FILE_COUNT:
        return ValidationResult(
            valid=False,
            errors=[f"File count {len(entries)} exceeds limit {MAX_FILE_COUNT}"],
        )

    # Check allowed file names and types
    manifest_path: Path | None = None
    png_files: dict[str, Path] = {}

    for entry in entries:
        name = entry.name
        # Reject hidden files or path traversal elements
        if name.startswith(".") or "/" in name or "\\" in name:
            return ValidationResult(valid=False, errors=[f"Illegal file name: {name}"])

        if name == "manifest.json":
            manifest_path = entry
        elif SAFE_PNG_NAME_RE.fullmatch(name):
            png_files[name] = entry
        else:
            return ValidationResult(valid=False, errors=[f"Disallowed file in artifact: {name}"])

    if manifest_path is None:
        return ValidationResult(valid=False, errors=["Missing manifest.json in artifact"])

    if not png_files:
        return ValidationResult(valid=False, errors=["No PNG screenshots found in artifact"])

    # Validate manifest.json size and read content
    manifest_size = manifest_path.stat().st_size
    if manifest_size > MAX_MANIFEST_BYTES:
        return ValidationResult(
            valid=False,
            errors=[f"manifest.json size {manifest_size} exceeds {MAX_MANIFEST_BYTES} bytes"],
        )

    try:
        manifest_raw = manifest_path.read_bytes()
        manifest_sha256 = hashlib.sha256(manifest_raw).hexdigest()
        manifest_data = json.loads(manifest_raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return ValidationResult(valid=False, errors=[f"Invalid manifest.json: {exc}"])

    total_size += manifest_size

    # Validate manifest schema
    if not isinstance(manifest_data, dict):
        return ValidationResult(valid=False, errors=["manifest.json root must be an object"])

    if manifest_data.get("version") != 1:
        return ValidationResult(valid=False, errors=["manifest.json version must be 1"])

    screenshots_list = manifest_data.get("screenshots")
    if not isinstance(screenshots_list, list) or len(screenshots_list) < MIN_SCREENSHOT_COUNT:
        return ValidationResult(
            valid=False,
            errors=["manifest.json must contain non-empty 'screenshots' array"],
        )

    manifest_entries_by_filename: dict[str, dict[str, Any]] = {}
    seen_state_viewports: set[tuple[str, str]] = set()

    skipped = manifest_data.get("skipped")
    if skipped is not None:
        if not isinstance(skipped, list) or len(skipped) > MAX_SKIPPED:
            errors.append(
                f"manifest.json skipped must be a list of at most {MAX_SKIPPED} state ids"
            )
        else:
            for sid in skipped:
                if (
                    not isinstance(sid, str)
                    or len(sid) > MAX_STATE_ID_LEN
                    or not STATE_ID_RE.fullmatch(sid)
                ):
                    errors.append(f"manifest.json skipped has invalid state id: {sid!r}")

    for i, item in enumerate(screenshots_list):
        if not isinstance(item, dict):
            errors.append(f"manifest.json screenshots[{i}] must be an object")
            continue

        filename = item.get("filename")
        route = item.get("route")
        viewport = item.get("viewport")
        expected_sha = item.get("sha256")
        expected_size = item.get("size")

        if not isinstance(filename, str) or not SAFE_PNG_NAME_RE.fullmatch(filename):
            errors.append(f"screenshots[{i}] has invalid or unsafe filename: {filename!r}")
            continue

        if not isinstance(route, str) or not ROUTE_RE.fullmatch(route):
            errors.append(f"screenshots[{i}] has invalid route: {route!r}")

        if not isinstance(viewport, str) or not VIEWPORT_RE.fullmatch(viewport):
            errors.append(f"screenshots[{i}] has invalid viewport: {viewport!r}")

        if not isinstance(expected_sha, str) or not SHA256_HEX_RE.fullmatch(expected_sha):
            errors.append(f"screenshots[{i}] has invalid sha256 hash: {expected_sha!r}")

        if type(expected_size) is not int or expected_size < 0:
            errors.append(f"screenshots[{i}] has invalid size: {expected_size!r}")

        if "state" in item:
            state = item["state"]
            if (
                not isinstance(state, str)
                or len(state) > MAX_STATE_ID_LEN
                or not STATE_ID_RE.fullmatch(state)
            ):
                errors.append(f"screenshots[{i}] has invalid state: {state!r}")
            elif isinstance(viewport, str) and filename != f"{state}-{viewport}.png":
                errors.append(
                    f"screenshots[{i}] filename {filename!r} does not match state/viewport "
                    f"({state}-{viewport}.png)"
                )
            elif (state, str(viewport)) in seen_state_viewports:
                errors.append(f"Duplicate state/viewport in manifest: {state}/{viewport}")
            else:
                seen_state_viewports.add((state, str(viewport)))

        for key, limit in (("title", MAX_TITLE_LEN), ("caption", MAX_CAPTION_LEN)):
            if key in item:
                text = item[key]
                if not isinstance(text, str) or not 0 < len(text) <= limit or not TEXT_RE.fullmatch(
                    text
                ):
                    errors.append(f"screenshots[{i}] has invalid {key}: {text!r}")

        if filename in manifest_entries_by_filename:
            errors.append(f"Duplicate filename in manifest: {filename}")
        manifest_entries_by_filename[filename] = item

    if errors:
        return ValidationResult(valid=False, errors=errors)

    # Verify set equality between files on disk and manifest entries
    disk_png_names = set(png_files.keys())
    manifest_png_names = set(manifest_entries_by_filename.keys())

    if disk_png_names != manifest_png_names:
        missing_on_disk = manifest_png_names - disk_png_names
        unlisted_on_disk = disk_png_names - manifest_png_names
        detail = []
        if missing_on_disk:
            detail.append(f"missing on disk: {sorted(missing_on_disk)}")
        if unlisted_on_disk:
            detail.append(f"unlisted on disk: {sorted(unlisted_on_disk)}")
        return ValidationResult(
            valid=False,
            errors=[f"Manifest and disk contents mismatch: {', '.join(detail)}"],
        )

    # Validate each PNG file on disk
    validated_screenshots: list[dict[str, Any]] = []

    for name, path in png_files.items():
        st_size = path.stat().st_size
        total_size += st_size

        if st_size > MAX_SINGLE_FILE_BYTES:
            errors.append(
                f"File {name} size {st_size} exceeds maximum {MAX_SINGLE_FILE_BYTES} bytes"
            )
            continue

        item_meta = manifest_entries_by_filename[name]
        expected_size = item_meta["size"]
        expected_sha = item_meta["sha256"]

        if st_size != expected_size:
            errors.append(
                f"File {name} size mismatch: manifest expected {expected_size}, got {st_size}"
            )
            continue

        try:
            content = path.read_bytes()
        except OSError as exc:
            errors.append(f"Failed to read {name}: {exc}")
            continue

        # PNG structure, magic bytes, and dimensions check
        png_errs = validate_png_bytes(content, name, expected_viewport=item_meta.get("viewport"))
        if png_errs:
            errors.extend(png_errs)
            continue

        actual_sha = hashlib.sha256(content).hexdigest()
        if actual_sha != expected_sha:
            errors.append(
                f"File {name} sha256 mismatch: manifest expected {expected_sha}, got {actual_sha}"
            )
            continue

        validated_screenshots.append(item_meta)

    if total_size > MAX_TOTAL_BYTES:
        errors.append(f"Total artifact size {total_size} exceeds {MAX_TOTAL_BYTES} bytes")

    if errors:
        return ValidationResult(valid=False, errors=errors)

    return ValidationResult(
        valid=True,
        manifest=manifest_data,
        manifest_sha256=manifest_sha256,
        screenshots=validated_screenshots,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate screenshot artifact directory.")
    parser.add_argument("artifact_dir", help="Path to unpacked artifact directory")
    args = parser.parse_args()

    result = validate_artifact_dir(args.artifact_dir)
    if not result.valid:
        print("Artifact validation failed:", file=sys.stderr)
        for err in result.errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)

    print(f"Artifact valid: {len(result.screenshots)} screenshots verified.")
    print(f"Manifest sha256: {result.manifest_sha256}")


if __name__ == "__main__":
    main()
