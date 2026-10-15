"""Generate the static App Evolution Showcase page (/history/).

Reads release tags, ledger ticket costs from state.json, and screenshot manifests
to generate:
1. data.json: Structured evolution timeline data with budget metadata.
2. index.html: Self-contained, accessible, dark-themed HTML page matching
   control center tokens, with 'then vs now' comparison, vertical timeline, and
   side-by-side before/after screenshots for recent releases and compact rows for older entries.
3. css/styles.css: Dark navy mission-control CSS stylesheet (< 20KB budget).
4. js/main.js: Vanilla JS for the desktop/mobile toggle and state switcher (< 15KB budget).

Each release card shows the states (scripts/ui/states.json) that changed in that release
as before/after pairs. "Changed" comes from the pixel diff the publisher stored in the
release manifest (`changes`); without it the generator falls back to comparing sha256.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ui.png_diff import format_pct  # noqa: E402
from scripts.ui.validate_artifact import (  # noqa: E402
    LEGACY_ROUTE_STATES,
    MAX_CAPTION_LEN,
    MAX_STATE_ID_LEN,
    MAX_TITLE_LEN,
    SAFE_PNG_NAME_RE,
    STATE_ID_RE,
    TEXT_RE,
)

REPO_NAME = "stevengonsalvez/foundry-autonomous-sdlc"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "history"
DEFAULT_SCREENSHOTS_DIR = REPO_ROOT / "history" / "screenshots"

ROUTES = ["home", "parcel-found", "not-found", "invalid-input"]
ROUTE_LABELS = {
    "home": "Home",
    "parcel-found": "Parcel Found",
    "not-found": "Not Found",
    "invalid-input": "Invalid Input",
}
VIEWPORTS = ["desktop", "mobile"]
# Cards stay readable and inside the HTML budget: the biggest changes get before/after
# images, the rest are listed by name.
MAX_CHANGE_BLOCKS = 3
FULL_CARD_COUNT = 5
DEFAULT_STATE = "home-default"
MERGE_PR_RE = re.compile(r"^Merge pull request #(\d+) from ")
TRAILING_REF_RE = re.compile(r"\s*\(#\d+\)\s*$")

# Size budget limits (in bytes)
BUDGET_HTML_BYTES = 50 * 1024
BUDGET_CSS_BYTES = 20 * 1024
BUDGET_JS_BYTES = 15 * 1024

TAG_RE = re.compile(r"^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def parse_semver_key(tag: str) -> tuple[int, ...]:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", tag)
    if m:
        return tuple(int(x) for x in m.groups())
    return (999, 999, 999)


def load_state_ledger(state_path: Path | None = None) -> dict[str, Any]:
    """Load state.json from file or fetch from git origin/state."""
    if state_path and state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Try local state/state.json if present
    local_state = REPO_ROOT / "state" / "state.json"
    if local_state.exists():
        try:
            return json.loads(local_state.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Try git show origin/state:state.json
    try:
        res = subprocess.run(
            ["git", "show", "origin/state:state.json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if res.returncode == 0 and res.stdout.strip():
            return json.loads(res.stdout)
    except Exception:
        pass

    return {}


def get_commit_metadata(ref: str, repo_root: Path = REPO_ROOT) -> dict[str, str]:
    """Get commit SHA, ISO date, and commit message for a ref in UTC."""
    env = os.environ.copy()
    env["TZ"] = "UTC"
    res = subprocess.run(
        [
            "git",
            "log",
            "-n",
            "1",
            "--date=format-local:%Y-%m-%dT%H:%M:%SZ",
            "--format=%H%x09%cd%x09%s",
            ref,
        ],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"Cannot resolve commit metadata for {ref}: {res.stderr.strip()}"
        )
    parts = res.stdout.strip().split("\t")
    if len(parts) >= 2:
        body_res = subprocess.run(
            ["git", "log", "-n", "1", "--format=%b", ref],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        body_lines = [ln.strip() for ln in body_res.stdout.splitlines() if ln.strip()]
        return {
            "sha": parts[0],
            "date": parts[1],
            "subject": parts[2] if len(parts) > 2 else "",
            "body": body_lines[0] if body_lines else "",
        }
    raise RuntimeError(f"Unexpected git log output for ref {ref}: {res.stdout.strip()}")


def _clean_state_files(tag_dir: Path, m_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """State id -> {title, caption, files, shas} from a release manifest.

    Manifests live on a branch fed by CI artifacts, so every value is re-checked: unsafe
    ids/filenames are dropped, files must exist on disk (no 404 images), unsafe text
    degrades to the state id/empty. Legacy route-only manifests map onto state ids.
    """
    states: dict[str, dict[str, Any]] = {}
    for s in m_data.get("screenshots", []):
        if not isinstance(s, dict):
            continue
        vp, fn = s.get("viewport"), s.get("filename")
        if vp not in VIEWPORTS or not isinstance(fn, str) or not SAFE_PNG_NAME_RE.fullmatch(fn):
            continue
        state = s.get("state") if "state" in s else LEGACY_ROUTE_STATES.get(str(s.get("route")))
        if (
            not isinstance(state, str)
            or len(state) > MAX_STATE_ID_LEN
            or not STATE_ID_RE.fullmatch(state)
        ):
            continue
        if not (tag_dir / fn).is_file():
            continue
        title, caption = s.get("title"), s.get("caption")
        if not (
            isinstance(title, str) and 0 < len(title) <= MAX_TITLE_LEN and TEXT_RE.fullmatch(title)
        ):
            title = ROUTE_LABELS.get(str(s.get("route")), state) if "state" not in s else state
        if not (
            isinstance(caption, str)
            and 0 < len(caption) <= MAX_CAPTION_LEN
            and TEXT_RE.fullmatch(caption)
        ):
            caption = ""
        entry = states.setdefault(
            state, {"title": title, "caption": caption, "files": {}, "shas": {}}
        )
        entry["files"][vp] = fn
        entry["shas"][vp] = s.get("sha256")
    return states


def _change_sort_key(change: dict[str, Any], order: dict[str, int]) -> tuple[int, float, int]:
    pcts = [p if p is not None else 101.0 for p in change["pct"].values()] or [101.0]
    return (0 if change["status"] == "new" else 1, -max(pcts), order.get(change["state"], 999))


def _compute_changes(
    entry: dict[str, Any],
    before: dict[str, Any] | None,
    precomputed: Any,
    order: dict[str, int],
) -> list[dict[str, Any]]:
    """States that changed in this release versus the previous captured release."""
    published: dict[str, Any] = {}
    if (
        before is not None
        and isinstance(precomputed, dict)
        and precomputed.get("vs") == before["tag"]
        and isinstance(precomputed.get("states"), dict)
    ):
        published = precomputed["states"]

    changes: list[dict[str, Any]] = []
    for sid, st in entry["states"].items():
        prev = before["states"].get(sid) if before else None
        info = published.get(sid) if isinstance(published.get(sid), dict) else None
        pct: dict[str, float | None] = {}
        if before is None or prev is None:
            status = "new"
        elif info and info.get("status") in ("new", "changed", "unchanged"):
            status = info["status"]
            raw_pct = info.get("pct")
            if isinstance(raw_pct, dict):
                pct = {
                    vp: float(v)
                    for vp, v in raw_pct.items()
                    if vp in VIEWPORTS and isinstance(v, (int, float)) and not isinstance(v, bool)
                }
        else:
            differs = any(
                st["files"].get(vp) is None
                or prev["files"].get(vp) is None
                or st["shas"].get(vp) != prev["shas"].get(vp)
                for vp in VIEWPORTS
                if vp in st["files"] or vp in prev["files"]
            )
            status = "changed" if differs else "unchanged"
        if status == "unchanged":
            continue
        changes.append(
            {
                "state": sid,
                "title": st["title"],
                "caption": st["caption"],
                "status": status,
                "pct": pct,
                "after": dict(st["files"]),
                "before": dict(prev["files"]) if prev and status != "new" else {},
            }
        )
    changes.sort(key=lambda c: _change_sort_key(c, order))
    return changes


def collect_evolution_entries(
    state_data: dict[str, Any],
    screenshots_dir: Path,
    tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Collect evolution entries ordered newest first."""
    if tags is None:
        try:
            res = subprocess.run(
                ["git", "tag", "-l", "v*"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            tags = [t.strip() for t in res.stdout.splitlines() if t.strip()]
            tags.sort(key=parse_semver_key)
        except Exception as exc:
            raise RuntimeError(f"Failed to list git tags: {exc}") from exc

    # Validate tags match semver format
    tags = [t for t in tags if TAG_RE.match(t)]

    # Fail loudly if screenshots_dir contains releases on disk but 0 tags were found in git
    disk_releases: list[str] = []
    if screenshots_dir.exists():
        disk_releases = [
            d.name
            for d in screenshots_dir.iterdir()
            if d.is_dir() and not d.is_symlink() and TAG_RE.match(d.name)
        ]

    if disk_releases and not tags:
        raise RuntimeError(
            f"Found {len(disk_releases)} release directories in {screenshots_dir} "
            f"({', '.join(sorted(disk_releases))}) but git repository has 0 tags. "
            "Ensure repository was checked out with fetch-depth: 0 / tags."
        )

    tickets_raw = state_data.get("tickets", [])
    ticket_list = (
        tickets_raw.values()
        if isinstance(tickets_raw, dict)
        else (tickets_raw if isinstance(tickets_raw, list) else [])
    )
    # Index tickets by release tag and issue number
    ticket_by_tag: dict[str, dict[str, Any]] = {}
    for t in ticket_list:
        if not isinstance(t, dict):
            continue
        rel = t.get("release") or {}
        tag_val = rel.get("tag")
        if tag_val:
            ticket_by_tag[tag_val] = t

    raw_entries: list[dict[str, Any]] = []

    for tag in tags:
        meta = get_commit_metadata(tag)
        ticket = ticket_by_tag.get(tag)

        title = ""
        issue_num: int | None = None
        issue_url: str | None = None
        issue_label: str | None = None
        pr_num: int | None = None
        pr_url: str | None = None
        cost_usd: float | None = None

        if ticket:
            title = ticket.get("title") or ""
            raw_issue = ticket.get("issue")
            issue_num = None
            if raw_issue is not None:
                try:
                    issue_num = int(raw_issue)
                except (ValueError, TypeError):
                    issue_num = None
            issue_url = ticket.get("url")
            pr = ticket.get("pr") or {}
            raw_pr = pr.get("number")
            pr_num = None
            if raw_pr is not None:
                try:
                    pr_num = int(raw_pr)
                except (ValueError, TypeError):
                    pr_num = None
            pr_url = pr.get("url")
            cost_info = ticket.get("cost") or {}
            raw_cost = cost_info.get("total_usd")
            if raw_cost is None:
                raw_cost = cost_info.get("usd")
            cost_usd = None
            if raw_cost is not None:
                try:
                    cost_usd = float(raw_cost)
                except (ValueError, TypeError):
                    cost_usd = None

            # Derive 'PR only' from state ledger (when ticket is filed as PR or issue == pr)
            if ticket.get("kind") == "pr" or (
                issue_num is not None and pr_num is not None and issue_num == pr_num
            ):
                issue_label = "PR only"
                issue_num = None
                issue_url = None
                if not pr_num and raw_issue:
                    try:
                        pr_num = int(raw_issue)
                    except (ValueError, TypeError):
                        pr_num = None
        else:
            title = meta["subject"]
            merge = MERGE_PR_RE.match(meta["subject"])
            if merge:
                pr_num = int(merge.group(1))
                pr_url = f"https://github.com/{REPO_NAME}/pull/{pr_num}"
                body = TRAILING_REF_RE.sub("", meta.get("body", "")).strip()
                if body:
                    title = body

        # Check screenshot directory and manifest
        tag_dir = screenshots_dir / tag
        manifest_file = tag_dir / "manifest.json"
        reproducible = True
        not_reproducible_reason: str | None = None
        states: dict[str, dict[str, Any]] = {}
        precomputed: Any = None

        if manifest_file.exists():
            try:
                m_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                if m_data.get("reproducible") is False:
                    reproducible = False
                    not_reproducible_reason = m_data.get("reason", "Build failed")
                else:
                    states = _clean_state_files(tag_dir, m_data)
                    precomputed = m_data.get("changes")
                    if not states:
                        reproducible = False
                        not_reproducible_reason = "not captured"
            except Exception:
                reproducible = False
                not_reproducible_reason = "Corrupt manifest"
        else:
            # When no manifest exists, default reproducible=False with reason 'not captured'
            reproducible = False
            not_reproducible_reason = "not captured"

        raw_entries.append(
            {
                "tag": tag,
                "commit_sha": meta["sha"],
                "short_sha": meta["sha"][:8],
                "date": meta["date"],
                "title": title or f"Release {tag}",
                "issue_number": issue_num,
                "issue_url": issue_url,
                "issue_label": issue_label,
                "pr_number": pr_num,
                "pr_url": pr_url,
                "cost_usd": cost_usd,
                "reproducible": reproducible,
                "not_reproducible_reason": not_reproducible_reason,
                "states": states,
                "screenshots": {sid: dict(st["files"]) for sid, st in states.items()},
                "_precomputed": precomputed,
            }
        )

    if disk_releases and not raw_entries:
        raise RuntimeError(
            f"Found {len(disk_releases)} releases in {screenshots_dir} "
            "but collected 0 timeline entries"
        )

    # Order newest first (highest semver first)
    raw_entries.sort(key=lambda e: parse_semver_key(e["tag"]), reverse=True)

    # Canonical state order: first appearance, oldest release first, so core states lead.
    order: dict[str, int] = {}
    for entry in reversed(raw_entries):
        for sid in entry["states"]:
            order.setdefault(sid, len(order))

    # 'before' is the nearest older release that was actually captured
    for i, entry in enumerate(raw_entries):
        before = next((e for e in raw_entries[i + 1 :] if e["reproducible"]), None)
        entry["before"] = (
            {
                "tag": before["tag"],
                "reproducible": before["reproducible"],
                "screenshots": before["screenshots"],
            }
            if before
            else None
        )
        entry["changes"] = (
            _compute_changes(entry, before, entry["_precomputed"], order)
            if entry["reproducible"]
            else []
        )

    for entry in raw_entries:
        entry.pop("_precomputed", None)
        # The hashes were only needed to compute changes
        entry["states"] = {
            sid: {"title": st["title"], "caption": st["caption"], "files": st["files"]}
            for sid, st in entry["states"].items()
        }

    return raw_entries


def generate_css() -> str:
    """Return dark navy stylesheet matching control center tokens."""
    return """/* Delivery Flow App Evolution Showcase Stylesheet
   Pure dark mission-control palette matching Flow Control Center tokens.
   Budget: < 20KB. Zero external requests. Reduced motion safe. Accessible. */

:root {
  color-scheme: dark;

  /* Flow Control Center graphite-blue tokens (hue 240) */
  --canvas: oklch(0.08 0.020 240);
  --surface-0: oklch(0.10 0.022 240);
  --surface-1: oklch(0.26 0.025 240);
  --surface-2: oklch(0.30 0.028 240);
  --surface-3: oklch(0.35 0.032 240);
  --surface-active: oklch(0.39 0.035 240);

  /* Hairlines and strokes */
  --edge: oklch(0.36 0.025 240);
  --edge-subtle: oklch(0.28 0.020 240);
  --edge-focus: oklch(0.72 0.16 220);

  /* Typography */
  --fg: oklch(0.96 0.010 240);
  --fg-dim: oklch(0.84 0.018 240);
  --fg-muted: oklch(0.72 0.020 240);

  /* Life-cycle accent tones */
  --tone-run: oklch(0.78 0.16 150);
  --tone-wait: oklch(0.78 0.15 65);
  --tone-block: oklch(0.68 0.22 10);
  --tone-info: oklch(0.75 0.14 220);
  --tone-agent: oklch(0.76 0.15 295);
  --tone-done: oklch(0.74 0.17 138);

  /* Fonts */
  --font-mono: ui-monospace, "SF Mono", Menlo, "JetBrains Mono", Consolas, monospace;
  --font-sans: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;

  /* Spatial geometry */
  --radius: 6px;
  --radius-sm: 3px;
  --radius-pill: 9999px;
  --max-w: 1200px;
}

*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

html {
  -webkit-text-size-adjust: 100%;
  text-size-adjust: 100%;
  background: var(--canvas);
  color: var(--fg);
  font-family: var(--font-sans);
  font-size: 14px;
  line-height: 1.5;
}

body {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

/* Accessibility skip link */
.skip-link {
  position: absolute;
  top: -40px;
  left: 1rem;
  background: var(--edge-focus);
  color: #000;
  font-weight: 600;
  padding: 0.5rem 1rem;
  border-radius: var(--radius-sm);
  z-index: 100;
  text-decoration: none;
  transition: top 0.1s ease;
}
.skip-link:focus {
  top: 1rem;
}

/* Layout container */
.container {
  width: 100%;
  max-width: var(--max-w);
  margin: 0 auto;
  padding: 0 1.25rem;
}

/* Header */
.topbar {
  background: var(--surface-0);
  border-bottom: 1px solid var(--edge-subtle);
  padding: 0.75rem 0;
}
.topbar-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 1rem;
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--fg);
  text-decoration: none;
  font-weight: 600;
  font-size: 1rem;
}
.brand:focus-visible {
  outline: 2px solid var(--edge-focus);
  outline-offset: 2px;
}
.brand-mark {
  display: block;
}
.brand-text {
  font-weight: 700;
  letter-spacing: -0.01em;
}
.brand-sub {
  color: var(--fg-muted);
  font-size: 0.85rem;
  font-weight: 400;
}
.nav-links {
  display: flex;
  gap: 0.75rem;
  list-style: none;
}
.nav-links a {
  color: var(--fg-dim);
  text-decoration: none;
  font-size: 0.85rem;
  padding: 0.3rem 0.6rem;
  border-radius: var(--radius-sm);
  transition: background 0.1s ease, color 0.1s ease;
}
.nav-links a:hover {
  color: var(--fg);
  background: var(--surface-1);
}
.nav-links a.active {
  color: var(--tone-info);
  background: var(--surface-1);
  font-weight: 600;
}
.nav-links a:focus-visible {
  outline: 2px solid var(--edge-focus);
  outline-offset: 2px;
}

/* Hero */
.hero {
  padding: 2rem 0 1.5rem;
  border-bottom: 1px solid var(--edge-subtle);
}
.hero h1 {
  font-size: 1.75rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin-bottom: 0.5rem;
}
.hero p {
  color: var(--fg-dim);
  max-width: 720px;
  font-size: 0.95rem;
}
.budget-badge {
  display: inline-block;
  margin-top: 0.75rem;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--tone-info);
  background: var(--surface-1);
  border: 1px solid var(--edge-subtle);
  padding: 0.25rem 0.5rem;
  border-radius: var(--radius-sm);
}

/* Then vs Now Strip */
.then-vs-now {
  margin: 1.5rem 0;
  background: var(--surface-0);
  border: 1px solid var(--edge);
  border-radius: var(--radius);
  padding: 1.25rem;
}
.then-vs-now-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}
.then-vs-now-header h2 {
  font-size: 1.1rem;
  font-weight: 600;
}
.then-vs-now-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.25rem;
}
.card-preview {
  background: var(--surface-1);
  border: 1px solid var(--edge-subtle);
  border-radius: var(--radius);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.card-preview-header {
  padding: 0.5rem 0.75rem;
  background: var(--surface-2);
  border-bottom: 1px solid var(--edge-subtle);
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.8rem;
}
.card-preview-title {
  font-weight: 600;
}
.card-preview-body {
  padding: 0.75rem;
  display: flex;
  justify-content: center;
  align-items: center;
  background: #000;
}
.card-preview-body img {
  max-width: 100%;
  height: auto;
  border-radius: var(--radius-sm);
  display: block;
}

/* Controls Toolbar */
.toolbar {
  position: sticky;
  top: 0;
  background: var(--canvas);
  border-bottom: 1px solid var(--edge);
  padding: 0.75rem 0;
  z-index: 50;
  backdrop-filter: blur(8px);
}
.toolbar-inner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}
.control-group {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
}
.control-label {
  font-size: 0.8rem;
  color: var(--fg-muted);
  font-weight: 500;
}
.btn-group {
  display: inline-flex;
  flex-wrap: wrap;
  border: 1px solid var(--edge);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.btn-toggle {
  background: var(--surface-1);
  color: var(--fg-dim);
  border: none;
  padding: 0.35rem 0.75rem;
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.1s ease, color 0.1s ease;
}
.btn-toggle:hover {
  background: var(--surface-2);
  color: var(--fg);
}
.btn-toggle.active {
  background: var(--tone-info);
  color: #000;
  font-weight: 600;
}
.btn-toggle:focus-visible {
  outline: 2px solid var(--edge-focus);
  outline-offset: -2px;
}

/* Timeline */
.timeline {
  padding: 2rem 0;
  position: relative;
}
.timeline::before {
  content: "";
  position: absolute;
  top: 0;
  bottom: 0;
  left: 20px;
  width: 2px;
  background: var(--edge-subtle);
}
.timeline-item {
  position: relative;
  padding-left: 50px;
  margin-bottom: 2.5rem;
}
.timeline-item-compact {
  margin-bottom: 0.75rem;
}
.timeline-item-compact .timeline-card-header {
  border-bottom: none;
  padding: 0.625rem 1rem;
}
.timeline-dot {
  position: absolute;
  left: 13px;
  top: 4px;
  width: 16px;
  height: 16px;
  border-radius: var(--radius-pill);
  background: var(--surface-2);
  border: 2px solid var(--tone-done);
  z-index: 2;
}
.timeline-card {
  background: var(--surface-0);
  border: 1px solid var(--edge);
  border-radius: var(--radius);
  overflow: hidden;
}
.timeline-card-header {
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--edge-subtle);
  background: var(--surface-1);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}
.timeline-meta-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}
.tag-badge {
  font-family: var(--font-mono);
  font-size: 0.85rem;
  font-weight: 700;
  padding: 0.2rem 0.5rem;
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  border: 1px solid var(--edge);
  color: var(--tone-run);
}
.item-title {
  font-size: 1rem;
  font-weight: 600;
  color: var(--fg);
}
.timeline-meta-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-family: var(--font-mono);
  font-size: 0.75rem;
  color: var(--fg-muted);
}
.badge {
  display: inline-block;
  padding: 0.15rem 0.4rem;
  border-radius: var(--radius-sm);
  border: 1px solid var(--edge-subtle);
  background: var(--surface-2);
  color: var(--fg-dim);
  text-decoration: none;
}
.badge a, a.badge {
  color: var(--tone-info);
  text-decoration: none;
}
.badge a:hover, a.badge:hover {
  text-decoration: underline;
}
.badge-cost {
  color: var(--tone-wait);
}

/* Compare Grid */
.compare-container {
  padding: 1.25rem;
}
.compare-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.25rem;
}
.compare-col {
  background: var(--surface-1);
  border: 1px solid var(--edge-subtle);
  border-radius: var(--radius);
  overflow: hidden;
}
.compare-col-header {
  padding: 0.4rem 0.75rem;
  background: var(--surface-2);
  border-bottom: 1px solid var(--edge-subtle);
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--fg-muted);
}
.compare-img-wrap {
  padding: 0.5rem;
  background: #000;
  display: flex;
  justify-content: center;
  align-items: center;
}
.compare-img-wrap img {
  max-width: 100%;
  height: auto;
  border-radius: var(--radius-sm);
  display: block;
}

/* State change blocks */
.change {
  margin-bottom: 1.5rem;
}
[hidden] {
  display: none !important;
}
.change-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.75rem;
  margin-bottom: 0.35rem;
}
.change-title {
  font-size: 1rem;
  margin: 0;
}
.change-caption, .no-change, .more-changes, .state-empty, .compact-changes {
  color: var(--fg-dim);
  font-size: 0.85rem;
  margin: 0 0 0.75rem;
}
.compact-changes {
  padding: 0 1.25rem 0.9rem;
  margin: 0;
}
.badge-new {
  color: var(--tone-run);
}
.no-prior {
  padding: 1.5rem 0.75rem;
  color: var(--fg-dim);
  font-size: 0.85rem;
  text-align: center;
}
/* Not reproducible banner */
.not-reproducible-box {
  padding: 1.5rem;
  background: var(--surface-1);
  border: 1px dashed var(--tone-block);
  border-radius: var(--radius);
  text-align: center;
}
.badge-alert {
  display: inline-block;
  background: var(--tone-block);
  color: #000;
  font-size: 0.75rem;
  font-weight: 700;
  padding: 0.2rem 0.5rem;
  border-radius: var(--radius-sm);
  margin-bottom: 0.5rem;
}
.not-reproducible-box p {
  color: var(--fg-dim);
  font-size: 0.85rem;
  font-family: var(--font-mono);
}

/* Older entries disclosure */
.older-entries-disclosure {
  position: relative;
  margin-top: 1rem;
}
.older-entries-summary {
  cursor: pointer;
  color: var(--fg);
  font-weight: 600;
  padding: 0.5rem 1rem;
  background: var(--surface-1);
  border: 1px solid var(--edge);
  border-radius: var(--radius-sm);
  margin-left: 50px;
  margin-bottom: 2rem;
  display: inline-block;
  user-select: none;
}
.older-entries-summary:hover {
  background: var(--surface-2);
  color: var(--tone-info);
}
.older-entries-summary:focus-visible {
  outline: 2px solid var(--edge-focus);
}
.older-entries-body {
  position: relative;
}

/* Footer */
.footer {
  margin-top: auto;
  padding: 1.5rem 0;
  border-top: 1px solid var(--edge-subtle);
  background: var(--surface-0);
  color: var(--fg-muted);
  font-size: 0.8rem;
  text-align: center;
}

/* Mobile responsive */
@media (max-width: 768px) {
  .then-vs-now-grid, .compare-grid {
    grid-template-columns: 1fr;
  }
  .timeline::before {
    left: 12px;
  }
  .timeline-item {
    padding-left: 36px;
  }
  .timeline-dot {
    left: 5px;
  }
}

/* Reduced motion preference */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
  }
}
"""


def generate_js() -> str:
    """Return vanilla JS script for interactive toggles with zero external calls."""
    return """// Delivery Flow App Evolution Showcase JS
// Budget: < 15KB. Zero external requests. Reduced motion safe.

(function () {
  'use strict';

  const DEFAULT_STATE = 'home-default';
  let currentViewport = 'desktop';
  let currentState = 'all';

  function init() {
    setupToggles('set-viewport', 'data-viewport', function (value) {
      currentViewport = value;
    });
    setupToggles('set-state', 'data-state', function (value) {
      currentState = value;
    });
    updateView();
  }

  function setupToggles(action, attr, apply) {
    const btns = document.querySelectorAll('[data-action="' + action + '"]');
    btns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        const value = btn.getAttribute(attr);
        if (!value) return;
        apply(value);
        btns.forEach(function (b) {
          const active = b === btn;
          b.classList.toggle('active', active);
          b.setAttribute('aria-pressed', String(active));
        });
        updateView();
      });
    });
  }

  function updateView() {
    // Then vs Now shows one state; "all changes" falls back to the home page.
    const previewState = currentState === 'all' ? DEFAULT_STATE : currentState;
    document.querySelectorAll('.card-preview-body [data-state]').forEach(function (el) {
      const stateMatch = el.getAttribute('data-state') === previewState;
      const vp = el.getAttribute('data-viewport');
      el.hidden = !(stateMatch && (!vp || vp === currentViewport));
    });

    // Timeline cards: filter the change blocks by state, switch images by viewport.
    document.querySelectorAll('.timeline-item').forEach(function (item) {
      let visible = 0;
      item.querySelectorAll('.change').forEach(function (block) {
        const show = currentState === 'all' || block.getAttribute('data-state') === currentState;
        block.hidden = !show;
        if (show) visible += 1;
      });
      const empty = item.querySelector('.state-empty');
      if (empty) empty.hidden = visible > 0 || currentState === 'all';
      const more = item.querySelector('.more-changes');
      if (more) more.hidden = currentState !== 'all';
      item.querySelectorAll('.change img').forEach(function (img) {
        img.hidden = img.getAttribute('data-viewport') !== currentViewport;
      });
    });

    const activeBtn = document.querySelector('[data-action="set-state"].active');
    const label = currentState === 'all' || !activeBtn ? 'Home' : activeBtn.textContent;
    document.querySelectorAll('.active-state-label').forEach(function (el) {
      el.textContent = label;
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
"""


CSP_CONTENT = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; base-uri 'none'; form-action 'none'"
)

FAVICON_URI = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Crect width='32' height='32' rx='6' fill='%230e1526'/%3E"
    "%3Cpath d='M7 23l5-6 4 3 9-10' fill='none' stroke='%23818cf8' stroke-width='2.75' "
    "stroke-linecap='round' stroke-linejoin='round'/%3E"
    "%3Ccircle cx='25' cy='10' r='2.5' fill='%23818cf8'/%3E%3C/svg%3E"
)


def _entry_states(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per-state title/caption/files for an entry (older data only carries `screenshots`)."""
    states = entry.get("states")
    if isinstance(states, dict) and states:
        return states
    return {
        sid: {"title": sid, "caption": "", "files": files}
        for sid, files in (entry.get("screenshots") or {}).items()
    }


def _state_imgs(
    tag: str, files: dict[str, str], state: str, alt: str, width: int, height: int, show: str
) -> str:
    """One <img> per viewport; the page script shows the one matching the toggles."""
    tag_q = html.escape(tag, quote=True)
    alt_q = html.escape(alt, quote=True)
    state_q = html.escape(state, quote=True)
    out = []
    for vp in VIEWPORTS:
        fn = files.get(vp)
        if not fn:
            continue
        hidden = "" if vp == show else " hidden"
        out.append(
            f'<img src="./screenshots/{tag_q}/{html.escape(fn, quote=True)}" '
            f'alt="{alt_q} {vp}" data-state="{state_q}" '
            f'data-viewport="{vp}"{hidden} loading="lazy" width="{width}" height="{height}" />'
        )
    return "".join(out)


def _then_now_html(
    entry: dict[str, Any] | None, state_order: list[str], titles: dict[str, str]
) -> str:
    """Preview card content for Then vs Now: every state, switched by the toolbar."""
    if not entry:
        return ""
    tag = entry["tag"]
    tag_h = html.escape(tag)
    if not entry.get("reproducible"):
        reason = html.escape(entry.get("not_reproducible_reason") or "not captured")
        return (
            f'<div class="not-reproducible-box">'
            f'<span class="badge-alert">Not Reproducible</span>'
            f"<p>Reason: {reason}</p>"
            f"</div>"
        )
    states = _entry_states(entry)
    out = []
    for sid in state_order:
        sid_q = html.escape(sid, quote=True)
        show = "desktop" if sid == DEFAULT_STATE else ""
        files = (states.get(sid) or {}).get("files") or {}
        if files:
            alt = f"{tag} {titles.get(sid, sid)}"
            out.append(_state_imgs(tag, files, sid, alt, 600, 375, show))
        else:
            title_h = html.escape(titles.get(sid, sid))
            hide = "" if sid == DEFAULT_STATE else " hidden"
            out.append(
                f'<div class="no-prior" data-state="{sid_q}"{hide}>'
                f"{title_h} did not exist in {tag_h}</div>"
            )
    return "".join(out)


def _change_block(change: dict[str, Any], before_tag: str | None, tag: str) -> str:
    sid = html.escape(change["state"], quote=True)
    title = html.escape(change["title"])
    if change["status"] == "new":
        badge = '<span class="badge badge-new">New state</span>'
    else:
        parts = [
            f"{vp} {format_pct(change['pct'].get(vp))}"
            for vp in VIEWPORTS
            if vp in change["after"] and vp in change["pct"]
        ]
        label = "changed: " + ", ".join(parts) if parts else "changed"
        badge = f'<span class="badge">{html.escape(label)}</span>'
    caption = ""
    if change["caption"]:
        caption = f'<p class="change-caption">{html.escape(change["caption"])}</p>'
    sid_raw, name = change["state"], change["title"]
    after_imgs = _state_imgs(tag, change["after"], sid_raw, f"{tag} {name}", 560, 350, "desktop")
    if change["before"] and before_tag:
        before_imgs = _state_imgs(
            before_tag, change["before"], sid_raw, f"{before_tag} {name}", 560, 350, "desktop"
        )
    else:
        prior = html.escape(before_tag) if before_tag else "any earlier release"
        before_imgs = f'<div class="no-prior">Not present in {prior}</div>'
    before_label = html.escape(before_tag) if before_tag else "Initial"
    return (
        f'<div class="change" data-state="{sid}"><div class="change-head">'
        f'<h4 class="change-title">{title}</h4>{badge}</div>{caption}'
        f'<div class="compare-grid">'
        f'<div class="compare-col"><div class="compare-col-header">Before ({before_label})</div>'
        f'<div class="compare-img-wrap">{before_imgs}</div></div>'
        f'<div class="compare-col"><div class="compare-col-header">After ({html.escape(tag)})</div>'
        f'<div class="compare-img-wrap">{after_imgs}</div></div>'
        f"</div></div>"
    )


def _changes_html(entry: dict[str, Any]) -> str:
    changes = entry.get("changes") or []
    before = entry.get("before")
    before_tag = before["tag"] if before else None
    if not changes:
        vs = html.escape(before_tag) if before_tag else "the previous release"
        return f'<p class="no-change">No visible UI change vs {vs}</p>'
    shown, rest = changes[:MAX_CHANGE_BLOCKS], changes[MAX_CHANGE_BLOCKS:]
    blocks = "".join(_change_block(c, before_tag, entry["tag"]) for c in shown)
    more = ""
    if rest:
        names = ", ".join(
            f"{html.escape(c['title'])}"
            + (
                f" ({html.escape(format_pct(max(c['pct'].values())))})"
                if c["status"] == "changed" and c["pct"]
                else ""
            )
            for c in rest
        )
        more = f'<p class="more-changes">+{len(rest)} more changed: {names}</p>'
    return (
        blocks
        + more
        + '<p class="state-empty" hidden>No change to this state in this release.</p>'
    )


def _compact_changes_html(entry: dict[str, Any]) -> str:
    changes = entry.get("changes") or []
    if not entry.get("reproducible"):
        return ""
    if not entry.get("before"):
        return '<p class="compact-changes">Initial release</p>'
    if not changes:
        return '<p class="compact-changes">No visible UI change</p>'
    names = ", ".join(html.escape(c["title"]) for c in changes[:4])
    extra = f" +{len(changes) - 4} more" if len(changes) > 4 else ""
    return f'<p class="compact-changes">Changed: {names}{extra}</p>'


def render_html(
    entries: list[dict[str, Any]], repo_name: str = "stevengonsalvez/foundry-autonomous-sdlc"
) -> str:
    """Render semantic HTML for the evolution page."""
    # Find Then vs Now entries
    oldest_entry = entries[-1] if entries else None
    newest_entry = entries[0] if entries else None

    # Every state seen in any release, oldest first so the core states lead; titles from
    # the newest release that has the state.
    state_order: list[str] = []
    titles: dict[str, str] = {}
    for entry in reversed(entries):
        for sid, st in _entry_states(entry).items():
            if sid not in state_order:
                state_order.append(sid)
            titles[sid] = st.get("title") or sid

    then_img_html = _then_now_html(oldest_entry, state_order, titles)
    now_img_html = _then_now_html(newest_entry, state_order, titles)

    # Build timeline items HTML
    timeline_items_html: list[str] = []

    for idx, entry in enumerate(entries):
        raw_tag = entry["tag"]
        tag = html.escape(raw_tag)
        title = html.escape(entry["title"])
        sha = html.escape(entry["short_sha"])
        date = html.escape(entry["date"].replace("T", " ")[:16] + " UTC")
        reproducible = entry["reproducible"]

        # Meta badges
        badges: list[str] = [f'<span class="badge" title="Commit {sha}">sha: {sha}</span>']
        if entry.get("issue_label"):
            lbl = html.escape(entry["issue_label"])
            badges.append(f'<span class="badge">{lbl}</span>')
        elif entry.get("issue_number") and entry.get("issue_url"):
            i_num = entry["issue_number"]
            i_url = html.escape(entry["issue_url"], quote=True)
            badges.append(
                f'<a class="badge" href="{i_url}" target="_blank" rel="noopener">issue #{i_num}</a>'
            )
        if entry.get("pr_number") and entry.get("pr_url"):
            p_num = entry["pr_number"]
            p_url = html.escape(entry["pr_url"], quote=True)
            badges.append(
                f'<a class="badge" href="{p_url}" target="_blank" rel="noopener">pr #{p_num}</a>'
            )
        if entry.get("cost_usd") is not None:
            cost = entry["cost_usd"]
            badges.append(
                f'<span class="badge badge-cost" title="Ledger total cost">${cost:.3f}</span>'
            )

        badges_str = " ".join(badges)
        entry_date = entry["date"]
        dot_html = '<div class="timeline-dot" aria-hidden="true"></div>'
        header_html = (
            f'<header class="timeline-card-header">'
            f'<div class="timeline-meta-left"><span class="tag-badge">{tag}</span>'
            f'<h3 class="item-title">{title}</h3></div>'
            f'<div class="timeline-meta-right"><time datetime="{entry_date}">{date}</time>'
            f"{badges_str}</div></header>"
        )

        if idx < FULL_CARD_COUNT:
            # Full card: the states that changed in this release, before and after
            if not reproducible:
                reason = html.escape(entry.get("not_reproducible_reason") or "Build failed")
                inner = (
                    f'<div class="not-reproducible-box">'
                    f'<span class="badge-alert">Not Reproducible</span>'
                    f"<p>Reason: {reason}</p>"
                    f"</div>"
                )
            else:
                inner = _changes_html(entry)
            item_html = (
                f'<article class="timeline-item">{dot_html}'
                f'<div class="timeline-card">{header_html}'
                f'<div class="compare-container">{inner}</div></div></article>'
            )
        else:
            # Compact row for older releases (no <img> markup, names the changed states)
            item_html = (
                f'<article class="timeline-item timeline-item-compact">{dot_html}'
                f'<div class="timeline-card timeline-card-compact">{header_html}'
                f"{_compact_changes_html(entry)}</div></article>"
            )
        timeline_items_html.append(item_html)

    if len(timeline_items_html) > 5:
        recent_items = timeline_items_html[:5]
        older_items = timeline_items_html[5:]
        older_count = len(older_items)
        older_content = "\n".join(older_items)
        older_summary = f"Older releases ({older_count})"
        timeline_content = (
            "\n".join(recent_items) + f'\n      <details class="older-entries-disclosure">\n'
            f'        <summary class="older-entries-summary">{older_summary}</summary>\n'
            f'        <div class="older-entries-body">\n'
            f"          {older_content}\n"
            f"        </div>\n"
            f"      </details>"
        )
    else:
        timeline_content = "\n".join(timeline_items_html)

    state_buttons = (
        '<button type="button" class="btn-toggle active" data-action="set-state" '
        'data-state="all" aria-pressed="true">All changes</button>'
        + "".join(
            f'<button type="button" class="btn-toggle" data-action="set-state" '
            f'data-state="{html.escape(sid, quote=True)}" aria-pressed="false">'
            f"{html.escape(titles.get(sid, sid))}</button>"
            for sid in state_order
        )
    )

    then_tag = html.escape(oldest_entry["tag"]) if oldest_entry else "v0.1.0"
    now_tag = html.escape(newest_entry["tag"]) if newest_entry else "v0.4.0"

    html_doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="{CSP_CONTENT}">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <meta name="description"
    content="Visual evolution of the parcel tracker UI across autonomous SDLC releases.">
  <title>App Evolution · Delivery Flow</title>
  <link rel="icon" href="{FAVICON_URI}">
  <link rel="stylesheet" href="./css/styles.css">
  <script src="./js/main.js" defer></script>
</head>
<body>
  <a class="skip-link" href="#main">Skip to content</a>

  <header class="topbar">
    <div class="container topbar-inner">
      <a class="brand" href="../" aria-label="Parcel tracker home">
        <svg class="brand-mark" width="24" height="24" viewBox="0 0 32 32"
          aria-hidden="true" focusable="false">
          <rect width="32" height="32" rx="6" fill="#1e293b" />
          <path d="M8 21l5-5 4 3 7-8" fill="none" stroke="#818cf8" stroke-width="2.5"
            stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        <span class="brand-text">Flow</span>
        <span class="brand-sub">· Evolution</span>
      </a>
      <nav aria-label="Pages navigation">
        <ul class="nav-links">
          <li><a href="../">Live app</a></li>
          <li><a href="../control-center/">Control center</a></li>
          <li><a href="./" class="active" aria-current="page">Evolution</a></li>
          <li><a href="../staging/">Staging</a></li>
          <li><a href="../dashboard/">Dashboard</a></li>
          <li><a href="https://github.com/{repo_name}#documentation">Docs</a></li>
        </ul>
      </nav>
    </div>
  </header>

  <main id="main" tabindex="-1">
    <section class="hero">
      <div class="container">
        <h1>App Evolution Showcase</h1>
        <p>A deterministic visual timeline of parcel tracker UI releases, tracking each change
        from initial launch to current release with side-by-side screenshot comparisons
        and ledger costs.</p>
        <div class="budget-badge" role="note">
          Size budget: HTML &lt; 50KB · CSS &lt; 20KB · JS &lt; 15KB (zero external requests)
        </div>
      </div>
    </section>

    <div class="container">
      <section class="then-vs-now" aria-labelledby="then-vs-now-heading">
        <div class="then-vs-now-header">
          <h2 id="then-vs-now-heading">Then vs Now</h2>
          <span class="badge" style="color: var(--tone-info);">{then_tag} &rarr; {now_tag}</span>
        </div>
        <div class="then-vs-now-grid">
          <div class="card-preview">
            <div class="card-preview-header">
              <span class="card-preview-title">First Release ({then_tag})</span>
              <span class="active-state-label">Home</span>
            </div>
            <div class="card-preview-body">
              {then_img_html}
            </div>
          </div>
          <div class="card-preview">
            <div class="card-preview-header">
              <span class="card-preview-title">Current Release ({now_tag})</span>
              <span class="active-state-label">Home</span>
            </div>
            <div class="card-preview-body">
              {now_img_html}
            </div>
          </div>
        </div>
      </section>

      <div class="toolbar" role="toolbar" aria-label="Timeline view controls">
        <div class="toolbar-inner">
          <div class="control-group">
            <span class="control-label" id="vp-label">Viewport:</span>
            <div class="btn-group" role="group" aria-labelledby="vp-label">
              <button type="button" class="btn-toggle active"
                data-action="set-viewport" data-viewport="desktop" aria-pressed="true">
                Desktop (1280px)
              </button>
              <button type="button" class="btn-toggle"
                data-action="set-viewport" data-viewport="mobile" aria-pressed="false">
                Mobile (390px)
              </button>
            </div>
          </div>
          <div class="control-group">
            <span class="control-label" id="state-label">State:</span>
            <div class="btn-group" role="group" aria-labelledby="state-label">
              {state_buttons}
            </div>
          </div>
        </div>
      </div>

      <section class="timeline" aria-label="Version history timeline">
        {timeline_content}
      </section>
    </div>
  </main>

  <footer class="footer">
    <div class="container">
      App Evolution Showcase · Deterministic UI captures · Zero external requests · Times are UTC.
    </div>
  </footer>
</body>
</html>
"""
    html_bytes = len(html_doc.encode("utf-8"))
    if html_bytes > BUDGET_HTML_BYTES:
        raise ValueError(
            f"HTML size ({html_bytes} bytes) exceeds budget ({BUDGET_HTML_BYTES} bytes)"
        )

    return html_doc


def build_history_site(
    output_dir: Path,
    screenshots_dir: Path,
    state_path: Path | None = None,
    state_data: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Assemble the complete /history/ site."""
    output_dir.mkdir(parents=True, exist_ok=True)
    css_dir = output_dir / "css"
    js_dir = output_dir / "js"
    css_dir.mkdir(parents=True, exist_ok=True)
    js_dir.mkdir(parents=True, exist_ok=True)

    if state_data is None:
        state_data = load_state_ledger(state_path)
    entries = collect_evolution_entries(state_data, screenshots_dir, tags=tags)

    # 1. Write data.json
    data_json_path = output_dir / "data.json"
    data_payload = {
        "version": 1,
        "repo": "stevengonsalvez/foundry-autonomous-sdlc",
        "budget": {
            "html_max_bytes": BUDGET_HTML_BYTES,
            "css_max_bytes": BUDGET_CSS_BYTES,
            "js_max_bytes": BUDGET_JS_BYTES,
            "external_requests": False,
        },
        "entries": entries,
    }
    data_json_path.write_text(json.dumps(data_payload, indent=2) + "\n", encoding="utf-8")

    # 2. Write CSS
    css_content = generate_css()
    css_bytes = len(css_content.encode("utf-8"))
    if css_bytes >= BUDGET_CSS_BYTES:
        raise ValueError(f"CSS exceeds size budget: {css_bytes} >= {BUDGET_CSS_BYTES} bytes")
    css_path = css_dir / "styles.css"
    css_path.write_text(css_content, encoding="utf-8")

    # 3. Write JS
    js_content = generate_js()
    js_bytes = len(js_content.encode("utf-8"))
    if js_bytes >= BUDGET_JS_BYTES:
        raise ValueError(f"JS exceeds size budget: {js_bytes} >= {BUDGET_JS_BYTES} bytes")
    js_path = js_dir / "main.js"
    js_path.write_text(js_content, encoding="utf-8")

    # 4. Write HTML
    html_content = render_html(entries)
    html_path = output_dir / "index.html"
    html_path.write_text(html_content, encoding="utf-8")

    # 5. Copy only the screenshots the page references (plus each release manifest)
    out_screenshots = output_dir / "screenshots"
    if screenshots_dir.exists() and screenshots_dir.resolve() != out_screenshots.resolve():
        referenced: dict[str, set[str]] = {}
        for tag_name, fn in re.findall(
            r'src="\./screenshots/([^"/]+)/([^"/]+\.png)"', html_content
        ):
            referenced.setdefault(html.unescape(tag_name), set()).add(html.unescape(fn))

        for tag_name in sorted(referenced):
            src_tag_dir = screenshots_dir / tag_name
            if not src_tag_dir.exists():
                raise RuntimeError(
                    f"Required screenshot directory missing for rendered entry: {src_tag_dir}"
                )
            if src_tag_dir.is_symlink():
                continue
            dst_tag_dir = out_screenshots / tag_name
            dst_tag_dir.mkdir(parents=True, exist_ok=True)
            for fn in sorted(referenced[tag_name]):
                item = src_tag_dir / fn
                if item.is_file() and not item.is_symlink():
                    shutil.copy2(item, dst_tag_dir / fn)
            manifest_src = src_tag_dir / "manifest.json"
            if manifest_src.is_file() and not manifest_src.is_symlink():
                shutil.copy2(manifest_src, dst_tag_dir / "manifest.json")

    print(f"Generated App Evolution Showcase at {output_dir}")
    print(f"HTML: {len(html_content.encode('utf-8'))} bytes (budget: {BUDGET_HTML_BYTES})")
    print(f"CSS:  {len(css_content.encode('utf-8'))} bytes (budget: {BUDGET_CSS_BYTES})")
    print(f"JS:   {len(js_content.encode('utf-8'))} bytes (budget: {BUDGET_JS_BYTES})")
    print(f"Total timeline entries: {len(entries)}")

    return data_payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate App Evolution Showcase (/history/).")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Target output directory (default: history/)",
    )
    parser.add_argument(
        "--screenshots-dir",
        type=Path,
        default=DEFAULT_SCREENSHOTS_DIR,
        help="Screenshots directory (default: history/screenshots/)",
    )
    parser.add_argument(
        "--state",
        type=Path,
        help="Path to state.json ledger",
    )
    parser.add_argument(
        "--tags",
        nargs="*",
        help="Explicit list of release tags to include (defaults to all git v* tags)",
    )
    args = parser.parse_args()

    build_history_site(
        output_dir=args.output_dir,
        screenshots_dir=args.screenshots_dir,
        state_path=args.state,
        tags=args.tags,
    )


if __name__ == "__main__":
    main()
