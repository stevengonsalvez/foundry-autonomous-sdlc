from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.cd import artifact


def built_app(
    tmp_path: Path, js: str = 'h1("Track a parcel");document.title="Track a parcel"'
) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<div id="root"></div>')
    (dist / "assets" / "index-abc.js").write_text(js)
    (dist / "assets" / "index-abc.css").write_text("body{}")
    return dist


def test_stamp_writes_build_json_with_the_agreed_keys(tmp_path: Path) -> None:
    dist = built_app(tmp_path)
    artifact.stamp(
        dist,
        sha="a" * 40,
        short="aaaaaaa",
        run_id=7,
        version="v0.4.0",
        built_at="2026-10-11T09:00:00Z",
    )
    assert json.loads((dist / "build.json").read_text()) == {
        "sha": "a" * 40,
        "short": "aaaaaaa",
        "built_at": "2026-10-11T09:00:00Z",
        "run_id": 7,
        "version": "v0.4.0",
    }


def test_a_fault_is_recorded_in_build_json(tmp_path: Path) -> None:
    dist = built_app(tmp_path)
    artifact.stamp(
        dist, sha="a" * 40, short="a", run_id=7, version="v", built_at="t", fault="smoke"
    )
    assert json.loads((dist / "build.json").read_text())["fault"] == "smoke"


def test_stamp_refuses_a_directory_that_is_not_a_built_app(tmp_path: Path) -> None:
    with pytest.raises(artifact.ArtifactError, match=r"no index\.html"):
        artifact.stamp(tmp_path, sha="a", short="a", run_id=1, version="v", built_at="t")


def test_the_smoke_fault_breaks_the_built_heading_and_nothing_else(tmp_path: Path) -> None:
    dist = built_app(tmp_path)
    assert artifact.inject_smoke_fault(dist) == 1
    js = (dist / "assets" / "index-abc.js").read_text()
    assert "Track a parc3l" in js and "Track a parcel" not in js
    assert (dist / "assets" / "index-abc.css").read_text() == "body{}"


def test_injecting_into_a_build_without_the_heading_is_an_error_not_a_silent_pass(
    tmp_path: Path,
) -> None:
    with pytest.raises(artifact.ArtifactError, match="found no built script"):
        artifact.inject_smoke_fault(built_app(tmp_path, js="console.log(1)"))


def test_cli_stamps_with_and_without_a_fault(tmp_path: Path) -> None:
    dist = built_app(tmp_path)
    common = [
        "stamp",
        "--dist",
        str(dist),
        "--sha",
        "a" * 40,
        "--short",
        "aaaaaaa",
        "--run-id",
        "3",
        "--version",
        "main-aaaaaaa",
    ]
    assert artifact.main([*common, "--fault", "none"]) == 0
    assert "fault" not in json.loads((dist / "build.json").read_text())
    assert artifact.main(["fault-smoke", "--dist", str(dist)]) == 0
    assert artifact.main([*common, "--fault", "smoke"]) == 0
    assert json.loads((dist / "build.json").read_text())["fault"] == "smoke"
    assert artifact.main(["fault-smoke", "--dist", str(tmp_path / "missing")]) == 1
