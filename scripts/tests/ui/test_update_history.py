"""Unit tests for release key resolution and history update automation."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from scripts.ui.update_history import parse_semver_tag, resolve_release_key


def test_parse_semver_tag() -> None:
    assert parse_semver_tag("v0.1.0") == (0, 1, 0)
    assert parse_semver_tag("v1.2.3") == (1, 2, 3)
    assert parse_semver_tag("not-a-tag") == (999, 999, 999)


def test_resolve_release_key_points_at_with_prod_tag() -> None:
    """When both prod/ and v0.4.0 tags point at HEAD, v0.4.0 must be selected."""
    # Mock git tag --points-at HEAD to return both prod tag and semver tag
    tags_output = "prod/20261012-001759-110ea16\nv0.4.0\n"

    def mock_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "tag" in cmd and "--points-at" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=tags_output, stderr="")
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="110ea16123456789\n", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="error")

    with patch("scripts.ui.update_history.subprocess.run", side_effect=mock_run):
        key, sha = resolve_release_key(Path("."))
        assert key == "v0.4.0"
        assert sha == "110ea16123456789"


def test_resolve_release_key_picks_highest_semver_tag() -> None:
    """When multiple semver tags point at HEAD, the highest semver must be selected."""
    tags_output = "v0.1.0\nv0.2.0\nv0.1.1\n"

    def mock_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "tag" in cmd and "--points-at" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=tags_output, stderr="")
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="aabbccdd12345678\n", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

    with patch("scripts.ui.update_history.subprocess.run", side_effect=mock_run):
        key, sha = resolve_release_key(Path("."))
        assert key == "v0.2.0"
        assert sha == "aabbccdd12345678"


def test_resolve_release_key_falls_back_to_sha_when_only_prod_tag() -> None:
    """When only prod/ tag points at HEAD (no v* tag), fall back to short commit SHA."""
    tags_output = "prod/20261012-001759-110ea16\n"

    def mock_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "tag" in cmd and "--points-at" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=tags_output, stderr="")
        if "rev-parse" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="110ea16123456789\n", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

    with patch("scripts.ui.update_history.subprocess.run", side_effect=mock_run):
        key, sha = resolve_release_key(Path("."))
        assert key == "110ea161"
        assert sha == "110ea16123456789"
