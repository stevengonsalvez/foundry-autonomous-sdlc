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
  - Colored indicator dot (6px)
  - Identifier / name in bold monospace
  - Subtitle role/description

### Ticket Pill Chips
Work items appear as compact single-line interactive pill tokens:
- Height: 24px to 28px.
- Radius: Full pill (9999px).
- Internal Composition:
  1. Ticket ID: `#24` in monospace bold
  2. State dot: 5px to 6px circular indicator (run, wait, block, info, or dashed pending)
  3. Agent micro-tag: 2-letter uppercase tag (e.g. `CO`, `TD`, `RV`)
  4. Lens metric:
     - Delivery lens: stage duration (e.g. `14s`, `2m`)
     - Cost lens: USD amount (e.g. `$0.04`)
     - Gates lens: gates ratio (e.g. `4/4`)
  5. Title: truncated title with text-overflow ellipsis
- Flags: Secondary tags (such as `Waiting for ledger` or `Rolled back`) render as quiet inline metadata.

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
- Fleet Agents: Dense status table of all agents with 2-letter badges, lifecycle state written out, and error telemetry.
- Escalations: Incident desk with crimson hairlines, terminal reasons, and direct evidence links.
- Flow Metrics: Inline SVG charts with hairline axes backed by accessible data tables.
- Audit Trail: Dense chronological ledger stream filterable by event kind and ticket number.

## 4. Responsive Model

- 1440px Desktop: Full two-dimensional matrix display with sticky swimlane spine.
- 600px to 1024px: Horizontal scrolling matrix with sticky frozen swimlane headers on the left.
- 360px Mobile: Stacked view where the board renders as a vertical list of stages, ensuring zero sideways page overflow.
