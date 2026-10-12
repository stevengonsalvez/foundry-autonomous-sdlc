# Control Center Design Blueprint

This document specifies the design system, visual hierarchy, and UI architecture for the Control Center redesign. It synthesises patterns and architectural techniques borrowed from Flowtron into a cohesive blueprint for monitoring the autonomous SDLC from backlog to production.

---

## 1. Executive Summary and Design Philosophy

The Control Center is an operational dashboard for autonomous software delivery. It provides complete observability into ticket lifecycles, pipeline execution, gate verifications, environment transitions, agent tasks, financial ledger data, and conversational trails.

### Core Mission
- **Operational Clarity:** Present complex autonomous delivery workflows at a glance without sacrificing technical depth.
- **Instrument-Grade Precision:** Deliver an interface calibrated like an industrial cockpit: dense, metric-first, and deterministic.
- **Truth in Presentation:** Display raw, verified data from the ledger. When data is unread or pending, the interface states this plainly rather than displaying placeholder values.
- **Zero-Dependency Security:** Preserve the static architecture: no build step, no npm runtime dependencies, no inline script or style injection, full Content Security Policy adherence, and strict text-only DOM manipulation.
- **Inclusive Accessibility:** Comply with WCAG 2.1 AA standards across both dark and light modes, honour reduced motion preferences, and support responsive viewports down to 360 px width without horizontal page scroll.

---

## 2. Patterns Borrowed from Flowtron and Rationale

Flowtron models delivery flows across multi-stage lifecycles using high-density visual hierarchies. We adapt several core patterns for the Control Center:

### 2.1 Navigation and Header Architecture
- **Pulsing Brand Beacon:** A compact 11 px status indicator in the top header (`.beacon`) that pulses softly using a scale and opacity animation. This provides immediate visceral confirmation that the system is live and monitoring the event stream. When the snapshot becomes stale (older than 10 minutes), the beacon transitions from active teal to warning amber or error red.
- **Two-Tier Header Structure:**
  - *Tier 1 (Top Bar):* Brand title in compact uppercase monospace, repository link, active snapshot freshness indicator, manual refresh button, and theme toggle.
  - *Tier 2 (Navigation Rail):* Clean tab bar linking hash routes (`#/`, `#/cost`, `#/environments`, `#/agents`, `#/escalations`, `#/flow`, `#/trail`), badged with live counter pills (for example, active escalation counts).
- **Collapsible Cockpit (Summary Strip):** A high-contrast KPI band placed prominently below the navigation. It displays headline metrics in a single row that can be collapsed to maximize vertical space when inspecting detailed board columns.

### 2.2 Board and Pipeline Visualisation
- **Macro-Phase Grouping Band:**
  In Flowtron, individual stages are anchored under macro-phases with distinct domain ownership and color accents. In our 9-stage SDLC board, we group columns into three intuitive macro-phases plus an exception lane:
  1. **Inception and Scoping (Business / Architecture):** Backlog, Refining, Feasible.
  2. **Construction and Verification (Engineering):** Tests, Building, Review.
  3. **Release and Operations (Platform / Reliability):** Staging, Production.
  4. **Exception Handling:** Escalated.
  A dedicated macro-phase band sits immediately above the column headers. It spans the respective columns via CSS Grid (`grid-column: span N`), featuring a 2 px top accent border, macro-phase title, category tag, and stage counter.
- **Column Header Stage Categories:**
  Each column header communicates the execution nature of that stage using standard category chips:
  - `Flow` (autonomous execution, unblocked progress: Building, Tests)
  - `Gate` (verification threshold or policy sign-off: Feasible, Review, Staging)
  - `Intake / Terminal` (Backlog, Production, Escalated)
  Headers feature a compact count badge, stage title in clean monospace, and a subtle status accent bar.
- **Card Tokens and Chips:**
  Individual ticket cards adapt Flowtron's token styling:
  - Crisp 1 px borders with rounded corners (8 px radius).
  - Left edge semantic indicator indicating ticket type or status.
  - Prominent monospace issue identifier (`#42` or `PR #12`).
  - Integrated spend meter showing cost against the 3.00 USD per-ticket cap.
  - Duration-in-stage badge updating relative time since stage entry.
- **Empty Column Density:**
  Columns with zero active tickets do not collapse or leave awkward voids. They maintain identical structural footprints with soft dashed borders, muted headers, and subtle zero-count badges, preserving overall grid alignment.

### 2.3 Ticket Detail: End-to-End Flow of Work
- **Stage Progression Stepper:** A horizontal visual stepper mapping every visit across the 9 stages, displaying active dwell time, loop-back rework visits, and entry timestamps.
- **Gate Verdict Matrix:** Flowtron verifies quality gates with explicit evidence. The Control Center renders a dedicated gate grid covering all policy gates: Tests, Coverage, End-to-End, Secret Scan, Tests-First order, Agent Scope, Review, Smoke, and Soak. Each gate item displays a distinct badge (Passed, Failed, In Progress, Skipped, Not Run), attempt counts, and first-attempt pass indicators.
- **Environment Progression Trail:** Explicit visualization of environment transitions (Staging -> Smoke -> Soak -> Production), linking commit SHAs, workflow run URLs, and deploy outcomes.
- **Financial Ledger Breakdown:** Precise breakdown of ledger compute estimates against actual billed spend, token usage, and meter allocations.
- **Conversational and Triage Trail:** A threaded timeline recording questions sent to the product owner, automated responses, code review verdicts, CI triage diagnoses, and escalation reasons.

### 2.4 Status Badges and Semantic Accents
- **Pill Shapes:** Compact badges with `border-radius: 9999px` (or `20px`) and tight internal padding (2 px 8 px).
- **Status Dots:** 6 px circular indicators providing immediate color cues without relying solely on hue.
- **Semantic Color Palette:**
  - *Success / Live / Auto:* Mint green / teal (`#2DD4A7` / oklch 72% 0.16 155)
  - *Active / In-Progress:* Electric cyan / sky (`#22D3EE` / oklch 74% 0.14 220)
  - *Warning / Review / Gate:* Warm amber (`#F2B23D` / oklch 76% 0.15 75)
  - *Danger / Failed / Escalated:* Coral red (`#F0644B` / oklch 65% 0.20 25)
  - *Neutral / Backlog / Muted:* Cool slate (`#697686` / oklch 55% 0.03 260)

### 2.5 Information Density and Typography
- **Monospace for Operational Data:** Ticket numbers, commit hashes, currency amounts, percentages, stage codes, and timestamps use a high-legibility monospace stack (`"IBM Plex Mono"`, `ui-monospace`, `Menlo`, `monospace`) with `font-variant-numeric: tabular-nums`.
- **Sans-Serif for Narrative Text:** Ticket titles, descriptions, review feedback, error traces, and documentation use a clean proportional sans-serif stack (`"Inter"`, `system-ui`, `-apple-system`, `sans-serif`).
- **Data Tables with Micro-Labels:** Compact tabular presentation with uppercase micro-headers (8.5 px to 10 px, `letter-spacing: 0.08em`), right-aligned numerals, and subtle border dividers.

### 2.6 Spacing, Borders, and Elevation
- **Unified 4 px Spacing Scale:** Systematic increments from 4 px (`--space-1`) up to 48 px (`--space-7`).
- **Crisp 1 px Borders:** Clean architectural lines (`border: 1px solid var(--line)`) that give distinct separation between cards, sections, and tables without heavy shadows.
- **Layered Surfaces:** Highlighting active elements using subtle background gradients and 1 px inset box-shadow rings (`box-shadow: inset 0 0 0 1px ...`) rather than blurry drop shadows.

### 2.7 Responsive and Mobile Ergonomics
- **No Sideways Root Scroll:** The root page maintains strict vertical scrolling across all screen sizes down to 360 px.
- **Contained Horizontal Scroll for Wide Grids:** The 9-column board and wide comparison tables sit inside dedicated scrollable containers (`.board-scroll`), with sticky column headers and visual scroll indicators.
- **Reflowing KPI Bands:** On viewports narrower than 820 px, the 5-to-6 column KPI strip automatically reflows to a 2-column grid.

---

## 3. Design Token Blueprint

The following tokens establish the visual foundation for both dark and light themes using standard CSS custom properties and modern `light-dark()` notation.

```css
:root {
  color-scheme: light dark;

  /* Typography Stacks */
  --font-sans: "Inter", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, "SF Mono", Menlo, Monaco, Consolas, monospace;

  /* Type Scale */
  --text-2xs: 0.6875rem; /* 11px */
  --text-xs: 0.75rem;     /* 12px */
  --text-sm: 0.8125rem;   /* 13px */
  --text-base: 0.875rem;  /* 14px */
  --text-md: 1rem;        /* 16px */
  --text-lg: 1.125rem;    /* 18px */
  --text-xl: 1.375rem;    /* 22px */
  --text-2xl: 1.625rem;   /* 26px */

  /* Spacing Scale (4px base) */
  --space-1: 0.25rem;  /* 4px */
  --space-2: 0.5rem;   /* 8px */
  --space-3: 0.75rem;  /* 12px */
  --space-4: 1rem;     /* 16px */
  --space-5: 1.25rem;  /* 20px */
  --space-6: 1.5rem;   /* 24px */
  --space-7: 2rem;     /* 32px */
  --space-8: 3rem;     /* 48px */

  /* Border Radii */
  --radius-xs: 0.25rem; /* 4px */
  --radius-sm: 0.375rem; /* 6px */
  --radius-md: 0.5rem;   /* 8px */
  --radius-lg: 0.75rem;  /* 12px */
  --radius-pill: 9999px;

  /* Base Surface Tokens */
  --canvas: light-dark(#F4F6F8, #0E1217);
  --panel: light-dark(#FFFFFF, #161C24);
  --panel-elevated: light-dark(#F8FAFC, #1B232D);
  --panel-sunken: light-dark(#EEF2F6, #11161D);

  /* Border and Line Tokens */
  --line: light-dark(#DDE3EA, #27313D);
  --line-soft: light-dark(#E8EDF2, #1F2832);
  --line-strong: light-dark(#BAC5D1, #3D4A5A);

  /* Typography / Text Tokens */
  --text-primary: light-dark(#0E1217, #EDF3FA);
  --text-secondary: light-dark(#3A4654, #CBD6E3);
  --text-muted: light-dark(#606E7F, #8292A2);
  --text-subtle: light-dark(#8594A6, #5B6675);

  /* Semantic State Tokens */
  /* Flow / Success / Live */
  --color-flow: #2DD4A7;
  --color-flow-bg: light-dark(rgba(45, 212, 167, 0.12), rgba(45, 212, 167, 0.14));
  --color-flow-line: light-dark(rgba(45, 212, 167, 0.40), rgba(45, 212, 167, 0.45));
  --color-flow-ink: light-dark(#0D6950, #4EEDB8);

  /* Assist / Warning / In-Progress */
  --color-warn: #F2B23D;
  --color-warn-bg: light-dark(rgba(242, 178, 61, 0.12), rgba(242, 178, 61, 0.14));
  --color-warn-line: light-dark(rgba(242, 178, 61, 0.40), rgba(242, 178, 61, 0.45));
  --color-warn-ink: light-dark(#7A5200, #FBD075);

  /* Gate / Escalated / Critical */
  --color-gate: #F0644B;
  --color-gate-bg: light-dark(rgba(240, 100, 75, 0.12), rgba(240, 100, 75, 0.16));
  --color-gate-line: light-dark(rgba(240, 100, 75, 0.40), rgba(240, 100, 75, 0.50));
  --color-gate-ink: light-dark(#8C2310, #FF9582);

  /* Sync / Environment / Transit */
  --color-transit: #22D3EE;
  --color-transit-bg: light-dark(rgba(34, 211, 238, 0.10), rgba(34, 211, 238, 0.14));
  --color-transit-line: light-dark(rgba(34, 211, 238, 0.35), rgba(34, 211, 238, 0.45));
  --color-transit-ink: light-dark(#086473, #67E8F9);

  /* Macro Phase Accent Colors */
  --macro-inception: #8AB4FF;
  --macro-construction: #7FD1A6;
  --macro-release: #2DD4A7;
  --macro-exception: #F0644B;

  /* Shadows and Inset Rings */
  --focus-ring: 0 0 0 2px var(--canvas), 0 0 0 4px var(--color-transit);
  --shadow-sm: light-dark(0 1px 2px rgba(0, 0, 0, 0.05), 0 2px 4px rgba(0, 0, 0, 0.30));
  --shadow-md: light-dark(0 4px 12px rgba(0, 0, 0, 0.08), 0 6px 18px rgba(0, 0, 0, 0.40));
}

:root[data-theme="light"] {
  color-scheme: light;
}

:root[data-theme="dark"] {
  color-scheme: dark;
}
```

---

## 4. Visual Hierarchy and Component Specifications

### 4.1 Header Bar and Brand Beacon
```
+-----------------------------------------------------------------------------------------+
| [● BEACON] CONTROL CENTER · REPO_NAME      [Updated 2m ago · raw]  [REFRESH] [THEME: AUTO] |
|-----------------------------------------------------------------------------------------|
| [BOARD]  [COST]  [ENVIRONMENTS]  [AGENTS]  [ESCALATIONS (1)]  [FLOW]  [TRAIL]           |
+-----------------------------------------------------------------------------------------+
```
- **Beacon Component (`.beacon`):**
  - Dimensions: 11 px x 11 px, border radius 50%.
  - Color: `--color-flow` (`#2DD4A7`) when active; pulses with a 2.4s ease-in-out cycle.
  - When state is stale (> 10 minutes), beacon changes to `--color-warn` with a static ring.
- **Repository Eyebrow:** Displayed in uppercase monospace with letter-spacing 0.12em.
- **Top Actions:** Compact buttons with 1 px borders, uppercase monospace labels, and visible keyboard focus rings.
- **Navigation Tabs:** Segmented rail with active route highlighting via an accent border and subtle background tint.

### 4.2 KPI Cockpit Band (Summary Strip)
```
+-----------------------------------------------------------------------------------------+
| | TICKETS      | IN FLIGHT    | PRODUCTION   | ESCALATED    | LEDGER EST.  | AZURE BILLED |
| | 18           | 7            | 10           | 1            | $14.82       | $13.50       |
+-----------------------------------------------------------------------------------------+
```
- **Layout:** Grid with 6 equal columns (`grid-template-columns: repeat(6, 1fr)`), wrapping to 2 columns below 820 px.
- **Card Anatomy:**
  - 3 px colored vertical indicator along the left edge (`.kpi-edge`).
  - Metric value (`.v`): 24 px font size, font-weight 600, tabular monospace.
  - Metric label (`.l`): 9.5 px uppercase monospace, letter-spacing 0.10em, muted text color.
- **Semantic Accents:**
  - In-flight: Blue / Cyan edge.
  - Production: Mint green edge.
  - Escalated: Coral red edge when > 0, otherwise subtle slate.
  - Financials: Normal slate, transitioning to warning amber when approaching the halt line.

### 4.3 Macro-Phases and Board Column Structure
```
+---------------------------------------------------------------------------------------------------------+
| [ INCEPTION & SCOPING ]         | [ CONSTRUCTION & VERIFICATION ] | [ RELEASE & OPS ]  | [ EXCEPTION ]  |
| 3 STAGES · BUSINESS             | 3 STAGES · ENGINEERING          | 2 STAGES · DEPLOY  | 1 STAGE        |
|---------------------------------+---------------------------------+--------------------+----------------|
| BACKLOG  | REFINING | FEASIBLE  | TESTS    | BUILDING | REVIEW    | STAGING  | PROD    | ESCALATED      |
| [GATE]   | [FLOW]   | [GATE]    | [FLOW]   | [FLOW]   | [GATE]    | [GATE]   | [FLOW]  | [HOLD]         |
| 2        | 1        | 0         | 1        | 3        | 2         | 1        | 7       | 1              |
|----------+----------+-----------+----------+----------+-----------+----------+---------+----------------|
| Card #12 | Card #15 | (empty)   | Card #19 | Card #20 | Card #21  | Card #24 | Card #5 | Card #18       |
| Card #14 |          |           |          | Card #22 | Card #23  |          | Card #8 |                |
+---------------------------------------------------------------------------------------------------------+
```

#### Macro-Phase Mapping
1. **Inception & Scoping (`--macro-inception: #8AB4FF`):**
   - Spans Backlog, Refining, Feasible.
   - Represents problem definition, task classification, and architectural feasibility checks.
2. **Construction & Verification (`--macro-construction: #7FD1A6`):**
   - Spans Tests, Building, Review.
   - Represents test creation, automated code implementation, and reviewer inspections.
3. **Release & Operations (`--macro-release: #2DD4A7`):**
   - Spans Staging, Production.
   - Represents deployment verification, smoke and soak tests, and final production delivery.
4. **Exception Handling (`--macro-exception: #F0644B`):**
   - Spans Escalated.
   - Represents tickets blocked by gate failures, runtime errors, or budget limits.

#### Stage Headers
- Stage Name: 11 px uppercase monospace, bold.
- Category Chip: Small pill (`Auto`, `Flow`, `Gate`) indicating execution mode.
- Count Badge: Monospace numeral with high contrast.

#### Ticket Card Anatomy
- **Header:** Issue identifier (`#42` in monospace bold), Type Badge (`Feature`, `Bug`, `Maintenance`), Environment Badge (`Staging`, `Prod`).
- **Body:** Ticket title clamped to 2-3 lines in readable sans-serif.
- **Cost Bar:** Compact horizontal progress bar:
  - Total width: 100%.
  - Fill percentage: `(cost_usd / 3.00) * 100`.
  - Normal color: Mint green; turns Amber at > 75%, Coral Red at 100%.
- **Footer:** Duration in current stage (`4h in building`), flags, and escalation indicators.

### 4.4 Ticket Detail Inspector (`#/ticket/<n>`)
The ticket detail view provides end-to-end trace visibility:
1. **Header Breadcrumb & Summary:**
   - Monospace issue key and full title.
   - Badge row with ticket type, stage badge, cost total, and GitHub link.
2. **Stage Timeline Stepper:**
   - Multi-step timeline visualizing visits across all 9 stages.
   - Identifies loop-back cycles (for example, second attempt in Building after a Review failure).
   - Shows active duration in each stage.
3. **Policy Gate Verification Grid:**
   - 3x3 or 4x2 matrix of policy gates: Tests, Coverage, End-to-End, Secret Scan, Tests-First order, Agent Scope, Review, Smoke, Soak.
   - Displays verdict icon (`✓`, `✕`, `•`, `-`), attempt count, and first-attempt pass status.
4. **Environment Deployment Trail:**
   - Sequential chain of hops: Staging -> Smoke -> Soak -> Production.
   - Links to run artifacts, commit SHAs, and deployment logs.
5. **Agent Activity and Conversational Trail:**
   - Structured accordion cards for Questions Back (queries from coding agents answered by simulated product owner), Review Verdicts, and CI Diagnoses.

### 4.5 Data Tables and Metric Lists
- Applied in Cost view, Flow metrics, Agents list, and Trail groups.
- Column headers: 9 px uppercase monospace with letter spacing.
- Numerical cells: Tabular digits aligned right.
- Zebra striping: Subtle alternating background (`rgba(255, 255, 255, 0.015)`).
- Hover feedback: Crisp highlight on hovered rows without content shifts.

---

## 5. Responsive and Mobile Blueprint

The layout ensures seamless usability from widescreen monitors down to 360 px viewports:

| Viewport Width | Layout Adaptations |
|---|---|
| **> 1200 px (Desktop)** | Full 9-column board visible in widescreen container. KPI band spans 6 columns in a single row. Ticket detail displays side-by-side gate and cost panels. |
| **820 px - 1199 px (Tablet)** | Board sits in a contained `.board-scroll` wrapper with sticky column headers. KPI band shifts to 3 columns x 2 rows. Toolbar controls stack into logical rows. |
| **360 px - 819 px (Mobile)** | Root page strictly preserves vertical scroll. The board container permits horizontal scrolling without breaking the header or navigation. KPI band reflows to 2 columns. Cards adopt a slightly more compact layout. Touch targets meet the minimum 44 px size. |

---

## 6. Security and Implementation Rules

All implementations must uphold the project's strict security guarantees:

1. **Text-Only DOM Construction:**
   - All dynamic strings (issue titles, review remarks, error traces, commit messages) must be inserted strictly as text nodes via `document.createTextNode` or `element.textContent`.
   - Never use `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, or `eval`.
2. **Strict Content Security Policy Conformance:**
   - No inline styles (`style="..."` attributes are prohibited and blocked by tests).
   - Dynamic sizes, percentages, and progress bars must be set via CSS custom properties on element styles using the CSSOM API (`el.style.setProperty('--bar-width', pct)`).
3. **Strict URL Sanitation:**
   - External links must only link to repository resources matching known URL patterns.
   - All links must use `target="_blank"` and `rel="noopener noreferrer"`.
4. **Style and Typography Guidelines:**
   - Do NOT use em-dashes anywhere in source text, documentation, or code comments. Use regular hyphens, colons, or parentheses instead.
   - Maintain full test suite coverage (`npm test`) across static checks, unit tests, and Playwright browser accessibility assertions.
