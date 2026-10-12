# Control Center Design System and Architecture

This document defines the real tokens, component anatomy, layout model, and styling rules implemented in `apps/control-center`.

## 1. OKLCH Design Tokens

Defined in `:root` in `css/styles.css`, the color system utilizes an independent graphite-blue OKLCH palette calibrated for a dark mission-control environment. Chroma is restrained on neutrals and semantic tones are tuned for high contrast.

### Base Canvas and Surface Hierarchy
- `--canvas`: `oklch(0.13 0.022 240)` (Graphite-blue canvas background)
- `--surface-0`: `oklch(0.16 0.025 240)` (Base container and matrix panel background)
- `--surface-1`: `oklch(0.19 0.028 240)` (Subtle elevated panel and table row surface)
- `--surface-2`: `oklch(0.23 0.030 240)` (Active controls, hover states, and card surfaces)
- `--surface-3`: `oklch(0.27 0.035 240)` (Selected segmented buttons and pressed states)
- `--surface-active`: `oklch(0.30 0.038 240)` (Focused interactive items)

### Hairlines and Dividers
- `--edge`: `oklch(0.29 0.025 240)` (Crisp 1px grid hairline border)
- `--edge-subtle`: `oklch(0.21 0.020 240)` (Subdued interior row divider and table stroke)
- `--edge-focus`: `oklch(0.72 0.16 220)` (High-visibility keyboard focus outline)

### Typography Contrast (WCAG AA Compliant >= 4.5:1)
- `--fg`: `oklch(0.93 0.015 240)` (High-legibility primary foreground text)
- `--fg-dim`: `oklch(0.79 0.020 240)` (Secondary text for headers, units, and metrics)
- `--fg-muted`: `oklch(0.66 0.022 240)` (Tertiary metadata, labels, and timestamps)

### Semantic Lifecycle Roles
- `--tone-run`: `oklch(0.78 0.16 150)` (Emerald mint: autonomous execution, active in-flight, healthy state)
- `--tone-wait`: `oklch(0.78 0.15 65)` (Golden amber: queued items, pending simulation, waiting for ledger)
- `--tone-block`: `oklch(0.68 0.20 25)` (Crimson: gate checks, blocked items, escalations, rollbacks)
- `--tone-info`: `oklch(0.75 0.14 220)` (Sky azure: links, shape domain, requirements contracts)
- `--tone-agent`: `oklch(0.76 0.15 295)` (Electric violet: agent roles and release domain)
- `--tone-done`: `oklch(0.78 0.13 175)` (Teal: completed stages, production deployments)

### Typography Stacks
- Monospace Stack: `ui-monospace, "SF Mono", Menlo, "JetBrains Mono", Consolas, monospace`
  Used for all IDs, numbers, labels, headers, chips, and telemetry tables.
- Prose Stack: `system-ui, -apple-system, sans-serif`
  Used strictly for narrative sentences and descriptions.
- Zero Web Fonts: System fonts only, no external font requests or remote CDNs.

### Hairlines, Radii, and Transitions
- Hairlines: Uniform 1px solid borders. No drop shadows, no glassmorphism, no gradient text.
- Radii: 4px for rectangular panels, inputs, and controls; 9999px (full pill) for chips and badges.
- Transitions: 120ms to 180ms ease-out on interactive chips and controls. Disabled under `prefers-reduced-motion`.

## 2. Component Anatomy

### Macroband Strip
Located at the top of the Delivery flow matrix, macrobands group stages into logical lifecycle domains:
- `SHAPE . BUSINESS`: Backlog, Refining, Feasible
- `BUILD . ENGINEERING`: Tests, Building, Review
- `RELEASE . OPS`: Staging, Production
- `ESCALATED`: Escalated
Each macroband features a 2px top accent line in its domain hue and tracked uppercase monospace typography (9.5px, letter-spacing 0.08em).

### Stage Headers and Mode Badges
Stage headers occupy the column header row:
- Stage Title: 11px uppercase monospace.
- Mode Badge: 8px uppercase badge positioned adjacent to the stage name:
  - `AUTO`: Emerald mint (autonomous agent execution)
  - `GATE`: Crimson (hard verification gate)
  - `SIM`: Golden amber (simulated product owner interaction)
  - `MANUAL`: Grey outline (operator checkpoint)
- Telemetry Count Line: Quiet 8.5px monospace status line beneath the header:
  - Delivery lens: `X in . Y wait . Z blk`
  - Cost lens: stage USD spend
  - Gates lens: percentage pass rate

### Swimlanes and Coordinates
The vertical axis organizes work items into swimlanes:
- Group Modes:
  - `Type`: Feature, Bug, Maintenance, Other (unclassified tickets retained)
  - `Agent`: Assigned fleet agent or unassigned (triage tickets retained)
  - `Outcome`: In-flight, Shipped, Escalated
- Lane Spine (Sticky Left Column):
  - Fixed 134px width aligned with macroband spacer.
  - Colored indicator dot (6px).
  - Identifier / name in bold monospace.
  - Subtitle role/description.

### Ticket Pill Chips
Work items appear as dense two-line pill tokens in the matrix grid:
- Internal Composition:
  - Line 1 (Header row): Ticket ID (`#24`), state indicator dot (5px), 2-letter agent tag (`CO`), and lens metric (`1d 2h`, `$0.07`, or `6/6`).
  - Line 2 (Body row): Ticket title with text-overflow ellipsis using the full cell width for high legibility.
- Wide Cell Adaptivity: Container query (`@container (min-width: 260px)`) smoothly shifts chip to single-line layout when cell width permits (e.g. mobile stacked stage list).
- Flags: Secondary tags (such as `Waiting for ledger` or `Rolled back`) render below the chip as quiet dashed badges, never rotated.

### Spend Banner
- Height: 28px slim one-line status strip.
- Geometry: 6px coral dot, monospace text, subtle coral tinted background, hairline border.
- Behavior: Visible across pages when spend exceeds halt line or cap, linking directly to Cost view.

### Fleet Agents
- Presentation: Dense 9-column data table replacing generic cards.
- Columns: State (dot and text), Agent name, Last active, Calls, Tokens in, Tokens out, Spend, Errors, Working on.
- Error Telemetry: Error rows highlighted with coral text and dot, avoiding large red card boxes.

### Flow Metrics
- Palette: Unified muted tone (`oklch(0.50 0.04 240)`) for standard stage bars and per-ticket stacked segments.
- Semantic Accents: Golden amber strictly for waiting/backlog, coral strictly for failed or escalated.
- Legend: Pure text labels without colored swatches.

### Non-Applicable and Empty Cells
- Empty Cells: 1px hairline dark panel with clear coordinates.
- Hatched Cells (`cell-hatched`): 135-degree repeating diagonal stripe pattern with a quiet `bypasses stage` label. Tickets in bypassed stages are never swallowed.

### Segmented Controls
- Dual segmented selectors (`lens` and `group`) with 1px hairline frames.
- Accessible `role="group"` with descriptive `aria-label` ('Lens' and 'Swimlane group').
- Lifted active segment with crisp monospace labels and instant state updates.

## 3. View Restyling and Layout Consistency

All 8 application views share the same mission-control visual language:
- Delivery Flow: Matrix grid with macroband row, sticky swimlane spine, and interactive lens/group controls.
- Ticket Detail: Compact stage progression strip, 2-column tabular cost breakdown, aligned gate verification results, and chronological timeline.
- Environments: Compact matrix comparison table for Staging and Production (version, commit, deploy timestamp, gates cleared pills, run link, included changes).
- Cost: Dense hairline tables comparing ledger estimates against Azure billed costs, with over-cap indicators.
- Fleet Agents: Dense status table of all 11 agents with 2-letter badges, lifecycle state written out, and error telemetry.
- Escalations: Incident desk with crimson hairlines, terminal reasons, and direct evidence links.
- Flow Metrics: Inline SVG charts with hairline axes backed by accessible data tables.
- Audit Trail: Dense chronological ledger stream filterable by event kind and ticket number.

## 4. Responsive Model

- 1440px Desktop: Full two-dimensional matrix display fitting all 9 stage columns and the Escalated stage without horizontal scroll.
- 1280px Desktop: Fits all 9 stage columns and lane column with zero horizontal scroll.
- Below 1100px: Horizontal scrolling matrix with sticky frozen swimlane headers on the left.
- Below 640px Mobile: Stacked view where the board renders as a vertical list of stages, ensuring zero sideways page overflow.
