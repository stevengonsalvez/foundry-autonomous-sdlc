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
import re
import tempfile
from pathlib import Path

import pytest

from scripts.tests.ui.test_validate_artifact import make_test_png
from scripts.ui.generate_history import (
    BUDGET_CSS_BYTES,
    BUDGET_HTML_BYTES,
    BUDGET_JS_BYTES,
    MAX_CHANGE_BLOCKS,
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
    if request.node.name in (
        "test_get_commit_metadata_raises_on_invalid_ref",
        "test_get_commit_metadata_utc_date_with_tz_offset",
    ):
        return

    def fake_meta(ref: str, repo_root: Path | None = None) -> dict[str, str]:
        return {
            "sha": f"0123456789abcdef0123456789abcdef{ref[:8]}",
            "date": "2026-10-10T12:00:00Z",
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

        # screenshots are keyed by state id; a legacy `home` route is the home-default state
        screenshots = payload["entries"][0]["screenshots"]
        assert screenshots["home-default"]["desktop"] == "home-desktop.png"
        assert "parcel-timeline" not in screenshots
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
    # Assert every single entry is present in the output (no silent dropping)
    assert all(e["tag"] in html_str for e in entries)
    assert html_str.count('class="timeline-item">') == 5
    assert html_str.count('timeline-item-compact') == 25


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


def test_get_commit_metadata_utc_date_with_tz_offset() -> None:
    """get_commit_metadata must convert non-UTC committer tz (+01:00) to UTC (Z)."""
    import os
    import subprocess

    from scripts.ui.generate_history import get_commit_metadata

    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["git", "init"], cwd=td, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=td, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=td, check=True)
        (Path(td) / "test.txt").write_text("content", encoding="utf-8")
        subprocess.run(["git", "add", "test.txt"], cwd=td, check=True)
        env = os.environ.copy()
        env["GIT_COMMITTER_DATE"] = "2026-10-10T12:30:00+01:00"
        env["GIT_AUTHOR_DATE"] = "2026-10-10T12:30:00+01:00"
        subprocess.run(
            ["git", "commit", "-m", "Commit with offset tz"],
            cwd=td,
            env=env,
            check=True,
            capture_output=True,
        )

        meta = get_commit_metadata("HEAD", repo_root=Path(td))
        assert meta["date"] == "2026-10-10T11:30:00Z"
        assert meta["subject"] == "Commit with offset tz"


def test_render_html_raises_when_over_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """When HTML exceeds budget, it must raise ValueError rather than dropping entries."""
    import scripts.ui.generate_history as gh

    entries = [
        {
            "tag": f"v0.{i}.0",
            "commit_sha": f"sha{i:04d}",
            "short_sha": f"sha{i:04d}"[:8],
            "date": "2026-10-14T08:00:00Z",
            "title": f"Feature release {i}",
            "issue_number": 100 + i,
            "issue_url": f"https://github.com/issues/{100 + i}",
            "pr_number": 200 + i,
            "pr_url": f"https://github.com/pull/{200 + i}",
            "cost_usd": 0.05,
            "reproducible": True,
            "not_reproducible_reason": None,
            "screenshots": {r: {vp: f"{r}-{vp}.png" for vp in VIEWPORTS} for r in ROUTES},
            "before": None,
        }
        for i in range(5, 0, -1)
    ]
    # Set an artificially small budget
    monkeypatch.setattr(gh, "BUDGET_HTML_BYTES", 500)
    with pytest.raises(ValueError, match="exceeds budget"):
        render_html(entries)


def test_collect_evolution_entries_retains_zero_cost() -> None:
    """Explicit None check must retain cost_usd 0.0 (not drop to None)."""
    with tempfile.TemporaryDirectory() as td:
        screenshots_dir = Path(td)
        create_release_fixture(screenshots_dir, "v0.1.0")
        state_data = {
            "tickets": [
                {
                    "release": {"tag": "v0.1.0"},
                    "title": "Free tier release",
                    "cost": {"total_usd": 0.0},
                }
            ]
        }
        entries = collect_evolution_entries(state_data, screenshots_dir, tags=["v0.1.0"])
        assert entries[0]["cost_usd"] == 0.0

        # Also when usd is 0.0 and total_usd is None
        state_data_2 = {
            "tickets": [
                {
                    "release": {"tag": "v0.1.0"},
                    "title": "Free tier release",
                    "cost": {"total_usd": None, "usd": 0.0},
                }
            ]
        }
        entries_2 = collect_evolution_entries(state_data_2, screenshots_dir, tags=["v0.1.0"])
        assert entries_2[0]["cost_usd"] == 0.0


def test_collect_evolution_entries_handles_malformed_ledger_types() -> None:
    """Malformed issue, PR or cost fields must not crash the Pages deploy."""
    with tempfile.TemporaryDirectory() as td:
        screenshots_dir = Path(td)
        create_release_fixture(screenshots_dir, "v0.1.0")
        state_data = {
            "tickets": [
                {
                    "release": {"tag": "v0.1.0"},
                    "title": "Bad types ticket",
                    "issue": "not-an-int",
                    "pr": {"number": "not-an-int", "url": "https://example.com"},
                    "cost": {"total_usd": "invalid-float"},
                }
            ]
        }
        entries = collect_evolution_entries(state_data, screenshots_dir, tags=["v0.1.0"])
        assert entries[0]["issue_number"] is None
        assert entries[0]["pr_number"] is None
        assert entries[0]["cost_usd"] is None


def test_csp_disallows_raw_githubusercontent() -> None:
    """CSP must not allow external requests to raw.githubusercontent.com."""
    from scripts.ui.generate_history import CSP_CONTENT

    assert "https://raw.githubusercontent.com" not in CSP_CONTENT
    assert "img-src 'self' data:;" in CSP_CONTENT


def test_uncaptured_release_does_not_produce_404_images() -> None:
    """A release without captured screenshots (such as v0.5.0 before captures are synced)
    must not render <img> tags referencing non-existent files on disk.
    """
    import re

    with tempfile.TemporaryDirectory() as td:
        screenshots_dir = Path(td) / "screenshots"
        screenshots_dir.mkdir()
        create_release_fixture(screenshots_dir, "v0.1.0")
        create_release_fixture(screenshots_dir, "v0.4.0")
        # v0.5.0 has NO screenshot directory (uncaptured / not reproducible)

        state_data = {
            "tickets": [
                {
                    "release": {"tag": "v0.5.0"},
                    "title": "feat(web): display event location pin in parcel timeline",
                    "issue": 83,
                    "pr": {
                        "number": 86,
                        "url": "https://github.com/stevengonsalvez/foundry-autonomous-sdlc/pull/86",
                    },
                    "cost": {"total_usd": 0.220416},
                },
                {
                    "release": {"tag": "v0.4.0"},
                    "title": "feat(web): add tracking number copy button",
                },
                {
                    "release": {"tag": "v0.1.0"},
                    "title": "feat(web): initial release",
                },
            ]
        }

        out_dir = Path(td) / "out"
        build_history_site(
            output_dir=out_dir,
            screenshots_dir=screenshots_dir,
            state_data=state_data,
            tags=["v0.1.0", "v0.4.0", "v0.5.0"],
        )

        html_content = (out_dir / "index.html").read_text(encoding="utf-8")

        # Extract all <img src="..."> references
        img_srcs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html_content)
        assert len(img_srcs) > 0

        # Every image tag in the generated HTML MUST exist on disk in out_dir (no 404s)
        for src in img_srcs:
            clean_src = src.removeprefix("./")
            file_on_disk = out_dir / clean_src
            msg = f"Image referenced in HTML does not exist (would 404): {src}"
            assert file_on_disk.exists(), msg



# ---- states: what changed per release ------------------------------------------------

STATE_META = {
    "home-default": ("Home", "Home page default."),
    "home-dark": ("Home, dark theme", "Home page in dark theme."),
    "parcel-timeline": ("Parcel timeline", "Parcel shipment history."),
    "parcel-copy-link": ("Parcel, copy link", "Copied confirmation."),
}


def create_state_release(
    dest_dir: Path,
    tag: str,
    states: dict[str, str],
    *,
    precomputed: dict | None = None,
    extra: dict[str, dict] | None = None,
) -> None:
    """states: state id -> sha256 stand-in. Two viewports each, tiny PNG files."""
    tag_dir = dest_dir / tag
    tag_dir.mkdir(parents=True, exist_ok=True)
    shots = []
    for sid, sha in states.items():
        title, caption = STATE_META.get(sid, (sid, ""))
        for vp in VIEWPORTS:
            fn = f"{sid}-{vp}.png"
            (tag_dir / fn).write_bytes(TINY_PNG)
            item = {
                "filename": fn,
                "state": sid,
                "route": "home",
                "viewport": vp,
                "title": title,
                "caption": caption,
                "sha256": sha,
                "size": len(TINY_PNG),
                **((extra or {}).get(sid, {})),
            }
            shots.append(item)
    manifest: dict = {"version": 1, "tag": tag, "reproducible": True, "screenshots": shots}
    if precomputed is not None:
        manifest["changes"] = precomputed
    (tag_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def fp_of(states: dict[str, str]) -> str:
    from scripts.ui.validate_artifact import fingerprint

    return fingerprint((sid, vp, sha) for sid, sha in states.items() for vp in VIEWPORTS)


def _entries(screens: Path, tags: list[str]) -> list[dict]:
    return collect_evolution_entries(state_data={}, screenshots_dir=screens, tags=tags)


def test_changes_are_new_changed_and_omit_unchanged(tmp_path: Path) -> None:
    create_state_release(tmp_path, "v0.7.0", {"home-default": "a", "parcel-timeline": "p"})
    create_state_release(
        tmp_path,
        "v0.8.0",
        {"home-default": "b", "parcel-timeline": "p", "home-dark": "d"},
    )
    entries = _entries(tmp_path, ["v0.7.0", "v0.8.0"])
    latest = entries[0]
    by_state = {c["state"]: c for c in latest["changes"]}

    assert set(by_state) == {"home-dark", "home-default"}  # parcel-timeline unchanged
    assert by_state["home-dark"]["status"] == "new"
    assert by_state["home-default"]["status"] == "changed"
    assert by_state["home-default"]["before"]["desktop"] == "home-default-desktop.png"
    assert by_state["home-dark"]["before"] == {}
    assert by_state["home-dark"]["after"]["mobile"] == "home-dark-mobile.png"
    # new states lead, then changed
    assert [c["state"] for c in latest["changes"]] == ["home-dark", "home-default"]
    assert latest["before"]["tag"] == "v0.7.0"


def test_first_release_lists_all_its_states_as_new(tmp_path: Path) -> None:
    create_state_release(tmp_path, "v0.1.0", {"home-default": "a", "parcel-timeline": "p"})
    entries = _entries(tmp_path, ["v0.1.0"])
    assert {c["status"] for c in entries[0]["changes"]} == {"new"}
    assert entries[0]["before"] is None


def test_precomputed_changes_in_manifest_win_over_sha_compare(tmp_path: Path) -> None:
    create_state_release(tmp_path, "v0.7.0", {"home-default": "a"})
    # shas differ (a vs b) but the publisher measured only render noise: unchanged
    create_state_release(
        tmp_path,
        "v0.8.0",
        {"home-default": "b", "home-dark": "d"},
        precomputed={
            "vs": "v0.7.0",
            "fp": {
                "self": fp_of({"home-default": "b", "home-dark": "d"}),
                "prev": fp_of({"home-default": "a"}),
            },
            "states": {
                "home-default": {"status": "unchanged", "pct": {"desktop": 0.0, "mobile": 0.0}},
                "home-dark": {"status": "new", "pct": {}},
            },
        },
    )
    latest = _entries(tmp_path, ["v0.7.0", "v0.8.0"])[0]
    assert [c["state"] for c in latest["changes"]] == ["home-dark"]


def test_precomputed_pct_is_carried_for_changed_states(tmp_path: Path) -> None:
    create_state_release(tmp_path, "v0.7.0", {"home-default": "a"})
    create_state_release(
        tmp_path,
        "v0.8.0",
        {"home-default": "b"},
        precomputed={
            "vs": "v0.7.0",
            "fp": {"self": fp_of({"home-default": "b"}), "prev": fp_of({"home-default": "a"})},
            "states": {
                "home-default": {"status": "changed", "pct": {"desktop": 12.5, "mobile": 3.0}}
            },
        },
    )
    latest = _entries(tmp_path, ["v0.7.0", "v0.8.0"])[0]
    assert latest["changes"][0]["pct"] == {"desktop": 12.5, "mobile": 3.0}


def test_before_skips_non_reproducible_releases(tmp_path: Path) -> None:
    create_state_release(tmp_path, "v0.1.0", {"home-default": "a"})
    create_release_fixture(tmp_path, "v0.2.0", reproducible=False, reason="build failed")
    create_state_release(tmp_path, "v0.3.0", {"home-default": "b"})
    entries = _entries(tmp_path, ["v0.1.0", "v0.2.0", "v0.3.0"])
    assert entries[0]["before"]["tag"] == "v0.1.0"
    assert entries[0]["changes"][0]["status"] == "changed"


def test_legacy_route_manifests_map_to_states(tmp_path: Path) -> None:
    create_release_fixture(tmp_path, "v0.1.0")
    entries = _entries(tmp_path, ["v0.1.0"])
    assert set(entries[0]["screenshots"]) == {
        "home-default",
        "parcel-timeline",
        "parcel-not-found",
        "parcel-invalid-input",
    }


def _render(tmp_path: Path, tags: list[str]) -> str:
    return render_html(_entries(tmp_path, tags))


def test_card_shows_before_and_after_for_changed_states_only(tmp_path: Path) -> None:
    create_state_release(tmp_path, "v0.7.0", {"home-default": "a", "parcel-timeline": "p"})
    create_state_release(
        tmp_path, "v0.8.0", {"home-default": "b", "parcel-timeline": "p", "home-dark": "d"}
    )
    page = _render(tmp_path, ["v0.7.0", "v0.8.0"])
    latest_card = page.split('<article class="timeline-item">')[1]

    assert 'data-state="home-dark"' in latest_card
    assert "Home, dark theme" in latest_card
    assert "Home page in dark theme." in latest_card
    assert "New state" in latest_card
    assert 'data-state="home-default"' in latest_card
    # before + after columns for the changed state, with the compared tags
    assert "Before (v0.7.0)" in latest_card and "After (v0.8.0)" in latest_card
    assert "./screenshots/v0.7.0/home-default-desktop.png" in latest_card
    assert "./screenshots/v0.8.0/home-default-desktop.png" in latest_card
    # unchanged state is not shown as a change
    assert 'data-state="parcel-timeline"' not in latest_card.split("</article>")[0]


def test_card_without_changes_says_so(tmp_path: Path) -> None:
    create_state_release(tmp_path, "v0.7.0", {"home-default": "a"})
    create_state_release(tmp_path, "v0.8.0", {"home-default": "a"})
    page = _render(tmp_path, ["v0.7.0", "v0.8.0"])
    assert "No visible UI change vs v0.7.0" in page


def test_changed_blocks_are_capped_and_the_rest_listed(tmp_path: Path) -> None:
    ids = ["home-default", "home-dark", "parcel-timeline", "parcel-copy-link"]
    create_state_release(tmp_path, "v0.7.0", dict.fromkeys(ids, "a"))
    create_state_release(tmp_path, "v0.8.0", dict.fromkeys(ids, "b"))
    page = _render(tmp_path, ["v0.7.0", "v0.8.0"])
    card = page.split('<article class="timeline-item">')[1].split("</article>")[0]
    assert card.count('class="change"') == MAX_CHANGE_BLOCKS
    assert "more changed" in card


def test_toolbar_lists_every_state_in_the_data(tmp_path: Path) -> None:
    create_state_release(tmp_path, "v0.7.0", {"home-default": "a"})
    create_state_release(tmp_path, "v0.8.0", {"home-default": "a", "home-dark": "d"})
    page = _render(tmp_path, ["v0.7.0", "v0.8.0"])
    assert 'data-action="set-state" data-state="all"' in page
    assert 'data-action="set-state" data-state="home-default"' in page
    assert 'data-action="set-state" data-state="home-dark"' in page
    assert "Home, dark theme" in page


def test_hostile_manifest_values_cannot_reach_the_page(tmp_path: Path) -> None:
    create_state_release(tmp_path, "v0.7.0", {"home-default": "a"})
    create_state_release(
        tmp_path,
        "v0.8.0",
        {"home-default": "b", "home-dark": "d"},
        extra={
            "home-dark": {
                "title": "<script>alert(1)</script>",
                "caption": '"><img src=x onerror=alert(2)>',
            },
            "home-default": {"filename": "../../etc/passwd.png"},
        },
    )
    page = _render(tmp_path, ["v0.7.0", "v0.8.0"])
    assert "<script>alert" not in page
    assert "onerror" not in page
    assert "etc/passwd" not in page
    assert "..\\" not in page and "/../" not in page


def test_no_ledger_ticket_falls_back_to_merge_commit_title_and_pr_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_state_release(tmp_path, "v0.9.0", {"home-default": "a"})

    def fake_meta(ref: str, repo_root: Path | None = None) -> dict[str, str]:
        return {
            "sha": "0123456789abcdef0123456789abcdef01234567",
            "date": "2026-10-14T10:00:00Z",
            "subject": "Merge pull request #104 from stevengonsalvez/agent/issue-96",
            "body": "feat(web): add a left navigation (#96)",
        }

    monkeypatch.setattr("scripts.ui.generate_history.get_commit_metadata", fake_meta)
    entry = _entries(tmp_path, ["v0.9.0"])[0]
    assert entry["title"] == "feat(web): add a left navigation"
    assert entry["pr_number"] == 104
    assert entry["pr_url"] == "https://github.com/stevengonsalvez/foundry-autonomous-sdlc/pull/104"
    page = render_html([entry])
    assert "pr #104" in page and "add a left navigation" in page


def test_ledger_title_and_pr_win_over_commit_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_state_release(tmp_path, "v0.9.0", {"home-default": "a"})

    def fake_meta(ref: str, repo_root: Path | None = None) -> dict[str, str]:
        return {
            "sha": "0123456789abcdef0123456789abcdef01234567",
            "date": "2026-10-14T10:00:00Z",
            "subject": "Merge pull request #104 from x/y",
            "body": "commit body title (#96)",
        }

    monkeypatch.setattr("scripts.ui.generate_history.get_commit_metadata", fake_meta)
    state = {
        "tickets": [
            {
                "release": {"tag": "v0.9.0"},
                "title": "Ledger title",
                "issue": 96,
                "pr": {"number": 104, "url": "https://github.com/o/r/pull/104"},
            }
        ]
    }
    entry = collect_evolution_entries(state, tmp_path, tags=["v0.9.0"])[0]
    assert entry["title"] == "Ledger title"
    assert entry["pr_url"] == "https://github.com/o/r/pull/104"


def test_compact_rows_name_the_changed_states(tmp_path: Path) -> None:
    create_state_release(tmp_path, "v0.1.0", {"home-default": "a"})
    for minor in range(2, 8):
        create_state_release(
            tmp_path, f"v0.{minor}.0", {"home-default": "a", "home-dark": str(minor)}
        )
    tags = [f"v0.{m}.0" for m in range(1, 8)]
    page = _render(tmp_path, tags)
    older = page.split('class="older-entries-disclosure"')[1]
    assert "timeline-item-compact" in older
    assert "Changed: " in older
    assert "<img" not in older


def test_worst_case_page_stays_inside_the_html_budget(tmp_path: Path) -> None:
    ids = list(STATE_META)
    for minor in range(1, 31):
        create_state_release(tmp_path, f"v0.{minor}.0", dict.fromkeys(ids, str(minor)))
    tags = [f"v0.{m}.0" for m in range(1, 31)]
    page = _render(tmp_path, tags)
    assert len(page.encode("utf-8")) < BUDGET_HTML_BYTES


def test_capped_changes_stay_findable_by_the_state_filter(tmp_path: Path) -> None:
    """A changed state beyond the block cap is named in the 'more' list with its state id, so
    the page script can keep it visible instead of claiming the state did not change."""
    ids = ["home-default", "home-dark", "parcel-timeline", "parcel-copy-link"]
    create_state_release(tmp_path, "v0.7.0", dict.fromkeys(ids, "a"))
    create_state_release(tmp_path, "v0.8.0", dict.fromkeys(ids, "b"))
    page = _render(tmp_path, ["v0.7.0", "v0.8.0"])
    card = page.split('<article class="timeline-item">')[1].split("</article>")[0]
    blocks = set(re.findall(r'class="change" data-state="([^"]+)"', card))
    listed = set(re.findall(r'data-more-state="([^"]+)"', card))
    assert len(blocks) == MAX_CHANGE_BLOCKS
    assert blocks | listed == set(ids) and not (blocks & listed)
    assert "data-more-state" in generate_js()


def test_stored_changes_are_ignored_when_the_captures_were_replaced(tmp_path: Path) -> None:
    """v0.7.0 was re-captured after v0.8.0's diff was stored: the stale diff says 'unchanged'
    but the pixels now differ, so the generator must fall back to comparing sha256."""
    create_state_release(tmp_path, "v0.7.0", {"home-default": "NEW"})
    create_state_release(
        tmp_path,
        "v0.8.0",
        {"home-default": "b"},
        precomputed={
            "vs": "v0.7.0",
            "fp": {"self": fp_of({"home-default": "b"}), "prev": fp_of({"home-default": "OLD"})},
            "states": {"home-default": {"status": "unchanged", "pct": {}}},
        },
    )
    latest = _entries(tmp_path, ["v0.7.0", "v0.8.0"])[0]
    assert [c["state"] for c in latest["changes"]] == ["home-default"]  # sha256 fallback

    # and a stored result without any fingerprint is never trusted
    create_state_release(
        tmp_path,
        "v0.8.0",
        {"home-default": "b"},
        precomputed={"vs": "v0.7.0", "states": {"home-default": {"status": "unchanged"}}},
    )
    assert _entries(tmp_path, ["v0.7.0", "v0.8.0"])[0]["changes"][0]["state"] == "home-default"
