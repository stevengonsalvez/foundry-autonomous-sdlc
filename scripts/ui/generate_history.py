"""Generate the static App Evolution Showcase page (/history/).

Reads release tags, ledger ticket costs from state.json, and screenshot manifests
to generate:
1. history/data.json: Structured evolution timeline data.
2. history/index.html: Self-contained, accessible, dark-themed HTML page matching
   control center tokens, with 'then vs now' comparison, vertical timeline, and
   side-by-side before/after screenshots.
3. history/css/styles.css: Dark navy mission-control CSS stylesheet (< 20KB budget).
4. history/js/main.js: Vanilla JS for desktop/mobile toggle and route switcher (< 15KB budget).
"""

from __future__ import annotations

import argparse
import contextlib
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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

# Size budget limits (in bytes)
BUDGET_HTML_BYTES = 50 * 1024
BUDGET_CSS_BYTES = 20 * 1024
BUDGET_JS_BYTES = 15 * 1024

TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")


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


def get_commit_metadata(ref: str) -> dict[str, str]:
    """Get commit SHA and ISO date for a ref."""
    try:
        res = subprocess.run(
            ["git", "log", "-n", "1", "--format=%H%x09%cI%x09%s", ref],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        parts = res.stdout.strip().split("\t")
        if len(parts) >= 2:
            return {
                "sha": parts[0],
                "date": parts[1],
                "subject": parts[2] if len(parts) > 2 else "",
            }
    except Exception:
        pass
    return {"sha": "00000000", "date": "2026-10-10T12:00:00Z", "subject": ""}


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
        except Exception:
            tags = ["v0.1.0"]

    # Validate tags match ^v\d+\.\d+\.\d+$
    tags = [t for t in tags if TAG_RE.match(t)]

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
            issue_num = ticket.get("issue")
            issue_url = ticket.get("url")
            pr = ticket.get("pr") or {}
            pr_num = pr.get("number")
            pr_url = pr.get("url")
            cost_info = ticket.get("cost") or {}
            cost_usd = cost_info.get("total_usd") or cost_info.get("usd")
        else:
            title = meta["subject"]

        # v0.3.1 /pull/40 was PR only (not tagged as an issue; issue was 39)
        if tag == "v0.3.1":
            issue_label = "PR only"
            issue_num = None
            issue_url = None
            if not pr_num:
                pr_num = 40
                pr_url = "https://github.com/stevengonsalvez/foundry-autonomous-sdlc/pull/40"

        # Check screenshot directory and manifest
        tag_dir = screenshots_dir / tag
        manifest_file = tag_dir / "manifest.json"
        reproducible = True
        not_reproducible_reason: str | None = None
        screenshot_map: dict[str, dict[str, str]] = {r: {} for r in ROUTES}

        if manifest_file.exists():
            try:
                m_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                if m_data.get("reproducible") is False:
                    reproducible = False
                    not_reproducible_reason = m_data.get("reason", "Build failed")
                else:
                    for s in m_data.get("screenshots", []):
                        route = s.get("route")
                        vp = s.get("viewport")
                        fn = s.get("filename")
                        if route in screenshot_map and vp:
                            screenshot_map[route][vp] = fn
                    if not any(screenshot_map[r] for r in ROUTES):
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
                "screenshots": screenshot_map,
            }
        )

    # Order newest first (highest semver first)
    raw_entries.sort(key=lambda e: parse_semver_key(e["tag"]), reverse=True)

    # Attach 'before' reference (previous entry chronologically)
    for i, entry in enumerate(raw_entries):
        if i + 1 < len(raw_entries):
            prev = raw_entries[i + 1]
            entry["before"] = {
                "tag": prev["tag"],
                "reproducible": prev["reproducible"],
                "screenshots": prev["screenshots"],
            }
        else:
            entry["before"] = None

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
  color: #fff;
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

  let currentViewport = 'desktop';
  let currentRoute = 'home';

  function init() {
    setupViewportToggles();
    setupRouteToggles();
    updateView();
  }

  function setupViewportToggles() {
    const btns = document.querySelectorAll('[data-action="set-viewport"]');
    btns.forEach((btn) => {
      btn.addEventListener('click', () => {
        const vp = btn.getAttribute('data-viewport');
        if (!vp || vp === currentViewport) return;
        currentViewport = vp;
        btns.forEach((b) => {
          const active = b === btn;
          b.classList.toggle('active', active);
          b.setAttribute('aria-pressed', String(active));
        });
        updateView();
      });
    });
  }

  function setupRouteToggles() {
    const btns = document.querySelectorAll('[data-action="set-route"]');
    btns.forEach((btn) => {
      btn.addEventListener('click', () => {
        const route = btn.getAttribute('data-route');
        if (!route || route === currentRoute) return;
        currentRoute = route;
        btns.forEach((b) => {
          const active = b === btn;
          b.classList.toggle('active', active);
          b.setAttribute('aria-pressed', String(active));
        });
        updateView();
      });
    });
  }

  function updateView() {
    const images = document.querySelectorAll('img[data-route]');
    images.forEach((img) => {
      const imgRoute = img.getAttribute('data-route');
      const imgViewport = img.getAttribute('data-viewport');
      const matches = (imgRoute === currentRoute && imgViewport === currentViewport);
      img.style.display = matches ? 'block' : 'none';
    });

    const routeLabels = document.querySelectorAll('.active-route-label');
    routeLabels.forEach((el) => {
      el.textContent = currentRoute;
    });

    const vpLabels = document.querySelectorAll('.active-viewport-label');
    vpLabels.forEach((el) => {
      el.textContent = currentViewport === 'desktop' ? 'Desktop (1280px)' : 'Mobile (390px)';
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
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https://raw.githubusercontent.com; "
    "font-src 'self'; base-uri 'none'; form-action 'none'"
)

FAVICON_URI = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Crect width='32' height='32' rx='6' fill='%230e1526'/%3E"
    "%3Cpath d='M7 23l5-6 4 3 9-10' fill='none' stroke='%23818cf8' stroke-width='2.75' "
    "stroke-linecap='round' stroke-linejoin='round'/%3E"
    "%3Ccircle cx='25' cy='10' r='2.5' fill='%23818cf8'/%3E%3C/svg%3E"
)


def render_html(
    entries: list[dict[str, Any]], repo_name: str = "stevengonsalvez/foundry-autonomous-sdlc"
) -> str:
    """Render semantic HTML for the evolution page."""
    # Find Then vs Now entries
    oldest_entry = entries[-1] if entries else None
    newest_entry = entries[0] if entries else None

    # Then vs Now images (home route)
    then_img_html = ""
    if oldest_entry:
        tag_q = html.escape(oldest_entry["tag"], quote=True)
        fn_desktop = html.escape(
            oldest_entry["screenshots"].get("home", {}).get("desktop", "home-desktop.png"),
            quote=True,
        )
        then_img_html = (
            f'<img src="./screenshots/{tag_q}/{fn_desktop}" alt="{tag_q} home desktop" '
            f'loading="lazy" width="600" height="375" />'
        )

    now_img_html = ""
    if newest_entry:
        tag_q = html.escape(newest_entry["tag"], quote=True)
        fn_desktop = html.escape(
            newest_entry["screenshots"].get("home", {}).get("desktop", "home-desktop.png"),
            quote=True,
        )
        now_img_html = (
            f'<img src="./screenshots/{tag_q}/{fn_desktop}" alt="{tag_q} home desktop" '
            f'loading="lazy" width="600" height="375" />'
        )

    # Build timeline items HTML
    timeline_items_html: list[str] = []

    for entry in entries:
        raw_tag = entry["tag"]
        tag_q = html.escape(raw_tag, quote=True)
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

        if not reproducible:
            reason = html.escape(entry.get("not_reproducible_reason") or "Build failed")
            body_html = f"""
              <div class="compare-container">
                <div class="not-reproducible-box">
                  <span class="badge-alert">Not Reproducible</span>
                  <p>Reason: {reason}</p>
                </div>
              </div>
            """
        else:
            # Build images for each route and viewport for side-by-side comparison
            before = entry.get("before")
            raw_before_tag = before["tag"] if before else "Initial"
            before_tag_q = html.escape(raw_before_tag, quote=True)
            before_tag = html.escape(raw_before_tag)

            after_imgs: list[str] = []
            before_imgs: list[str] = []

            for r in ROUTES:
                for vp in VIEWPORTS:
                    # After
                    raw_fn_after = entry["screenshots"].get(r, {}).get(vp, f"{r}-{vp}.png")
                    fn_after = html.escape(raw_fn_after, quote=True)
                    src_after = f"./screenshots/{tag_q}/{fn_after}"
                    display = "block" if (r == "home" and vp == "desktop") else "none"
                    after_imgs.append(
                        f'<img src="{src_after}" alt="{tag_q} {r} {vp}" '
                        f'data-route="{r}" data-viewport="{vp}" '
                        f'style="display:{display};" loading="lazy" width="560" height="350"/>'
                    )

                    # Before
                    if before and before.get("reproducible"):
                        raw_fn_before = before["screenshots"].get(r, {}).get(vp, f"{r}-{vp}.png")
                        fn_before = html.escape(raw_fn_before, quote=True)
                        src_before = f"./screenshots/{before_tag_q}/{fn_before}"
                        before_imgs.append(
                            f'<img src="{src_before}" alt="{before_tag_q} {r} {vp}" '
                            f'data-route="{r}" data-viewport="{vp}" '
                            f'style="display:{display};" loading="lazy" width="560" height="350"/>'
                        )
                    else:
                        before_imgs.append(
                            f'<div class="no-prior" data-route="{r}" data-viewport="{vp}" '
                            f'style="display:{display};">No prior baseline ({before_tag})</div>'
                        )

            after_content = "".join(after_imgs)
            before_content = "".join(before_imgs)

            body_html = (
                f'<div class="compare-container"><div class="compare-grid">'
                f'<div class="compare-col">'
                f'<div class="compare-col-header">Before ({before_tag})</div>'
                f'<div class="compare-img-wrap">{before_content}</div></div>'
                f'<div class="compare-col">'
                f'<div class="compare-col-header">After ({tag})</div>'
                f'<div class="compare-img-wrap">{after_content}</div></div>'
                f"</div></div>"
            )

        entry_date = entry["date"]
        item_html = (
            f'<article class="timeline-item"><div class="timeline-dot" aria-hidden="true"></div>'
            f'<div class="timeline-card"><header class="timeline-card-header">'
            f'<div class="timeline-meta-left"><span class="tag-badge">{tag}</span>'
            f'<h3 class="item-title">{title}</h3></div>'
            f'<div class="timeline-meta-right"><time datetime="{entry_date}">{date}</time>'
            f"{badges_str}</div></header>{body_html}</div></article>"
        )
        timeline_items_html.append(item_html)

    if len(timeline_items_html) > 8:
        recent_items = timeline_items_html[:8]
        older_items = timeline_items_html[8:]
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

    then_tag = html.escape(oldest_entry["tag"]) if oldest_entry else "v0.1.0"
    now_tag = html.escape(newest_entry["tag"]) if newest_entry else "v0.4.0"

    return f"""<!doctype html>
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
              <span>Home Route</span>
            </div>
            <div class="card-preview-body">
              {then_img_html}
            </div>
          </div>
          <div class="card-preview">
            <div class="card-preview-header">
              <span class="card-preview-title">Current Release ({now_tag})</span>
              <span>Home Route</span>
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
            <span class="control-label" id="route-label">Route:</span>
            <div class="btn-group" role="group" aria-labelledby="route-label">
              <button type="button" class="btn-toggle active"
                data-action="set-route" data-route="home" aria-pressed="true">
                Home
              </button>
              <button type="button" class="btn-toggle"
                data-action="set-route" data-route="parcel-found" aria-pressed="false">
                Parcel Found
              </button>
              <button type="button" class="btn-toggle"
                data-action="set-route" data-route="not-found" aria-pressed="false">
                Not Found
              </button>
              <button type="button" class="btn-toggle"
                data-action="set-route" data-route="invalid-input" aria-pressed="false">
                Invalid Input
              </button>
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
    html_bytes = len(html_content.encode("utf-8"))
    if html_bytes >= BUDGET_HTML_BYTES:
        raise ValueError(f"HTML exceeds size budget: {html_bytes} >= {BUDGET_HTML_BYTES} bytes")
    html_path = output_dir / "index.html"
    html_path.write_text(html_content, encoding="utf-8")

    # 5. Link or copy screenshots directory if requested
    out_screenshots = output_dir / "screenshots"
    if screenshots_dir.exists() and screenshots_dir.resolve() != out_screenshots.resolve():
        out_screenshots.mkdir(parents=True, exist_ok=True)
        for item in screenshots_dir.iterdir():
            if item.is_dir():
                target = out_screenshots / item.name
                if not target.exists():
                    with contextlib.suppress(Exception):
                        shutil.copytree(item, target)

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
    args = parser.parse_args()

    build_history_site(
        output_dir=args.output_dir,
        screenshots_dir=args.screenshots_dir,
        state_path=args.state,
    )


if __name__ == "__main__":
    main()
