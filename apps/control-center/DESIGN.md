# Control Center Design System and Architecture

This document defines the real tokens, component anatomy, layout model, and styling rules implemented in `apps/control-center`.

## 1. OKLCH Design Tokens

Defined once in `css/tokens.css`, the color system utilizes an OKLCH palette calibrated for a dark mission-control environment. Chroma is restrained on neutrals and tinted toward navy.

### Base Canvas and Surface Hierarchy
- `--ink`: `oklch(0.14 0.015 255)` (Deep navy/black canvas background)
- `--panel`: `oklch(0.18 0.018 255)` (Primary container and matrix panel background)
- `--panel-2`: `oklch(0.22 0.020 255)` (Elevated surface for inputs, buttons, and segmented selectors)

### Hairlines and Dividers
- `--line`: `oklch(0.32 0.025 255)` (Crisp 1px grid hairline border)
- `--line-soft`: `oklch(0.25 0.018 255)` (Subdued interior row divider and table stroke)

### Typography Contrast
- `--text`: `oklch(0.92 0.012 250)` (High-legibility primary foreground text)
- `--muted`: `oklch(0.65 0.020 250)` (Secondary text for headers, units, and metrics)
- `--muted-2`: `oklch(0.48 0.018 250)` (Dim tertiary metadata and watermark labels)

### Semantic Lifecycle Roles
- `--auto`: `oklch(0.78 0.15 165)` (Teal / mint: autonomous agent execution, healthy state, passing checks)
- `--assist`: `oklch(0.78 0.16 80)` (Warm amber: queued items, in-progress transitions, warning limits)
- `--gate`: `oklch(0.68 0.19 30)` (Coral / vermilion: verification gates, blocked items, escalations, rollbacks)
- `--info`: `oklch(0.72 0.14 250)` (Cornflower blue: navigation accents, focus rings, simulation indicators)
- `--agent`: `oklch(0.75 0.15 290)` (Purple / orchid: agent fleet indicators and specialized badges)
- `--done`: `oklch(0.40 0.018 255)` (Slate grey: completed and archived items)
- `--cyan`: `oklch(0.78 0.14 200)` (Cyan: contract checks and environment links)

### Typography Stacks
- Monospace Stack: `ui-monospace, "SF Mono", Menlo, "JetBrains Mono", Consolas, monospace`
  Used for all IDs, numbers, labels, headers, chips, and telemetry tables.
- Prose Stack: `system-ui, -apple-system, sans-serif`
  Used strictly for narrative sentences and descriptions.
- Zero Web Fonts: No external font requests, CDNs, or remote resources.

### Hairlines, Radii, and Transitions
- Hairlines: Uniform 1px solid borders. No drop shadows, no glassmorphism, no gradient text.
- Radii: 4px for rectangular panels, inputs, and controls; 9999px (full pill) for chips and badges.
- Transitions: 120ms to 180ms ease-out on interactive chips and controls. Disabled under `prefers-reduced-motion`.

## 2. Component Anatomy

### Macroband Strip
Located at the top row of the Delivery flow matrix, macrobands group stages into logical lifecycle domains:
- `SHAPE . BUSINESS`: Backlog, Refining, Feasible
- `BUILD . ENGINEERING`: Tests, Building, Review
- `RELEASE . OPS`: Staging, Production
- `ESCALATED`: Escalations
Each macroband features a 2px top accent line in its domain hue and tracked uppercase monospace typography (12px, letter-spacing 0.02em to 0.05em).

### Stage Headers and Mode Badges
Stage headers occupy the column header row:
- Stage Title: 10.5px to 11px uppercase monospace.
- Mode Badge: 8px uppercase outline badge positioned adjacent to the stage name:
  - `AUTO`: Teal outline (autonomous agent execution)
  - `GATE`: Coral outline (hard policy check decides)
  - `SIM`: Blue outline (simulated product owner step)
  - `MANUAL`: Grey outline (operator checkpoint)
- Telemetry Count Line: Quiet 8.5px monospace status line beneath the header:
  - Format: `X in . Y wait . Z blocked` (or stage spend in Cost lens, pass rate in Gates lens).

### Swimlanes and Coordinates
The vertical axis organizes work items into swimlanes:
- Group Modes:
  - `Type`: Feature, Bug, Maintenance
  - `Agent`: Assigned fleet agent (OR, CO, RG, PO, FE, TD, RV, TR, CT, RN, LD)
  - `Outcome`: In flight, Shipped (prod), Escalated
- Lane Header (Sticky Left):
  - Colored indicator dot (6px)
  - Identifier / name in monospace
  - Outlined micro-tags

### Ticket Pill Chips
Work items appear as compact interactive pill tokens:
- Height: 26px to 28px.
- Radius: Full pill (9999px).
- Internal Layout:
  1. State dot: 5px to 6px circular indicator (teal active, amber waiting, coral blocked/escalated, dashed pending).
  2. Ticket ID: `#24` in monospace bold, linking directly to ticket details (`#/ticket/24`).
  3. Agent micro-pill: 2-letter uppercase identifier (e.g. `CO`, `TD`, `RV`).
  4. Lens metric:
     - Delivery lens: stage duration (e.g. `14s`, `2m`).
     - Cost lens: USD spend with thin proportional bar against the 3.00 USD cap.
     - Gates lens: gate verdict dot.
- Overflow: Cells with more than 4 items collapse extra tickets into a dashed `+N more` pill chip.

### Non-Applicable and Empty Cells
- Empty Cells: 1px hairline dark panel with clear coordinates.
- Hatched Cells (`cell-hatched`): 135-degree repeating diagonal stripe pattern (`repeating-linear-gradient(135deg, ...)`) with a subtle `not in pipeline` micro-label.

### Segmented Controls
- Dual segmented selectors (`lens` and `group`) with 1px hairline frames.
- Lifted active segment with crisp monospace labels and instant state updates.

## 3. View Restyling and Layout Consistency

All 8 application views share the same mission-control visual language:
- Delivery Flow: Matrix grid with dual macrobands and interactive swimlanes.
- Ticket Detail: Horizontal stage progression strip of pill chips along the top, dense monospace gates table, and timeline log below.
- Environments: Small delivery matrix with Staging and Production swimlanes, deploy hops as pills, and rollbacks flagged in coral.
- Cost: Dense hairline tables comparing ledger estimates against Azure billed costs, sorting by spend, with quiet cap warning bars.
- Fleet Agents: Dense status table of all 11 agents with 2-letter badges, lifecycle state written out, and error telemetry.
- Escalations: Incident desk with coral hairlines, terminal reasons, and direct evidence links.
- Flow Metrics: Inline SVG charts with hairline axes backed by dense accessible data tables.
- Audit Trail: Dense chronological ledger stream filterable by event kind and ticket number.

## 4. Responsive Model

- 1440px Desktop: Full two-dimensional matrix display.
- 640px to 1024px: Horizontal scrolling matrix with sticky frozen swimlane headers on the left.
- 360px Mobile: Dense stacked view with compact swimlane cards, ensuring zero sideways page overflow.
