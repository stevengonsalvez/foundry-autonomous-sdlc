"""Store 'what changed since the previous release' in a release manifest.

The /history/ page shows, per release, the states whose pixels changed. Deciding that needs
a pixel diff (sha256 alone flags sub-pixel antialiasing noise), which is too slow to repeat
for every release each time Pages is built. So the trusted publisher computes it once, when
the release is stored on the pr-screenshots branch, and records it as `changes` in
releases/<tag>/manifest.json:

    {"vs": "v0.7.0", "states": {"home-dark": {"status": "new", "pct": {}},
                                "home-default": {"status": "changed", "pct": {"desktop": 1.2}}}}
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from scripts.ui.publish_proof import compare_screenshots
from scripts.ui.validate_artifact import state_id_of

TAG_RE = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _semver(tag: str) -> tuple[int, ...]:
    return tuple(int(x) for x in TAG_RE.match(tag).groups())  # type: ignore[union-attr]


def _load_captured(release_dir: Path) -> dict[str, Any] | None:
    """The manifest of a release that actually has screenshots, else None."""
    try:
        data = json.loads((release_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("reproducible") is False:
        return None
    shots = data.get("screenshots")
    return data if isinstance(shots, list) and shots else None


def find_previous_release(releases_dir: Path, key: str) -> str | None:
    """Nearest older semver release that was captured."""
    if not TAG_RE.match(key):
        return None
    older = [
        d.name
        for d in releases_dir.iterdir()
        if d.is_dir()
        and not d.is_symlink()
        and TAG_RE.match(d.name)
        and _semver(d.name) < _semver(key)
    ]
    for tag in sorted(older, key=_semver, reverse=True):
        if _load_captured(releases_dir / tag) is not None:
            return tag
    return None


def annotate_release(releases_dir: Path, key: str) -> dict[str, Any] | None:
    """Write `changes` into releases/<key>/manifest.json; returns it (None if not applicable)."""
    if not TAG_RE.match(key):
        return None
    release_dir = releases_dir / key
    manifest = _load_captured(release_dir)
    if manifest is None:
        return None

    prev_tag = find_previous_release(releases_dir, key)
    if prev_tag is None:
        states = {
            sid: {"status": "new", "pct": {}}
            for sid in (state_id_of(s) for s in manifest["screenshots"] if isinstance(s, dict))
            if sid
        }
    else:
        prev = _load_captured(releases_dir / prev_tag) or {"screenshots": []}
        report = compare_screenshots(
            manifest["screenshots"], release_dir, prev["screenshots"], releases_dir / prev_tag
        )
        states = {
            entry["state"]: {
                "status": entry["status"],
                "pct": {
                    vp: view["pct"]
                    for vp, view in entry["viewports"].items()
                    if view["pct"] is not None
                },
            }
            for entry in report
        }

    changes = {"vs": prev_tag, "states": states}
    manifest["changes"] = changes
    (release_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return changes
