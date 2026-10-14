# Control Center Design System and Architecture

This document defines the tokens, component anatomy, layout model, and styling rules implemented in `apps/control-center`.

## 1. OKLCH Design Tokens

Defined in `:root` in `css/styles.css`, the color system utilizes an independent graphite-blue OKLCH palette calibrated for a dark mission-control environment. Chroma is restrained on neutrals and semantic tones are tuned for high contrast.

### Base Canvas and Surface Hierarchy
- `--canvas`: `oklch(0.030 0.010 215)` (Page canvas background behind all containers)
- `--surface-0`: `oklch(0.045 0.012 215)` (Base matrix panel and shell background)
- `--surface-1`: `oklch(0.075 0.014 215)` (Elevated table row and card surface)
- `--surface-2`: `oklch(0.105 0.016 215)` (Active control surface and track background)
- `--surface-3`: `oklch(0.135 0.018 215)` (Raised segmented button and hover surface)

Four evenly-spaced surface rungs between L 0.03 and 0.14 with a constant step of 0.030. Neutral surfaces are calibrated so every single neutral differs from all 5 reference dark neutrals (`ink`, `panel`, `panel-2`, `line-soft`, `line`) by dE_ok >= 0.04. Active interactive segmented buttons utilize focus and outline styling (`--edge-focus`) rather than relying on a separate surface tone.

### Hairlines and Dividers
- `--edge`: `oklch(0.380 0.025 215)` (Container boundary and matrix grid hairlines)
- `--edge-subtle`: `oklch(0.350 0.020 215)` (Interior table row and cell divider hairlines)
- `--edge-focus`: `oklch(0.72 0.16 190)` (High-visibility keyboard focus outline)

### Typography Contrast (WCAG AA Compliant >= 4.5:1)
- `--fg`: `oklch(0.985 0.005 215)` (Primary high-contrast tabular text)
- `--fg-dim`: `oklch(0.81 0.018 215)` (Secondary headers, units, and metrics)
- `--fg-muted`: `oklch(0.72 0.020 215)` (Tertiary metadata, labels, and timestamps)

### Semantic Lifecycle Roles
- `--tone-run`: `oklch(0.78 0.16 142)` (Active execution, healthy state, and pass indicators)
- `--tone-wait`: `oklch(0.78 0.15 52)` (Waiting items, pending ledger, and sim stage)
- `--tone-block`: `oklch(0.74 0.20 345)` (Blocked items, failed gates, escalations, rollbacks)
- `--tone-info`: `oklch(0.76 0.14 190)` (Informational badges, links, and contracts)
- `--tone-agent`: `oklch(0.76 0.15 325)` (Agent identity tags and role labels)
- `--tone-done`: `oklch(0.76 0.16 120)` (Completed stages, production deploys, and shipped items)

### Pipeline Stage Markers
- `--st-backlog`: `var(--fg-muted)`
- `--st-refining`: `var(--tone-wait)`
- `--st-feasible`: `var(--tone-info)`
- `--st-tests`: `var(--tone-block)`
- `--st-building`: `var(--tone-run)`
- `--st-review`: `var(--tone-agent)`
- `--st-staging`: `var(--tone-info)`
- `--st-prod`: `var(--tone-done)`
- `--st-escalated`: `var(--tone-block)`

### Flow Segment Fills (Distinct Hue Per Stage)
Per-stage flow segment fills maintain circular hue separation of >= 30 degrees (exceeding the >= 25 degree requirement) and inter-token distance of dE_ok >= 0.0842 (exceeding the >= 0.06 requirement):
- `--st-fill-backlog`: `oklch(0.60 0.04 250)` (Slate indigo hue 250 deg)
- `--st-fill-refining`: `oklch(0.68 0.14 65)` (Amber gold hue 65 deg)
- `--st-fill-feasible`: `oklch(0.68 0.14 185)` (Cyan teal hue 185 deg)
- `--st-fill-tests`: `oklch(0.68 0.14 285)` (Violet purple hue 285 deg)
- `--st-fill-building`: `oklch(0.68 0.13 145)` (Emerald green hue 145 deg)
- `--st-fill-review`: `oklch(0.68 0.14 320)` (Magenta berry hue 320 deg)
- `--st-fill-staging`: `oklch(0.68 0.14 220)` (Azure blue hue 220 deg)
- `--st-fill-prod`: `oklch(0.70 0.15 110)` (Lime olive hue 110 deg)
- `--st-fill-escalated`: `oklch(0.74 0.20 355)` (Crimson ruby hue 355 deg)

### Typography Stacks
- `--font-mono`: `ui-monospace, "SF Mono", Menlo, "JetBrains Mono", Consolas, monospace`
  Used for all IDs, numbers, labels, headers, chips, and telemetry tables.
- `--font-sans`: `system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`
  Used strictly for narrative sentences and descriptions.
- Zero Web Fonts: System fonts only, no external font requests or remote CDNs.

### Geometry, Radii, and Transitions
- Hairlines: Uniform 1px solid borders. No drop shadows, no glassmorphism, no gradient text.
- `--radius`: `4px` (Panels, containers, segmented controls, inputs)
- `--radius-sm`: `2px` (Micro-tags, state dot indicators, agent inner tags)
- `--radius-pill`: `9999px` (Status badges and ticket pill chips)
- `--dur-fast`: `120ms` (Interactive hover and focus transition timing)
- `--ease`: `cubic-bezier(0.16, 1, 0.3, 1)` (Snappy decel easing curve)
- Reduced Motion: Transitions disabled when `prefers-reduced-motion: reduce` is detected.

## 2. Component Anatomy

### Board Matrix Semantics
The delivery board is built with strict accessible grid/table semantics:
- Table Container: Renders as `role="table"` with `aria-label="Delivery flow matrix board, scrolls sideways"`.
- Sticky Swimlane Spine (`.matrix-spine`): Renders as `role="row"` containing:
  - Corner Spine Header (`.spine-head`): `role="columnheader"` with visible label `Stage`.
  - Swimlane Headers (`.lane-head`): `role="columnheader"` for each swimlane (ID `lane-<key>`), displaying the lane dot indicator, lane title, and subtitle.
- Stage Columns (`.col`): Each stage column renders as `role="row"`.
  - Stage Header Cell (`.col-head`): Renders as `role="rowheader"` (ID `col-<stage>`), containing stage title, execution mode badge, count telemetry, and status summary.
  - Coordinate Cells (`.matrix-cell`): Each intersection renders as `role="cell"` with `aria-labelledby="lane-<key> col-<stage>"`.

### Macroband Strip
Located above the matrix grid, macrobands group stages into lifecycle domains with a 2px top hairline accent in domain hue:
- `ALIGN . PRODUCT` (`.band-shape`, span 3 columns): Backlog, Refining, Feasible
- `IMPLEMENT . CODE` (`.band-build`, span 3 columns): Tests, Building, Review
- `DELIVER . OPERATIONS` (`.band-release`, span 2 columns): Staging, Production
- `EXCEPTIONS` (`.band-escalated`, span 1 column): Escalated

### Stage Headers and Mode Badges
Stage headers occupy each stage rowheader:
- Stage Title: 11px uppercase monospace.
- Mode Badge (`.mode-badge`): 8px uppercase badge indicating architectural execution model:
  - `AUTO` (`.mode-auto`): Autonomous engine loop execution (`var(--tone-run)`)
  - `GATE` (`.mode-gate`): Quality verification barrier (`var(--tone-block)`)
  - `SIM` (`.mode-sim`): Simulated interaction checkpoint (`var(--tone-wait)`)
  - `MANUAL` (`.mode-manual`): Operator checkpoint (`var(--fg-muted)`)
- Telemetry Count Line: Monospace telemetry beneath the header:
  - Delivery lens: `X in . Y wait . Z blk`
  - Cost lens: stage USD spend
  - Gates lens: percentage pass rate

### Swimlanes and Coordinates
The vertical spine organizes work items into swimlanes:
- Group Modes:
  - `Type`: Feature, Bug, Maintenance, Other (retaining unclassified items)
  - `Agent`: Assigned fleet agent or unassigned (retaining triage items)
  - `Outcome`: In-flight, Shipped, Escalated
- Lane Spine (Sticky Left Column):
  - Width: 134px minimum.
  - Colored indicator dot: 6px (`.dot-run`, `.dot-wait`, `.dot-block`, `.dot-info`, `.dot-agent`, `.dot-done`).
  - Identifier / name in bold monospace.
  - Subtitle role/description.

### Ticket Pill Chips
Work items appear as dense two-line pill tokens in the matrix grid:
- Internal Composition:
  - Line 1 (Header row): Ticket ID (`#24`), state indicator dot (11px dot with 9px glyph), 2-letter agent tag (`CO`), and contextual lens metric (`1d 2h`, `$0.07`, or `6/6`).
  - Line 2 (Body row): Ticket title with text-overflow ellipsis using the full cell width.
- State Indicator Dot (`.chip-dot`):
  - Size: 11px circular container with 9px glyph (`.dot-active`, `.dot-pending`, `.dot-wait`, `.dot-blocked`, `.dot-done`).
  - Blocked State: Features a lighter 1px outline ring (`box-shadow: 0 0 0 1px var(--tone-block)`) for dual-channel recognition without relying on color alone.
  - Screen Reader and Tooltip Text: Both `title` attribute and `.sr-only` text use identical human-readable state names: `in progress`, `pending`, `waiting`, `blocked`, `done`.
- Wide Cell Adaptivity: Container query (`@container (min-width: 260px)`) switches chip to single-line layout when cell width permits.
- Flags: Secondary tags (such as `Waiting for ledger` or `Rolled back`) render below the chip as quiet dashed badges, never rotated.

### Stepper Connectors and Node Styles
In the ticket detail progression strip:
- `.node-done`: Uses `var(--tone-done)` stroke for clear completion semantics.
- `.node-current`: Uses `var(--tone-info)` stroke with pulsing indicator.
- `.link`: Unfinished connector uses `var(--fg-muted)` at stroke-opacity 0.65 with dashed stroke (`stroke-dasharray: 4 3`), achieving 3.95:1 contrast against `--surface-0` (measured in Chromium by reading pixels, exceeding WCAG AA non-text 3:1).
- `.link-done`: Completed connector uses solid stroke in `var(--tone-done)`.

### Spend Banner
- Height: 28px slim one-line status strip.
- Geometry: 6px coral dot, monospace text, subtle coral tinted background (`oklch(0.20 0.04 345 / 0.5)`), hairline border.
- Behavior: Visible across pages when spend exceeds halt line or cap, linking directly to Cost view.

### Fleet Agents
- Presentation: Dense data table replacing generic cards.
- Columns: State (dot and text), Agent name, Last active, Calls, Tokens in, Tokens out, Spend, Errors, Working on.
- Error Telemetry: Error rows highlighted with coral text and dot, avoiding large red card boxes.

### Flow Metrics
- Palette: Unified muted tone (`oklch(0.50 0.04 215)`) for standard stage bars and per-ticket stacked segments.
- Semantic Accents: Golden amber strictly for waiting/backlog, coral strictly for failed or escalated.
- Legend: Pure text labels without colored swatches.

### Non-Applicable and Empty Cells
- Empty Cells: 1px hairline dark panel with clear coordinates.
- Hatched Cells (`cell-hatched`): 135-degree repeating diagonal stripe pattern with a quiet `bypasses stage` label. Tickets in bypassed stages are never swallowed.

### Segmented Controls and Toolbar
- Dual segmented selectors (`lens` and `group`) with 1px hairline frames and `role="group"`.
- Toolbar Type Filter: Renders as `role="group"` with `aria-label="Filter by type"`.
- Instant state updates and full keyboard focus ring (`--edge-focus`).

## 3. View Restyling and Layout Consistency

All 8 application views share the same mission-control visual language:
- Delivery Flow: Matrix grid with macroband row, sticky swimlane spine, and interactive lens/group controls.
- Ticket Detail: Compact stage progression strip, 2-column tabular cost breakdown, aligned gate verification results, and chronological timeline.
- Environments: Compact matrix comparison table for Staging and Production (version, commit, deploy timestamp, gates cleared pills, run link, included changes).
- Cost: Dense hairline tables comparing ledger estimates against Azure billed costs, with over-cap indicators.
- Fleet Agents: Dense status table of all active and registered fleet agents with 2-letter badges, lifecycle state written out, and error telemetry.
- Escalations: Incident desk with crimson hairlines, terminal reasons, and direct evidence links.
- Flow Metrics: Inline SVG charts with hairline axes backed by accessible data tables.
- Audit Trail: Dense chronological ledger stream filterable by event kind and ticket number.

## 4. Responsive Model

- 1440px Desktop: Full two-dimensional matrix display fitting all 9 stage columns and the Escalated stage without horizontal scroll.
- 1280px Desktop: Fits all 9 stage columns and lane column with zero horizontal scroll.
- Below 1100px: Horizontal scrolling matrix with sticky frozen swimlane headers on the left.
- Below 640px Mobile: Stacked view where the board renders as a vertical list of stages, ensuring zero sideways page overflow.
