# Control Center Design Blueprint

This document specifies the design system, visual hierarchy, and UI architecture for the Control Center. It synthesizes operational dashboard patterns into a blueprint for monitoring the autonomous software delivery lifecycle (SDLC) from backlog to production.

---

## 1. Executive Summary and Architectural Principles

The Control Center is an operational dashboard for automated software delivery. It provides full observability into ticket lifecycles, pipeline stage transitions, quality gate verifications, environment hops, worker agent processes, financial ledger records, and conversational audit trails.

### Core Architectural Principles
- **Operational Clarity:** Present complex multi-stage delivery workflows at a glance without sacrificing technical depth.
- **Instrument-Grade Precision:** Calibrated like an industrial cockpit: dense, metric-first, and deterministic with tabular numbers for financial figures and timestamps.
- **Truth in Presentation:** Display raw, verified data directly from ledger events (`state.json`). When data is unread, pending, or stale (> 10 minutes), the interface states this plainly rather than showing invented placeholders.
- **Zero External Network Dependencies:** Strict Content Security Policy (`font-src 'self'`, `default-src 'none'`) with zero external fonts, zero external CDN scripts, and zero build-step runtime requirements.
- **Text-Only DOM Construction:** All dynamic strings (titles, logs, commit hashes, notes) are created using `document.createTextNode` or `element.textContent`, eliminating HTML injection vulnerabilities.
- **Inclusive Accessibility:** WCAG 2.1 AA compliant across light and dark modes, honoring reduced motion preferences (`prefers-reduced-motion: reduce`) and responsive viewports down to 360 px width without horizontal root page scroll.

---

## 2. Typography and System Font Strategy

### System Font Philosophy
The Control Center explicitly avoids loading external fonts (such as Google Fonts or external CDN typefaces) over the network. This design choice provides several key operational guarantees:
- **Strict CSP Adherence:** The Content Security Policy specifies `font-src 'self'`, which strictly prohibits fetching webfonts from third-party hosts.
- **Zero Network Latency and Zero FOUT:** Eliminates flash of unstyled text (FOUT) and flash of invisible text (FOIT). The UI paints instantly upon HTML parsing.
- **Deterministic Offline Support:** Operates seamlessly in air-gapped, offline, or restricted intranet environments.

### Font Stacks
1. **Sans-Serif Stack (`--font-sans` in `theme.css`, aliased to `--font` in `styles.css`):**
   ```css
   --font-sans: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, system-ui, sans-serif;
   ```
   Local "Inter" is listed first and is utilized only if installed on the host system. When "Inter" is not present locally, the browser falls back directly to high-quality native operating system stacks:
   - `-apple-system` and `BlinkMacSystemFont` on macOS and iOS.
   - `"Segoe UI"` on Windows.
   - `Roboto` on Android and ChromeOS.
   - `system-ui` for modern OS UI font definitions.
   - `sans-serif` as the generic fallback.

2. **Monospace Stack (`--font-mono` in `theme.css` and `styles.css`):**
   ```css
   --font-mono: "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, Monaco, Consolas, "Liberation Mono", monospace;
   ```
   Local "IBM Plex Mono" is utilized only if installed on the local machine. If not installed locally, the browser falls back directly to native platform monospace stacks:
   - `ui-monospace` and `"SF Mono"` on Apple platforms.
   - `Menlo` and `Monaco` on macOS.
   - `Consolas` on Windows.
   - `"Liberation Mono"` on Linux distributions.
   - `monospace` as the generic fallback.

3. **Tabular Figures:**
   All numerical data, ticket numbers, commit SHAs, currency totals, percentages, stage codes, and timestamps use `font-variant-numeric: tabular-nums` to ensure exact columnar alignment across dense tables and grids.

---

## 3. Design Tokens and Theme Architecture

The design token system is established across `css/theme.css` and `css/styles.css`. Core tokens provide semantic color mappings, surface elevations, borders, spacing units, and corner radii.

### 3.1 Surface and Background Tokens
- `--bg`: Root canvas background, defined via `light-dark(oklch(98.4% 0.004 265), oklch(15.5% 0.012 265))`.
- `--bg-app`: Top-level application container background (`#f6f8fa` light, `#0e1217` dark).
- `--bg-panel`: Primary panel and card surface background (`#ffffff` light, `#161c24` dark).
- `--bg-panel-elevated`: Elevated card surface background (`#ffffff` light, `#1b232d` dark).
- `--bg-surface`: Secondary surface tint (`#f1f5f9` light, `#1f2833` dark).
- `--bg-surface-hover`: Surface hover state background (`#e2e8f0` light, `#27313d` dark).
- `--bg-subtle`: Subtle recessed background (`#f8fafc` light, `#12171e` dark).
- `--surface`: Base component surface, defined via `light-dark(oklch(100% 0 0), oklch(20% 0.014 265))`.
- `--surface-2`: Secondary elevated surface, defined via `light-dark(oklch(97.2% 0.006 265), oklch(23.5% 0.015 265))`.
- `--surface-3`: Tertiary surface, defined via `light-dark(oklch(94.8% 0.008 265), oklch(27% 0.016 265))`.

### 3.2 Border and Divider Tokens
- `--line`: Primary structural border delimiter (`#d0d7de` light, `#27313d` dark; also `light-dark(oklch(91% 0.01 265), oklch(29.5% 0.015 265))`).
- `--line-soft`: Subtle secondary delimiter (`#e2e8f0` light, `#1f2832` dark).
- `--line-strong`: High-contrast border delimiter (`#94a3b8` light, `#3e4c5e` dark; also `light-dark(oklch(82% 0.014 265), oklch(40% 0.018 265))`).

### 3.3 Text Ink Tokens
- `--text-primary`: Primary reading text ink (`#0f172a` light, `#f1f5f9` dark).
- `--text-secondary`: Secondary text ink (`#334155` light, `#cbd6e3` dark).
- `--text-muted`: Muted metadata text ink (`#64748b` light, `#8b9bb0` dark).
- `--text-faint`: De-emphasized or disabled text ink (`#94a3b8` light, `#5a697a` dark).

### 3.4 Interactive and Accent Tokens
- `--accent`: Primary interactive accent (`#2563eb` light, `#6fa8ff` dark; and `light-dark(oklch(50% 0.19 270), oklch(73% 0.14 270))`).
- `--focus-ring`: Focus outline indicator (`#2563eb` light, `#6fa8ff` dark).

### 3.5 Semantic Status Tokens
- `--auto`: Autonomous execution status green (`#059669` light, `#2dd4a7` dark), paired with `--auto-bg` and `--auto-border`.
- `--assist`: Operator guidance status amber (`#d97706` light, `#f2b23d` dark), paired with `--assist-bg` and `--assist-border`.
- `--gate`: Quality gate threshold status red (`#dc2626` light, `#f0644b` dark), paired with `--gate-bg` and `--gate-border`.
- `--dit`: Delivery-in-transit status blue (`#2563eb` light, `#6fa8ff` dark), paired with `--dit-bg` and `--dit-border`.
- `--contract`: Contract and schema status cyan (`#0891b2` light, `#22d3ee` dark), paired with `--contract-bg` and `--contract-border`.
- `--ephem`: Ephemeral resource status purple (`#7c3aed` light, `#c084fc` dark), paired with `--ephem-bg` and `--ephem-border`.
- `--done`: Terminal completed status slate (`#475569` light, `#94a3b8` dark), paired with `--done-bg` and `--done-border`.

### 3.6 Macro Phase Accent Tokens (`--macro-*`)
Defined in `css/board.css` for grouping column sets:
- `--macro-inception`: Inception phase accent (`#8ab4ff` light, `#6fa8ff` dark).
- `--macro-construction`: Construction phase accent (`#7fd1a6` light, `#7fd1a6` dark).
- `--macro-release`: Release phase accent (`#2dd4a7` light, `#2dd4a7` dark).
- `--macro-exception`: Exception phase accent (`#f0644b` light, `#f0644b` dark).
- `--macro-color`: Dynamically assigned to each column group header bar.

### 3.7 Stage Status Tone Tokens (`--st-*`)
Defined in `css/styles.css` using `light-dark()` notation:
- `--st-backlog`: `light-dark(oklch(60% 0.03 265), oklch(66% 0.03 265))`
- `--st-refining`: `light-dark(oklch(66% 0.15 75), oklch(76% 0.14 78))`
- `--st-feasible`: `light-dark(oklch(62% 0.15 140), oklch(74% 0.15 140))`
- `--st-tests`: `light-dark(oklch(60% 0.12 190), oklch(74% 0.11 190))`
- `--st-building`: `light-dark(oklch(56% 0.16 245), oklch(72% 0.13 245))`
- `--st-review`: `light-dark(oklch(52% 0.19 275), oklch(70% 0.16 275))`
- `--st-staging`: `light-dark(oklch(56% 0.19 310), oklch(72% 0.15 310))`
- `--st-prod`: `light-dark(oklch(54% 0.15 155), oklch(74% 0.15 155))`
- `--st-escalated`: `light-dark(oklch(56% 0.2 25), oklch(70% 0.17 25))`

### 3.8 Spacing Scale Tokens (`--space-*`)
A 4 px base spacing scale configured systematically across components:
- `--space-1`: 4px (0.25rem)
- `--space-2`: 8px (0.5rem)
- `--space-3`: 12px (0.75rem)
- `--space-4`: 16px (1rem)
- `--space-5`: 20px (1.5rem in styles.css)
- `--space-6`: 28px (2rem in styles.css)
- `--space-7`: 40px (3rem in styles.css)

### 3.9 Border Radius Tokens (`--radius-*`)
- `--radius-xs`: 3px
- `--radius-sm`: 6px (0.5rem in styles.css)
- `--radius-md`: 9px (0.875rem in styles.css)
- `--radius-lg`: 12px
- `--radius-pill`: 9999px

---

## 4. Light and Dark Theme Implementation

The Control Center provides seamless light and dark mode presentation through a unified architecture combining native CSS `light-dark()`, media queries, and manual override persistence.

### 4.1 Implementation Mechanism
1. **Declaration on Root:**
   The root stylesheet declares `color-scheme: light dark` on `:root`. This informs the browser rendering engine that the document natively supports both modes.
2. **`light-dark()` Notation:**
   Variables defined with `light-dark(lightValue, darkValue)` automatically resolve to the active color scheme without requiring separate stylesheet overrides.
3. **Media Query and Data Attribute Selectors:**
   - Default light styles are declared under `:root`.
   - Dark theme variables are activated by system preference via `@media (prefers-color-scheme: dark)` on `:root:not([data-theme="light"])`.
   - Explicit manual dark mode is activated via `[data-theme="dark"]`.
   - Explicit manual light mode is activated via `[data-theme="light"]`.

### 4.2 Flash of Unstyled Content (FOUC) Prevention
A synchronous, blocking script (`js/theme.js`) is placed directly in the document `<head>`:
```javascript
(function () {
  try {
    var saved = localStorage.getItem('cc-theme');
    if (saved === 'light' || saved === 'dark') {
      document.documentElement.setAttribute('data-theme', saved);
    }
  } catch (error) {
    /* storage can be blocked; system theme applies */
  }
})();
```
Because this script executes before first paint and before the DOM body begins parsing, the appropriate `data-theme` attribute is set immediately. The page never flickers or flashes the wrong theme on reload.

### 4.3 Three-Way Manual Switcher
The theme toggle button (`#theme-toggle`) in `js/shell.js` cycles through three states:
- **Auto (System Match):** Removes the `data-theme` attribute from `document.documentElement` and clears the `cc-theme` key in `localStorage`. The page responds dynamically to the host operating system setting.
- **Light:** Applies `data-theme="light"` to `document.documentElement` and writes `'light'` to `localStorage`.
- **Dark:** Applies `data-theme="dark"` to `document.documentElement` and writes `'dark'` to `localStorage`.

All storage operations are safely wrapped in try-catch handlers so that private browsing modes or restricted cookie storage policies do not cause runtime failures.

---

## 5. Header Architecture, Status Beacon, Spend Callout, and Navigation

### 5.1 Top Header Bar (`.topbar`)
The top bar provides brand identity, live status diagnostics, repository naming, and global action controls:
- **Brand Identity (`.brand`):** Anchors the home view link (`#/`) with an SVG logo mark and application title.
- **Header Status Beacon (`#brand-beacon`):**
  - A circular 11 px status indicator situated immediately alongside the brand mark.
  - Dynamically evaluated by `mountShell` using `freshness(state, nowMs)`.
  - When the snapshot is fresh (less than 10 minutes old), the beacon has the `.is-live` class and pulses smoothly via CSS animation (`@keyframes beacon-pulse`), indicating an active event stream.
  - When the snapshot exceeds 10 minutes (`STALE_AFTER_S = 600`), the beacon receives the `.is-stale` class, stops pulsing, transitions to warning tones, and updates its accessible tooltip to warn operators of a stale snapshot.
- **Repository Eyebrow (`#repo-name`):** Displays the active GitHub repository name as plain text.
- **Operational Tools (`#tools`):**
  - Freshness readout (`#freshness`): displays relative update elapsed time, last ledger event timestamp, data source badge (`source: raw` or `source: api`), and problem counters if fetch errors occur.
  - Manual refresh button (`#refresh`): triggers on-demand ledger updates with an animated busy state (`aria-busy`).
  - Theme button (`#theme-toggle`): displays active theme icon and status label.

### 5.2 Spend Threshold Callout Banner (`#banner`)
The spend threshold callout sits directly below the top bar and above the main view container. It provides automated financial protection alerting:
- **Activation Logic:** Checked on every snapshot paint. If `totals.halted` or `totals.over_cap` is true, and the operator is not currently viewing the Cost view (`route !== 'cost'`), the banner displays.
- **Presentation:** A prominent warning callout (`.spend-banner` inside `.container`) featuring an alert icon and plain language financial status:
  - If spend exceeded the hard cap: "Spend is over the cap: Azure billed $X. The loop is halted. See the cost view."
  - If spend exceeded the soft halt line: "Spend is over the halt line: Azure billed $X. The loop is halted. See the cost view."
- **Deep Link Navigation:** Clicking the banner navigates directly to `#/cost`.
- **Automated Dismissal:** Clears completely when spend is below limits or when the operator navigates into the Cost view itself.

### 5.3 Navigation Rail (`#nav`)
The navigation rail organizes the Control Center into 7 core hash routes and deep-linked subviews:
1. `#/` (Board: live delivery matrix organizing tickets across macro phases and stages).
2. `#/environments` (Environments: deployment targets, staging and production release hops, rollback status).
3. `#/cost` (Cost: compute ledger cost estimates vs billed Azure cloud spend, halt caps, ticket expense tables).
4. `#/agents` (Agents: registered worker agents, run states, execution heartbeats, last error logs).
5. `#/escalations` (Escalations: tickets requiring human intervention, with a live numeric badge pill).
6. `#/flow` (Flow: cycle time distributions, dwell time per stage, throughput, rework loop analytics).
7. `#/trail` (Trail: questions to product owners, code review feedback, triage diagnoses, chronological traces).

Subviews and fallback routes:
- `#/ticket/:issue` (Ticket detail inspector showing end-to-end stage timeline, gate matrix, deployment hops, and spend).
- `#/not-found` (Fallback view for invalid routes or missing ticket identifiers).

The active route is marked with `aria-current="page"` (or `aria-current="true"` for ticket inspector views).

---

## 6. KPI Card Band (Delivery Cockpit)

The KPI cockpit on the Board view is an always-visible, fixed 6-card metric grid (`<dl class="kpis board-kpis">`) positioned above the board toolbar. It maintains consistent vertical structure across visits without any folding controls or drawer toggles.

### The Six KPI Cards
1. **Total Tickets (`.kpi-edge-total`):**
   Displays the total count of tickets known to the ledger across all stages.
2. **In Flight (`.kpi-transit`, `.kpi-edge-flight`):**
   Displays the count of tickets actively progressing through refining, feasibility, testing, building, review, and staging.
3. **In Production (`.kpi-good`, `.kpi-edge-prod`):**
   Displays the count of tickets successfully deployed and running in production.
4. **Escalated (`.kpi-bad`, `.kpi-edge-escalated`):**
   Displays the count of tickets halted due to errors, gate failures, or budget limits. Accented with error red when greater than zero.
5. **Ledger Estimate (`.kpi-edge-ledger`):**
   Displays the cumulative estimated compute cost in USD computed from token usage and execution models.
6. **Azure Billed (`.kpi-edge-billed`):**
   Displays actual billed spend reported by Azure billing integration. Displays "not read yet" if billing data has not been retrieved. Accented with error red if the loop is halted.

### Layout and Responsive Behavior
- **Desktop (> 820 px):** Rendered as a single row with 6 equal columns (`grid-template-columns: repeat(6, 1fr)`).
- **Mobile and Tablet (<= 820 px):** Reflows into a 2-column grid (`grid-template-columns: repeat(2, 1fr)`), keeping all 6 cards visible without horizontal scroll.

---

## 7. The Nine-Stage Operational Pipeline and Macro Phases

The autonomous delivery lifecycle organizes work across 9 operational stages structured into 3 sequential macro phases (Inception & Scoping, Construction & Verification, Release & Production), plus an exception lane.

### 7.1 Pipeline Structure Overview

| Macro Phase | Stage Code | Stage Title | Category | Operational Purpose |
|---|---|---|---|---|
| **Inception & Scoping** | `backlog` | Backlog | Intake | Raw issues and tasks ingested from GitHub repository. |
| **Inception & Scoping** | `refining` | Refining | Flow | Autonomous requirements analysis, acceptance criteria, and task decomposition. |
| **Inception & Scoping** | `feasible` | Feasible | Gate | Verification of technical feasibility, architecture constraints, and budget caps. |
| **Construction & Verification** | `tests` | Tests | Flow | Authoring test suites and contracts test-first before code implementation. |
| **Construction & Verification** | `building` | Building | Flow | Autonomous code generation and implementation to fulfill tests. |
| **Construction & Verification** | `review` | Review | Gate | Validation of tests, lint checks, static analysis, and code review criteria. |
| **Release & Production** | `staging` | Staging | Gate | Deployment to staging, execution of smoke and soak tests, health verification. |
| **Release & Production** | `prod` | Prod | Terminal | Deployment to production environment with ongoing operational telemetry. |
| **Exception** | `escalated` | Escalated | Exception | Tickets requiring human operator intervention due to gate failures or errors. |

### 7.2 Macro Phase 1: Inception & Scoping (`--macro-inception`)
- **Visual Grouping:** Spans the first 3 columns (`backlog`, `refining`, `feasible`) under a blue header bar (`#8ab4ff` light, `#6fa8ff` dark).
- **Stage Details:**
  1. `backlog`: Intake repository for unrefined issues, bugs, and feature requests. Holds pending items awaiting ingestion.
  2. `refining`: Flow stage where ticket requirements, scope boundaries, acceptance criteria, and file contracts are clarified.
  3. `feasible`: Gate threshold ensuring the work is technically viable, within project boundaries, and under cost estimation limits before engineering begins.

### 7.3 Macro Phase 2: Construction & Verification (`--macro-construction`)
- **Visual Grouping:** Spans the next 3 columns (`tests`, `building`, `review`) under a sage green header bar (`#7fd1a6`).
- **Stage Details:**
  4. `tests`: Flow stage enforcing test-driven development. Automated unit, integration, and contract test suites are generated before production code.
  5. `building`: Flow stage where automated code generation implements solutions that satisfy the authored test contracts.
  6. `review`: Gate threshold running automated linters, static analysis, test suites, branch protection checks, and code review verdicts. Failed checks cycle tickets back for rework.

### 7.4 Macro Phase 3: Release & Production (`--macro-release`)
- **Visual Grouping:** Spans the next 2 columns (`staging`, `prod`) under a teal header bar (`#2dd4a7`), tagged in the UI as Release & Operations.
- **Stage Details:**
  7. `staging`: Gate threshold where release artifacts are deployed to staging environments, verified with automated smoke tests and soak tests, and checked for regressions.
  8. `prod`: Terminal operational stage. Artifacts are deployed to production and monitored with live telemetry.

### 7.5 Exception Lane (`--macro-exception`)
- **Visual Grouping:** Spans the final column (`escalated`) under a coral red header bar (`#f0644b`).
- **Stage Details:**
  9. `escalated`: Holds tickets that encountered unresolvable merge conflicts, repeated gate verification failures, budget limit halts, or unexpected runtime exceptions. Escalated tickets pause execution until human operators review and resolve the issue.

### 7.6 Visual Presentation on the Board
- **Macro Phase Band (`.macro-band`):** Positioned immediately above column headers. Features distinct accent border, phase title, stage count, and total ticket counter for that phase.
- **Column Headers:** Monospace stage title, category chip (`Intake`, `Flow`, `Gate`, `Terminal`, `Exception`), and count badge.
- **Ticket Cards (`.card`):** Displays issue number, title clamped to 2 lines, type badge (`Feature`, `Bug`, `Task`), per-ticket spend progress bar against the 3.00 USD ticket cap, time-in-stage duration, and status indicators.

---

## 8. Ticket Detail Inspector (`#/ticket/:issue`)

The ticket detail view provides comprehensive diagnostic tracing for a single issue:
1. **Summary Header:** Issue key, full title, type badge, environment badge, GitHub link, and total compute expense.
2. **Stage Progression Stepper:** Horizontal visual stepper displaying every visit across all 9 stages, recording dwell time, entry timestamps, and rework cycle loops.
3. **Policy Gate Verification Grid:** Dedicated matrix evaluating all quality gates: Tests, Coverage, End-to-End, Secret Scan, Tests-First order, Scope check, Review, Smoke test, and Soak test. Displays pass/fail status, attempt counts, and first-attempt pass indicators.
4. **Environment Deployment Trail:** Visualizes progression through deployment hops (Staging -> Smoke -> Soak -> Production), linking commit SHAs and workflow run URLs.
5. **Conversational Trail:** Accordion cards documenting recorded questions to the product owner, automated responses, code review verdicts, and triage diagnosis traces.

---

## 9. Security, CSP, and Implementation Guarantees

All interface code strictly adheres to these security rules:
1. **Text-Only DOM Construction:**
   Dynamic text is strictly inserted via `document.createTextNode` or `element.textContent`. The codebase contains zero instances of `innerHTML`, `outerHTML`, `insertAdjacentHTML`, or `eval`.
2. **Strict Content Security Policy:**
   Inline script tags and inline `style="..."` attributes are prohibited and blocked by automated tests. Dynamic styling (such as progress bar percentages or chart dimensions) is applied exclusively via CSS custom property assignment (`el.style.setProperty('--bar-width', pct)`).
3. **Safe URL Handling:**
   All outbound links are sanitized through `safeGithubUrl` and `isSafeHref`. Links are restricted to verified repository paths and fragments, with `rel="noopener noreferrer"` applied to all external targets.
4. **Zero Em-Dash Rule:**
   In accordance with project typography standards, em-dashes are never used in documentation or interface text. Hyphens, colons, or parentheses are used instead.
