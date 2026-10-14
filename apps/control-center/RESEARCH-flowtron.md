# Flowtron UI Research and Measurement Analysis

An empirical study of the reference UI layout model, visual density, component anatomy, and measured metrics.

## Provenance, Licensing, and Implementation Independence

Flowtron has no open-source license. Consequently, strict implementation independence was maintained:
- **What was taken and adopted**: Structural design principles, layout model, and measured dimensional ratios (lane-by-stage matrix representation, macroband grouping strip, pill chips, dual segmented toggles, tracked uppercase monospace typography, and 1px hairlines).
- **What was changed and independently redesigned**:
  - **Component Names and Tokens**: Common architectural and layout class names are retained (`badge`, `board-shell`, `card`, `chip`, `dot`, `gate`, `kpi`, `kpis`, `legend`, `note`, `num`, `seg`, `sub`, `toolbar`, `wrap`), while flowtron token names and component identifiers are replaced with an independent scheme (`--canvas`, `--surface-0..3`, `--edge`, `--edge-subtle`, `--edge-focus`, `--fg`, `--fg-dim`, `--fg-muted`, `--tone-run`, `--tone-wait`, `--tone-block`, `--tone-info`, `--tone-agent`, `--tone-done`, `.band-strip`, `.band-cell`, `.matrix-grid`, `.matrix-spine`, `.lane-head`, `.matrix-cell`, `.chip-*`, etc.).
  - **Palette**: The color palette was redesigned to maintain strict chromatic separation from flowtron under the same-role distance standard:
    - **Governing Rule**: Each token must differ from its same-role flowtron accent (`auto`, `dit`, `gate`, `assist`, `done`, `app-1`, `contract`, etc.) by dE_ok >= 0.06 and at least 12 degrees circular hue when chroma >= 0.03. Proximity to another-role accent within 20 degrees is permitted but explicitly inventoried in the cross-role table.
    - **Neutral Ladder**: Early drafts placed surfaces within dE 0.013 to 0.024 of reference neutrals when compared across all rungs, or collapsed into near-black when trying to avoid collisions at low lightness. The neutral ladder was recalibrated to a true midnight-navy palette across 4 surface rungs between L 0.215 and 0.328 (`--canvas` 0.160, `--surface-0` 0.215, `--surface-1` 0.256, `--surface-2` 0.292, `--surface-3` 0.328, hue 264°) and elevated hairline edges (`--edge-subtle` 0.420, `--edge` 0.510). Surfaces 0-3 step is ~0.038 / 0.041 and canvas sits 0.055 below surface-0. Three candidate palettes were evaluated (Candidate A at hue 264°, Candidate B at hue 276°, and Candidate C at hue 256°) sharing identical L and C ladders. Candidate A was selected because 264° establishes a focused midnight-navy command-deck presence without drifting into violet/purple (observed in Candidate B under wide-gamut displays) or teal/slate (observed in Candidate C near flowtron's dark tones). Every neutral sits dE_ok >= 0.04 from every reference neutral across all 8 root tokens (`ink`, `panel`, `panel-2`, `line-soft`, `line`, `muted-2`, `muted`, `text`). Adjacent surface rungs maintain contrast ratio >= 1.10:1 throughout the stack. `--surface-active` was deleted as obsolete since active segmented buttons use outline and focus borders rather than a dedicated surface tone.
    - **Reference Values and Exclusions**: Flowtron reference tokens from `src/style.css` include neutrals (`ink` #0E1217, `panel` #161C24, `panel-2` #1B232D, `line` #27313D, `line-soft` #1F2832, `text` #CBD6E3, `muted` #697686, `muted-2` #4D596A) and accents (`auto` #2DD4A7, `assist` #F2B23D, `gate` #F0644B, `dit` #6FA8FF, `contract` #22D3EE, `ephem` #C084FC, `dark` #C9A227, `done` #3A4654, `app-1` #A78BFA, `--app-2` #38BDF8, `app-3` #A3E635, `app-4` #FB7185). Note: #38BDF8 is `--app-2` in flowtron (not named info). Flowtron contains a presentation mode `body.shot-demo` opened with `?org=shot-demo`, setting 8 neutrals: `ink` #090C11, `panel` #151B23, `panel-2` #1C242E, `line-soft` #2B3644, `line` #3D4A5A, `text` #EDF3FA, `muted` #94A2B4, `muted-2` #6A7788. This is a dedicated presentation mode rather than the default shipping palette, so per Stevie's decision it is excluded from primary reference neutral comparisons, but an explicit distance analysis table against `shot-demo` neutrals is included below.
    - **Generated Palette Distance Matrix** (via `scripts/palette-distance.mjs`):

| Our Token | OKLCH | Role | Same-Role Accent | Same-Role dE | Same-Role dh | Min dE Accent | Min dE | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `--tone-run` | 0.78 0.16 142° | auto | auto | 0.0735 | 27.3° | auto | 0.0735 | PASS |
| `--tone-wait` | 0.78 0.15 52° | assist | assist | 0.0719 | 26.4° | assist | 0.0719 | PASS |
| `--tone-block` | 0.74 0.20 345° | gate | gate | 0.1656 | 47.1° | app-4 | 0.0977 | PASS |
| `--tone-info` | 0.76 0.14 190° | dit | dit | 0.1610 | 68.6° | auto | 0.0547 | PASS |
| `--tone-agent` | 0.76 0.15 325° | app-1 | app-1 | 0.0985 | 31.5° | ephem | 0.0722 | PASS |
| `--tone-done` | 0.76 0.16 120° | done | done | 0.4124 | 132.5° | dark | 0.0868 | PASS |
| `--edge-focus` | 0.72 0.16 190° | dit | dit | 0.1705 | 68.6° | auto | 0.0809 | PASS |
| `--st-fill-backlog` | 0.60 0.04 250° | neutral | - | - | - | dit | 0.1646 | PASS |
| `--st-fill-refining` | 0.68 0.14 65° | assist | assist | 0.1286 | 13.4° | dark | 0.0765 | PASS |
| `--st-fill-feasible` | 0.68 0.14 185° | contract | contract | 0.1330 | 26.5° | auto | 0.1055 | PASS |
| `--st-fill-tests` | 0.68 0.14 285° | gate | gate | 0.2568 | 107.1° | app-1 | 0.0412 | PASS |
| `--st-fill-building` | 0.68 0.13 145° | auto | auto | 0.1148 | 24.3° | auto | 0.1148 | PASS |
| `--st-fill-review` | 0.68 0.14 320° | app-1 | app-1 | 0.0766 | 26.5° | ephem | 0.0683 | PASS |
| `--st-fill-staging` | 0.68 0.14 220° | dit | dit | 0.1052 | 38.6° | app-2 | 0.0797 | PASS |
| `--st-fill-prod` | 0.70 0.15 110° | auto | auto | 0.1658 | 59.3° | dark | 0.0591 | PASS |
| `--st-fill-escalated` | 0.74 0.20 355° | gate | gate | 0.1382 | 37.1° | app-4 | 0.0697 | PASS |
| `favicon-dot` | 0.71 0.13 215° | dit | dit | 0.1005 | 43.4° | app-2 | 0.0573 | PASS |

#### Cross-Role Accents Within 20° Hue (Permitted by Decision)

| Token | Flowtron Accent | Role of Accent | Hue Diff | dE_ok |
| --- | --- | --- | --- | --- |
| `--tone-run` | `app-3` | app-3 | 13.2° | 0.0937 |
| `--tone-wait` | `gate` | gate | 19.9° | 0.1221 |
| `--tone-agent` | `ephem` | ephem | 19.5° | 0.0722 |
| `--tone-done` | `app-3` | app-3 | 8.8° | 0.1049 |
| `--st-fill-backlog` | `dit` | dit | 8.6° | 0.1646 |
| `--st-fill-backlog` | `app-2` | app-2 | 17.3° | 0.1840 |
| `--st-fill-feasible` | `auto` | auto | 15.7° | 0.1055 |
| `--st-fill-tests` | `app-1` | app-1 | 8.5° | 0.0412 |
| `--st-fill-building` | `app-3` | app-3 | 16.2° | 0.1918 |
| `--st-fill-review` | `ephem` | ephem | 14.5° | 0.0683 |
| `--st-fill-staging` | `contract` | contract | 8.5° | 0.1190 |
| `--st-fill-staging` | `app-2` | app-2 | 12.7° | 0.0797 |
| `--st-fill-prod` | `app-3` | app-3 | 18.8° | 0.1701 |
| `--st-fill-escalated` | `app-4` | app-4 | 18.4° | 0.0697 |
| `favicon-dot` | `contract` | contract | 3.7° | 0.0831 |
| `favicon-dot` | `app-2` | app-2 | 17.4° | 0.0573 |

#### Neutrals Distance Matrix vs All 8 Reference Neutrals (Target: dE_ok >= 0.04)

| Token | Our OKLCH | vs ink | vs panel | vs panel-2 | vs line-soft | vs line | vs muted-2 | vs muted | vs text | Min dE | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `--canvas` | 0.16 0.055 264° | 0.0476 | 0.0741 | 0.0988 | 0.1176 | 0.1521 | 0.3012 | 0.4016 | 0.7124 | 0.0476 | PASS |
| `--surface-0` | 0.21 0.058 264° | 0.0577 | 0.0412 | 0.0525 | 0.0682 | 0.0998 | 0.2467 | 0.3470 | 0.6577 | 0.0412 | PASS |
| `--surface-1` | 0.26 0.062 264° | 0.0908 | 0.0545 | 0.0404 | 0.0436 | 0.0648 | 0.2065 | 0.3066 | 0.6170 | 0.0404 | PASS |
| `--surface-2` | 0.29 0.063 264° | 0.1228 | 0.0815 | 0.0568 | 0.0455 | 0.0417 | 0.1712 | 0.2710 | 0.5812 | 0.0417 | PASS |
| `--surface-3` | 0.33 0.065 264° | 0.1570 | 0.1141 | 0.0866 | 0.0702 | 0.0443 | 0.1365 | 0.2356 | 0.5454 | 0.0443 | PASS |
| `--edge-subtle` | 0.42 0.040 264° | 0.2413 | 0.1971 | 0.1680 | 0.1484 | 0.1120 | 0.0413 | 0.1413 | 0.4520 | 0.0413 | PASS |
| `--edge` | 0.51 0.042 264° | 0.3311 | 0.2869 | 0.2578 | 0.2381 | 0.2016 | 0.0510 | 0.0527 | 0.3623 | 0.0510 | PASS |
| `favicon-bg` | 0.20 0.056 267° | 0.0468 | 0.0472 | 0.0663 | 0.0839 | 0.1171 | 0.2652 | 0.3656 | 0.6763 | 0.0468 | PASS |

#### Adjacent Surface Rungs Contrast (Target: ratio >= 1.10:1)

| Rung Pair | Upper Surface | Lower Surface | Contrast Ratio | Status |
| --- | --- | --- | --- | --- |
| `--surface-0` vs `--canvas` | 0.215 | 0.160 | 1.107:1 | PASS |
| `--surface-1` vs `--surface-0` | 0.256 | 0.215 | 1.113:1 | PASS |
| `--surface-2` vs `--surface-1` | 0.292 | 0.256 | 1.121:1 | PASS |
| `--surface-3` vs `--surface-2` | 0.328 | 0.292 | 1.138:1 | PASS |

#### Typography Neutrals vs Flowtron Reference Values

| Token | Our OKLCH | Flowtron Token | Flowtron Hex | dE_ok | Status |
| --- | --- | --- | --- | --- | --- |
| `--fg` | 0.98 0.005 264° | `text` | `#CBD6E3` | 0.1146 | PASS |
| `--fg-dim` | 0.81 0.018 264° | `muted` | `#697686` | 0.2495 | PASS |
| `--fg-muted` | 0.72 0.020 264° | `muted-2` | `#4D596A` | 0.2601 | PASS |

#### Reference Comparison vs `body.shot-demo` Presentation Mode Neutrals

| Token | Our OKLCH | vs ink (#090C11) | vs panel (#151B23) | vs panel-2 (#1C242E) | vs line-soft (#2B3644) | vs line (#3D4A5A) | vs muted-2 (#6A7788) | vs muted (#94A2B4) | vs text (#EDF3FA) | Min dE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `--canvas` | 0.160 0.055 264° | 0.0436 | 0.0704 | 0.1028 | 0.1711 | 0.2455 | 0.3262 | 0.4211 | 0.7314 | 0.0436 |
| `--surface-0` | 0.215 0.058 264° | 0.0673 | 0.0404 | 0.0634 | 0.1305 | 0.2045 | 0.2721 | 0.3664 | 0.6766 | 0.0404 |
| `--surface-1` | 0.256 0.062 264° | 0.1062 | 0.0560 | 0.0403 | 0.0967 | 0.1695 | 0.2323 | 0.3261 | 0.6360 | 0.0403 |
| `--surface-2` | 0.292 0.063 264° | 0.1428 | 0.0818 | 0.0506 | 0.0694 | 0.1396 | 0.1973 | 0.2905 | 0.6002 | 0.0506 |
| `--surface-3` | 0.328 0.065 264° | 0.1804 | 0.1139 | 0.0754 | 0.0367 | 0.1085 | 0.1627 | 0.2550 | 0.5644 | 0.0367 |
| `--edge-subtle` | 0.420 0.040 264° | 0.2680 | 0.2014 | 0.1639 | 0.0919 | 0.0189 | 0.0632 | 0.1603 | 0.4705 | 0.0189 |
| `--edge` | 0.510 0.042 264° | 0.3581 | 0.2915 | 0.2541 | 0.1822 | 0.1074 | 0.0560 | 0.0716 | 0.3807 | 0.0560 |
| `favicon-bg` | 0.200 0.056 267° | 0.0526 | 0.0448 | 0.0718 | 0.1398 | 0.2138 | 0.2906 | 0.3850 | 0.6953 | 0.0448 |
| `--fg-muted` | 0.720 0.020 264° | 0.5666 | 0.5002 | 0.4629 | 0.3912 | 0.3160 | 0.1558 | 0.0173 | 0.2418 | 0.0173 |

  - **Copy and Visual Assets**: All domain copy was rewritten. Macroband copy uses independent operational categories (ALIGN . PRODUCT, IMPLEMENT . CODE, DELIVER . OPERATIONS, EXCEPTIONS) rather than flowtron phase descriptions. Hatched cell copy is "bypasses stage". Favicon is an independent pulse mark in deep navy and cyan (#0a132e and #06b6d4).
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
