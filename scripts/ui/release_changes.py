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
from scripts.ui.validate_artifact import LEGACY_ROUTE_STATES, manifest_fingerprint, state_id_of

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


def _legacy_reader_order(screenshots: list[Any]) -> list[Any]:
    """Put the four original default states last.

    A Pages build that predates states keys screenshots by route and lets the last entry win,
    so with several states per route it would show e.g. the dark home page as "Home". Listing
    the original states last keeps such a reader on the screenshots it always showed. The
    order is otherwise stable and irrelevant to state-aware readers.
    """
    legacy = set(LEGACY_ROUTE_STATES.values())
    return [s for s in screenshots if state_id_of(s) not in legacy] + [
        s for s in screenshots if state_id_of(s) in legacy
    ]


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
    prev: dict[str, Any] = {"screenshots": []}
    if prev_tag is None:
        states = {
            sid: {"status": "new", "pct": {}}
            for sid in (state_id_of(s) for s in manifest["screenshots"] if isinstance(s, dict))
            if sid
        }
    else:
        prev = _load_captured(releases_dir / prev_tag) or prev
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

    prev_shots = prev["screenshots"] if prev_tag is not None else None
    # fp ties the stored result to the exact pixels it was computed from, so a re-captured
    # release (or a re-captured predecessor) makes /history/ fall back to sha256, not go stale.
    changes = {
        "vs": prev_tag,
        "fp": {
            "self": manifest_fingerprint(manifest["screenshots"]),
            "prev": manifest_fingerprint(prev_shots) if prev_shots is not None else None,
        },
        "states": states,
    }
    manifest["changes"] = changes
    manifest["screenshots"] = _legacy_reader_order(manifest["screenshots"])
    (release_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return changes
