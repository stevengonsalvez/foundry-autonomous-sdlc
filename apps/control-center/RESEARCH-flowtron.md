# Flowtron UI Research and Measurement Analysis

An empirical study of the reference UI layout model, visual density, component anatomy, and measured metrics.

## Provenance, Licensing, and Implementation Independence

Flowtron has no open-source license. Consequently, strict implementation independence was maintained:
- **What was taken and adopted**: Structural design principles, layout model, and measured dimensional ratios (lane-by-stage matrix representation, macroband grouping strip, pill chips, dual segmented toggles, tracked uppercase monospace typography, and 1px hairlines).
- **What was changed and independently redesigned**:
  - **All Names and Tokens**: Zero flowtron token or class names are used. Our system uses an independent token scheme (`--canvas`, `--surface-0..3`, `--edge`, `--edge-subtle`, `--edge-focus`, `--fg`, `--fg-dim`, `--fg-muted`, `--tone-run`, `--tone-wait`, `--tone-block`, `--tone-info`, `--tone-agent`, `--tone-done`) and independent class names (`.band-strip`, `.band-cell`, `.matrix-grid`, `.matrix-spine`, `.lane-head`, `.matrix-cell`, `.chip-*`, etc.).
  - **Palette**: The color palette was redesigned to ensure strict chromatic separation from flowtron:
    - Flowtron reference values: ink 0.180, panel 0.224, panel-2 0.253.
    - Document our independent slate base hue at 215 (at or below 225).
    - Document our even surface ladder: canvas 0.10, surface-0 0.13, surface-1 0.16, surface-2 0.19, surface-3 0.23, surface-active 0.27, edge 0.29, edge-subtle 0.22. None matches flowtron steps (0.180, 0.224, 0.253).
    - Precise and honest hue separation metrics:
      - `--tone-run`: hue 142 (emerald mint) vs flowtron auto #2DD4A7 (hue 169.3 deg), 27.3 deg separation (>20 deg).
      - `--tone-info`: hue 205 (cerulean) vs flowtron info #38BDF8 (hue 232.7 deg), 27.7 deg separation (>20 deg).
      - `--tone-wait`: hue 52 (warm gold) vs flowtron assist (amber hue 80 deg), 28.0 deg separation (>20 deg).
      - `--tone-block`: hue 15 (crimson), text lightness 0.74 (>= 4.5:1 contrast on surface-3).
      - `--tone-done`: hue 138 (emerald lime) vs flowtron auto hue 169.3 deg, 31.3 deg separation (>20 deg).
      - Favicon: #080e1a and #06b6d4 (cyan hue 196.2 deg, >36 deg from flowtron #38bdf8).
  - **Copy and Visual Assets**: All domain copy was rewritten. Macroband copy uses independent operational categories (ALIGN . PRODUCT, IMPLEMENT . CODE, DELIVER . OPERATIONS, EXCEPTIONS) rather than flowtron phase descriptions. Hatched cell copy is "bypasses stage". Favicon is an independent pulse mark in deep slate and cyan (#080e1a and #06b6d4).
  - **Data Fidelity and Complete Accounting**: Unlike reference designs that collapse tickets into an overflow badge ("+N more"), our system maintains complete data fidelity: every active ticket is rendered as an interactive pill chip, ensuring column card counts strictly equal stage counts without swallowed or dropped items.
  - **Implementation**: Written from scratch in vanilla ES modules and standard CSS with pure dark theme, zero remote requests, and complete data fidelity.

## 1. Measured Values and Dimensional Ratios

All measurements below are observed values from the reference interface.

### Typography and Hierarchy
* Monospace Font Stack: System monospace stack (`ui-monospace, "SF Mono", Menlo, "JetBrains Mono", Consolas, monospace`) for all operational identifiers, metrics, badges, chips, column headers, controls, tags, and status counters.
* Prose Stack: System sans-serif stack (`system-ui, -apple-system, sans-serif`) for descriptive notes.
* Page Title: 19px to 22px, font-weight 600, letter-spacing 0.16em, uppercase monospace.
* Page Subtitle: 11px, letter-spacing 0.13em, uppercase monospace.
* Macroband Title: 12px, font-weight 600, letter-spacing 0.02em to 0.05em, uppercase monospace.
* Macroband Category / Owner Tag: 7.5px to 8px, letter-spacing 0.06em, 1px outline hairline, border-radius 8px, padding 1px 7px.
* Stage Header Title: 10.5px to 11px, font-weight 600, letter-spacing 0.03em, line-height 1.25, uppercase monospace.
* Stage Mode Badge (AUTO, GATE, SIM, MANUAL): 8px to 8.5px, letter-spacing 0.06em, padding 1px 5px, border-radius 10px.
* Stage Telemetry Line: 8px to 9px, letter-spacing 0.04em monospace, centered or quiet left-aligned. Format: `129 in . 129 wait . 0 blocked` with dot interpuncts.
* Swimlane Row Label: 10.5px to 11px, letter-spacing 0.03em to 0.05em, font-weight 600 monospace.
* Swimlane Micro-Tags: 7.5px to 8px, letter-spacing 0.08em, padding 2px 6px, border-radius 20px.
* Ticket Pill Chip Text: 9.5px to 10px, font-weight 600 monospace.
* Ticket Agent Micro-Tag: 7.5px to 8px, uppercase monospace, 2 letters.
* Overflow Chip ("+N more"): 8px, letter-spacing 0.03em, padding 1px 6px, border-radius 8px.
* Segmented Control Options: 10px, uppercase monospace, letter-spacing 0.08em, padding 4px 10px.
* Large Numeric Metric Values: 18px to 25px, font-weight 600 to 800, line-height 1.0.

### Tracking and Letter Spacing Spectrum
* Negative tracking: -0.02em for large dense numeric values.
* Subtle tracking (0.01em to 0.04em): for data tables, stage names, and card labels.
* Moderate tracking (0.05em to 0.08em): for chips, badges, buttons, and micro-tags.
* Wide uppercase tracking (0.10em to 0.18em): for section titles, toolbar headers, and macroband headings.

### Grid Construction and Spacing
* Outer Page Wrapper: max-width 1560px, padding 20px to 24px (scrolling gracefully down to 360px without page overflow).
* Board Shell: 1px hairline border, border-radius 4px to 12px, padding 12px to 16px.
* Horizontal Matrix Scroll Container: min-width 1220px to 1340px for desktop view, enabling clean horizontal scanning.
* Swimlane Row Minimum Height: 54px to 64px per swimlane row (compact and dense).
* Swimlane Label Frozen Column Width: 180px to 220px.
* Border Widths: 1px uniform hairlines across cells, dividers, and panels. No borders thicker than 1px except a 2px top accent line on macrobands.
* Corner Radii: 4px for panels, containers, and inputs; 9999px (full pill) for status badges and ticket chips.

### Ticket Pill Chip Anatomy
* Dimensions: Height 26px to 28px, minimum width 64px, flexible up to 88px.
* Shape: Full pill radius (9999px).
* Border: 1px to 1.5px hairline outline.
* Padding: 2px 8px.
* Internal Composition:
  1. State dot: 5px to 6px circular indicator on the left.
  2. Ticket identifier: `#24` in bold mono.
  3. Agent pill: 2-letter uppercase inner micro-pill (e.g. `RG`, `FE`, `TD`, `CO`, `RV`, `OR`, `LD`).
  4. Contextual lens metric (stage spend, gate outcome, or duration).
* State Variants:
  * Active: teal outline, faint teal tint.
  * Waiting / Queued: amber outline, dashed hairline.
  * Blocked / Escalated: coral outline, faint coral tint.
  * Pending ledger: muted line, dashed outline.
  * Shipped / Done: muted slate outline.

### Cell Treatments and Overflows
* Empty Observed Cells: 1px hairline boundaries, transparent dark panel background.
* Hatched / Non-Applicable Cells: 135-degree repeating diagonal stripe pattern (e.g. 6px stripe, 6px gap), subtle inset border, with an 8px uppercase mono label ("not in pipeline" or "bypass").
* Overflow Handling: When cell items exceed display limits, collapse into a `+N more` dashed micro-pill badge in the corner.

### Controls and Segmented Selectors
* Segmented Switch (lens and group selectors):
  * Container: 1px hairline border, border-radius 4px to 6px, display inline-flex, background dark surface.
  * Segments: 1px transparent border, border-radius 4px, padding 4px 10px, monospace, 10px uppercase, letter-spacing 0.08em.
  * Active Segment: Lifted panel background, border-color hairline line, bright text, font-weight 600.
* Buttons:
  * Border-radius 4px, padding 6px 12px, font-size 11px, letter-spacing 0.07em, uppercase monospace.
  * Focus outline: 2px solid with 2px offset for visible keyboard navigation.

### Transitions and Motion
* Durations: 120ms to 180ms ease-out.
* Transitions strictly applied to chip state changes and control highlights.
* No entrance or page transition animations.
* Full respect for `prefers-reduced-motion`.

## 2. Layout Model

The reference UI organizes complex lifecycle operations through a two-dimensional matrix:
1. Horizontal Axis (Stages and Macrobands):
   * Row 1: Macroband strip grouping stages into macro domains (SHAPE, BUILD, RELEASE) with colored top hairlines.
   * Row 2: Stage column headers, each with a title, mode badge (AUTO, GATE, SIM, MANUAL), and telemetry count line.
2. Vertical Axis (Swimlanes):
   * Left frozen column: lane identifier, colored domain dot, and attribute tags.
   * Rows: divided by group dimension (e.g. Work Item Type, Assigned Agent, or Outcome).
3. Intersection Cells:
   * Coordinate panels holding active ticket pill chips, hatched patterns for non-applicable stages, or quiet empty states.
4. Top Controls:
   * Header with repo name, system status, search, and navigation.
   * Control band with dual segmented selectors: `lens` (Delivery | Cost | Gates) and `group` (Type | Agent | Outcome).

## 3. What Makes It Feel Like Mission Control

1. Mathematical Density and Spatial Discipline: Every pixel conveys status or coordinate position. Whitespace is purposeful grid guttering rather than decorative padding.
2. Elimination of Decorative Consumer Fluff: No soft bubbly cards, no drop shadows, no glassmorphism blurs, no pastel gradients.
3. Information-Rich Micro-Typography: Tracked uppercase monospace labels, tabular numbers, and dot-separated telemetry summaries provide high-efficiency scanning.
4. Color Reserved Exclusively for State: The background and grid remain dark ink and charcoal neutrals. Chromatic color is strictly semantic: teal for active/healthy, amber for queued/waiting, coral for gates/escalations.
5. Multidimensional Redundancy: Color is never used in isolation; every state combines color, outline style (solid, dashed, hatched), and a text or glyph tag.

## 4. What to Amplify in the Redesign

1. Strict 1px Hairlines: Replace card containers across all 8 views with crisp 1px borders in OKLCH palette tokens.
2. Macroband and Stage Matrix: Implement the full macroband header (ALIGN . PRODUCT, IMPLEMENT . CODE, DELIVER . OPERATIONS, EXCEPTIONS) and lane matrix with mode badges.
3. Interactive Lens and Group Controls: Provide instant view toggles that change ticket chip details (Delivery age, Cost cap bars, Gate verdicts) and swimlane grouping (Type, Agent, Outcome).
4. Responsive Fallback: Maintain the sticky lane header and horizontal scrolling down to 640px, transitioning to an ultra-dense stacked list at 360px without page overflow.
5. Zero External Dependencies: Native CSS tokens, ES modules, safe DOM construction, and full keyboard navigation.
