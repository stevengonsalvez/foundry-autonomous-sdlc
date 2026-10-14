"""Unit tests for the App Evolution Showcase generator (generate_history.py).

Tests requirements:
1. Ordering: newest first (highest semver / latest commit date first).
2. Escaped untrusted titles from issues: XSS prevention.
3. Missing screenshots fixture: handled gracefully without crash.
4. Not reproducible tag fixture: records 'not reproducible: <reason>' in output.
5. New entry appended: adding a new release properly updates timeline and 'before' reference.
6. Size budget: verifies HTML < 50KB, CSS < 20KB, JS < 15KB.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from scripts.tests.ui.test_validate_artifact import make_test_png
from scripts.ui.generate_history import (
    BUDGET_CSS_BYTES,
    BUDGET_HTML_BYTES,
    BUDGET_JS_BYTES,
    ROUTES,
    VIEWPORTS,
    build_history_site,
    collect_evolution_entries,
    generate_css,
    generate_js,
    render_html,
)

# Minimal 1x1 valid PNG bytes
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360606060000000050001a7e48b520000000049454e44ae426082"
)


@pytest.fixture(autouse=True)
def mock_commit_metadata(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    if request.node.name == "test_get_commit_metadata_raises_on_invalid_ref":
        return

    def fake_meta(ref: str) -> dict[str, str]:
        return {
            "sha": f"0123456789abcdef0123456789abcdef{ref[:8]}",
            "date": "2026-10-10T12:00:00+00:00",
            "subject": f"Commit for {ref}",
        }

    monkeypatch.setattr("scripts.ui.generate_history.get_commit_metadata", fake_meta)


def create_release_fixture(
    dest_dir: Path,
    tag: str,
    routes: list[str] | None = None,
    viewports: list[str] | None = None,
    reproducible: bool = True,
    reason: str | None = None,
) -> None:
    tag_dir = dest_dir / tag
    tag_dir.mkdir(parents=True, exist_ok=True)

    if not reproducible:
        manifest = {
            "version": 1,
            "tag": tag,
            "commit_sha": "a1b2c3d4",
            "reproducible": False,
            "reason": reason or "Build failed: dependency missing",
            "screenshots": [],
        }
        (tag_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return

    routes = routes or ROUTES
    viewports = viewports or VIEWPORTS

    screenshots_meta = []
    for r in routes:
        for vp in viewports:
            fn = f"{r}-{vp}.png"
            (tag_dir / fn).write_bytes(TINY_PNG)
            screenshots_meta.append(
                {
                    "route": r,
                    "viewport": vp,
                    "filename": fn,
                    "sha256": "dummy",
                    "size_bytes": len(TINY_PNG),
                }
            )

    manifest = {
        "version": 1,
        "tag": tag,
        "commit_sha": "a1b2c3d4",
        "reproducible": True,
        "screenshots": screenshots_meta,
    }
    (tag_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_ordering() -> None:
    """Timeline entries must be ordered newest first (descending semver)."""
    with tempfile.TemporaryDirectory() as td:
        screenshots_dir = Path(td)
        for tag in ["v0.1.0", "v0.3.0", "v0.2.0", "v0.4.0", "v0.1.1"]:
            create_release_fixture(screenshots_dir, tag)

        state_data = {
            "tickets": [
                {"release": {"tag": "v0.1.0"}, "title": "Initial release"},
                {"release": {"tag": "v0.1.1"}, "title": "Patch bug"},
                {"release": {"tag": "v0.2.0"}, "title": "Feature carriers"},
                {"release": {"tag": "v0.3.0"}, "title": "Feature live updates"},
                {"release": {"tag": "v0.4.0"}, "title": "Feature maps"},
            ]
        }

        entries = collect_evolution_entries(
            state_data=state_data,
            screenshots_dir=screenshots_dir,
            tags=["v0.1.0", "v0.1.1", "v0.2.0", "v0.3.0", "v0.4.0"],
        )

        tags_ordered = [e["tag"] for e in entries]
        assert tags_ordered == ["v0.4.0", "v0.3.0", "v0.2.0", "v0.1.1", "v0.1.0"]

        # Verify before pointer: each entry's before is the next chronological entry
        assert entries[0]["before"]["tag"] == "v0.3.0"
        assert entries[1]["before"]["tag"] == "v0.2.0"
        assert entries[2]["before"]["tag"] == "v0.1.1"
        assert entries[3]["before"]["tag"] == "v0.1.0"
        assert entries[4]["before"] is None


def test_escaped_untrusted_titles_from_issues() -> None:
    """Untrusted issue titles and links must be HTML-escaped to prevent XSS."""
    with tempfile.TemporaryDirectory() as td:
        screenshots_dir = Path(td)
        create_release_fixture(screenshots_dir, "v0.2.0")

        malicious_title = '<script>alert("pwned")</script> & <b onmouseover="alert(1)">Carrier</b>'
        malicious_url = 'https://github.com/issues/1"><script>alert(2)</script>'

        state_data = {
            "tickets": [
                {
                    "release": {"tag": "v0.2.0"},
                    "title": malicious_title,
                    "issue": 42,
                    "url": malicious_url,
                    "pr": {"number": 55, "url": 'https://github.com/pull/55?param="><script>'},
                    "cost": {"total_usd": 0.045},
                }
            ]
        }

        entries = collect_evolution_entries(
            state_data=state_data,
            screenshots_dir=screenshots_dir,
            tags=["v0.2.0"],
        )

        html_out = render_html(entries)

        # Raw malicious scripts must NOT appear in output
        assert '<script>alert("pwned")</script>' not in html_out
        assert 'onmouseover="alert(1)"' not in html_out
        assert '"><script>' not in html_out

        # Escaped characters must be present
        assert "&lt;script&gt;alert(&quot;pwned&quot;)&lt;/script&gt;" in html_out
        assert "&amp;" in html_out


def test_missing_screenshots() -> None:
    """Missing routes or screenshots must be handled gracefully without crashing."""
    with tempfile.TemporaryDirectory() as td:
        screenshots_dir = Path(td)
        # Release with ONLY home desktop screenshot (missing other 7 routes/viewports)
        create_release_fixture(
            screenshots_dir,
            "v0.1.0",
            routes=["home"],
            viewports=["desktop"],
        )

        state_data = {"tickets": [{"release": {"tag": "v0.1.0"}, "title": "Minimal release"}]}

        out_dir = Path(td) / "out"
        payload = build_history_site(
            output_dir=out_dir,
            screenshots_dir=screenshots_dir,
            state_data=state_data,
            tags=["v0.1.0"],
        )

        assert payload["entries"][0]["screenshots"]["home"]["desktop"] == "home-desktop.png"
        assert (
            "parcel-found" not in payload["entries"][0]["screenshots"]
            or not payload["entries"][0]["screenshots"]["parcel-found"]
        )
        assert (out_dir / "index.html").exists()
        assert (out_dir / "data.json").exists()


def test_not_reproducible_tag() -> None:
    """Tags that fail to build must be flagged as not reproducible with the reason."""
    with tempfile.TemporaryDirectory() as td:
        screenshots_dir = Path(td)
        create_release_fixture(
            screenshots_dir,
            "v0.1.0",
            reproducible=False,
            reason="Legacy webpack 4 configuration failed under Node 22",
        )

        state_data = {"tickets": [{"release": {"tag": "v0.1.0"}, "title": "Old build"}]}

        out_dir = Path(td) / "out"
        payload = build_history_site(
            output_dir=out_dir,
            screenshots_dir=screenshots_dir,
            state_data=state_data,
            tags=["v0.1.0"],
        )

        entry = payload["entries"][0]
        assert entry["reproducible"] is False
        assert "Legacy webpack 4" in entry["not_reproducible_reason"]

        html_content = (out_dir / "index.html").read_text(encoding="utf-8")
        assert "Not Reproducible" in html_content
        assert "Reason: Legacy webpack 4 configuration failed under Node 22" in html_content


def test_new_entry_appended() -> None:
    """Adding a new release entry updates the timeline and connects before/after."""
    with tempfile.TemporaryDirectory() as td:
        screenshots_dir = Path(td)
        create_release_fixture(screenshots_dir, "v0.1.0")
        create_release_fixture(screenshots_dir, "v0.2.0")

        state_data = {
            "tickets": [
                {"release": {"tag": "v0.1.0"}, "title": "Version 1"},
                {"release": {"tag": "v0.2.0"}, "title": "Version 2"},
            ]
        }

        out_dir = Path(td) / "out"
        p1 = build_history_site(
            output_dir=out_dir,
            screenshots_dir=screenshots_dir,
            state_data=state_data,
            tags=["v0.1.0", "v0.2.0"],
        )
        assert len(p1["entries"]) == 2
        assert p1["entries"][0]["tag"] == "v0.2.0"

        # Append new entry v0.3.0
        create_release_fixture(screenshots_dir, "v0.3.0")
        state_data["tickets"].append({"release": {"tag": "v0.3.0"}, "title": "Version 3"})

        p2 = build_history_site(
            output_dir=out_dir,
            screenshots_dir=screenshots_dir,
            state_data=state_data,
            tags=["v0.1.0", "v0.2.0", "v0.3.0"],
        )
        assert len(p2["entries"]) == 3
        assert p2["entries"][0]["tag"] == "v0.3.0"
        assert p2["entries"][0]["before"]["tag"] == "v0.2.0"
        assert p2["entries"][1]["before"]["tag"] == "v0.1.0"


def test_size_budget() -> None:
    """Generated assets must strictly adhere to the stated size budgets."""
    css = generate_css()
    js = generate_js()
    assert len(css.encode("utf-8")) < BUDGET_CSS_BYTES
    assert len(js.encode("utf-8")) < BUDGET_JS_BYTES

    # Test with 30 releases
    entries = []
    for i in range(30, 0, -1):
        tag = f"v0.{i}.0"
        entries.append(
            {
                "tag": tag,
                "commit_sha": f"sha{i:04d}",
                "short_sha": f"sha{i:04d}"[:8],
                "date": "2026-10-14T08:00:00Z",
                "title": f"Feature release number {i} with a detailed description",
                "issue_number": 100 + i,
                "issue_url": f"https://github.com/issues/{100 + i}",
                "pr_number": 200 + i,
                "pr_url": f"https://github.com/pull/{200 + i}",
                "cost_usd": 0.042 * i,
                "reproducible": True,
                "not_reproducible_reason": None,
                "screenshots": {r: {vp: f"{r}-{vp}.png" for vp in VIEWPORTS} for r in ROUTES},
                "before": {
                    "tag": f"v0.{i - 1}.0",
                    "reproducible": True,
                    "screenshots": {r: {vp: f"{r}-{vp}.png" for vp in VIEWPORTS} for r in ROUTES},
                }
                if i > 1
                else None,
            }
        )

    html_str = render_html(entries)
    html_bytes = len(html_str.encode("utf-8"))
    assert html_bytes < BUDGET_HTML_BYTES, (
        f"HTML ({html_bytes} bytes) exceeds budget of {BUDGET_HTML_BYTES} bytes"
    )


def test_update_history_validates_untrusted_artifacts() -> None:
    """update_history must reject invalid artifacts and update valid ones."""
    from scripts.ui.update_history import update_history

    with tempfile.TemporaryDirectory() as td:
        temp_dir = Path(td)
        artifacts_dir = temp_dir / "untrusted_artifacts"
        artifacts_dir.mkdir()

        import hashlib

        desktop_png = make_test_png(1280, 800)
        png_sha = hashlib.sha256(desktop_png).hexdigest()
        manifest_data = {
            "version": 1,
            "head_sha": "1234567890abcdef1234567890abcdef12345678",
            "screenshots": [
                {
                    "route": "home",
                    "viewport": "desktop",
                    "filename": "home-desktop.png",
                    "sha256": png_sha,
                    "size": len(desktop_png),
                }
            ],
        }
        (artifacts_dir / "home-desktop.png").write_bytes(desktop_png)
        (artifacts_dir / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

        mock_repo = temp_dir / "repo"
        (mock_repo / "history" / "screenshots").mkdir(parents=True)

        res = update_history(
            artifacts_dir=artifacts_dir,
            repo="",
            key="v0.5.0",
            push=False,
            repo_root=mock_repo,
        )
        assert res["key"] == "v0.5.0"
        assert len(res["screenshots"]) == 1
        assert res["screenshots"][0]["route"] == "home"

        # Corrupt file: not a PNG
        (artifacts_dir / "home-desktop.png").write_bytes(b"NOT A PNG FILE")
        with pytest.raises(RuntimeError, match="Artifact validation failed"):
            update_history(
                artifacts_dir=artifacts_dir,
                repo="",
                key="v0.5.0",
                push=False,
                repo_root=mock_repo,
            )


def test_tag_regex_filtering() -> None:
    r"""Only tags matching ^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$ should be collected."""
    with tempfile.TemporaryDirectory() as td:
        screenshots_dir = Path(td)
        entries = collect_evolution_entries(
            state_data={},
            screenshots_dir=screenshots_dir,
            tags=["v0.1.0", "v0.2.0-rc1", "invalid-tag", "v1.2", "v0.3.0"],
        )
        assert [e["tag"] for e in entries] == ["v0.3.0", "v0.1.0"]


def test_older_entries_disclosure_collapses_more_than_five() -> None:
    """Releases exceeding 5 should be collapsed and rendered as compact rows."""
    entries = []
    for i in range(10, 0, -1):
        entries.append(
            {
                "tag": f"v0.{i}.0",
                "commit_sha": f"sha{i}",
                "short_sha": f"sha{i}"[:8],
                "date": "2026-10-10T12:00:00Z",
                "title": f"Release {i}",
                "reproducible": True,
                "screenshots": {},
            }
        )
    html_out = render_html(entries)
    assert '<details class="older-entries-disclosure">' in html_out
    assert '<summary class="older-entries-summary">Older releases (5)</summary>' in html_out
    assert "timeline-item-compact" in html_out


def test_v031_issue_label_pr_only() -> None:
    """v0.3.1 must derive issue_label = 'PR only' from state ledger where issue == pr."""
    with tempfile.TemporaryDirectory() as td:
        screenshots_dir = Path(td)
        create_release_fixture(screenshots_dir, "v0.3.1")
        state_data = {
            "tickets": [
                {
                    "release": {"tag": "v0.3.1"},
                    "kind": "pr",
                    "issue": 40,
                    "pr": {
                        "number": 40,
                        "url": "https://github.com/stevengonsalvez/foundry-autonomous-sdlc/pull/40",
                    },
                }
            ]
        }
        entries = collect_evolution_entries(
            state_data=state_data,
            screenshots_dir=screenshots_dir,
            tags=["v0.3.1"],
        )
        assert entries[0]["issue_label"] == "PR only"
        assert entries[0]["issue_number"] is None
        html_out = render_html(entries)
        assert '<span class="badge">PR only</span>' in html_out
        assert "issue #" not in html_out
        assert "pr #40" in html_out


def test_budget_exceeded_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hard budget limits for CSS must raise ValueError."""
    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td) / "out"
        screenshots_dir = Path(td) / "screenshots"
        create_release_fixture(screenshots_dir, "v0.1.0")

        import scripts.ui.generate_history as gh

        monkeypatch.setattr(gh, "BUDGET_CSS_BYTES", 10)
        with pytest.raises(ValueError, match="CSS exceeds size budget"):
            build_history_site(
                output_dir=out_dir,
                screenshots_dir=screenshots_dir,
                state_data={},
                tags=["v0.1.0"],
            )


def test_shallow_clone_raises_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """When releases/ exist on disk but git has 0 tags (shallow checkout), generator must raise."""
    import subprocess

    with tempfile.TemporaryDirectory() as td:
        screenshots_dir = Path(td)
        create_release_fixture(screenshots_dir, "v0.1.0")

        original_run = subprocess.run

        def mock_run(cmd, *args, **kwargs):
            if cmd == ["git", "tag", "-l", "v*"]:

                class MockResult:
                    returncode = 0
                    stdout = ""
                    stderr = ""

                return MockResult()
            return original_run(cmd, *args, **kwargs)

        monkeypatch.setattr(subprocess, "run", mock_run)
        with pytest.raises(
            RuntimeError,
            match=r"Found 1 release directories .* but git repository has 0 tags",
        ):
            collect_evolution_entries(
                state_data={},
                screenshots_dir=screenshots_dir,
                tags=None,
            )


def test_get_commit_metadata_raises_on_invalid_ref() -> None:
    """get_commit_metadata must raise RuntimeError on unknown/invalid refs."""
    from scripts.ui.generate_history import get_commit_metadata

    with pytest.raises(RuntimeError, match="Cannot resolve commit metadata"):
        get_commit_metadata("nonexistent-ref-00000000")
