# Motion Media: Autonomous SDLC Demonstration

This directory contains the visual motion assets for the autonomous SDLC demonstration, designed for the header and documentation of `foundry-autonomous-sdlc`.

## Design Language and Philosophy

All visuals match the mission-control visual language defined in `apps/control-center/DESIGN.md` and `apps/control-center/css/styles.css`:
- **Canvas and Palette**: Independent dark navy graphite-blue palette (`#02080f` canvas, `#07151f` surface, `#202d37` hairlines).
- **Semantic Accents**:
  - Emerald mint (`#25df75`): autonomous execution, healthy gates, active run.
  - Golden amber (`#e8a838`): pending simulation, questions, refining.
  - Crimson / coral (`#ff4979`): gate checks, terminal escalations, smoke failures, rollbacks.
  - Sky azure (`#00c1eb`): contracts, staging environment, intake.
  - Electric violet (`#b99cff`): agent roles, coder execution, code review.
  - Teal (`#41d2b3`): completed releases, production promotions.
- **Pure Vector Standards**:
  - Hand-crafted SVG with inline SMIL (`<animateMotion>`) and CSS `@keyframes`.
  - Zero client scripts (`<script>` elements are strictly absent).
  - Zero web fonts (system monospace stack: `ui-monospace, "SF Mono", Monaco, Menlo, Consolas, monospace`).
  - Zero external network requests (zero CDN links or remote CSS).
  - Respects `prefers-reduced-motion` media queries with clean static fallback states.
  - Scales responsively from 1440px desktop down to 360px mobile viewports.
- **Honest Labelling**:
  - All visual timelines are explicitly labelled as compressed for demonstration (e.g. 14 seconds representing 12 to 45 minutes of real wall-clock runtime).
  - All scenarios are built directly from authentic recorded traces from the repository's `state` branch (`events.jsonl` and `state.json`).

## Assets

| File | Type | Description | Authentic Reference | Size |
|------|------|-------------|---------------------|------|
| `hero.svg` / `hero.gif` | Header | Master README motion header composing the topology network and 4 concurrent scenario flow lanes | Repository state | SVG: ~16 KB / GIF: &lt; 2 MB |
| `topology.svg` / `topology.gif` | System Architecture | Animated system topology connecting GitHub, Routine timer, Orchestrator, Prompt agents, Coder, CI gates, CD, and Control Center | `docs/architecture.md` | SVG: ~17 KB / GIF: &lt; 2 MB |
| `scenario-feature.svg` / `scenario-feature.gif` | Scenario 1 | Feature happy path: intake, bounce, simulated PO refinement, feasible, TDD red test, green build, review approval, staging smoke, soak, and production release | Issue #24, PR #29, Release v0.3.0 ($0.0816 USD) | SVG: ~11 KB / GIF: &lt; 2 MB |
| `scenario-bug.svg` / `scenario-bug.gif` | Scenario 2 | Bug with failing regression test first: triage severity and owner, failing test commit (red), fix commit (green), review, release | Issue #25, PR #26, Release v0.1.1 ($0.0368 USD) | SVG: ~11 KB / GIF: &lt; 2 MB |
| `scenario-escalation.svg` / `scenario-escalation.gif` | Scenario 3 | Vague requirement and escalation: initial score &lt; 80 bounced, simulated PO clarifies, feasibility agent evaluates and halts cleanly with coral escalation | Issue #17 ($0.0153 USD, not-agent-suitable) | SVG: ~10 KB / GIF: &lt; 2 MB |
| `scenario-rollback.svg` / `scenario-rollback.gif` | Scenario 4 | Continuous deployment smoke failure and automated rollback: staging deploy, Playwright smoke fail, rollback to previous prod build, ticket flagged | PR #46, Run 38180836579, sha 8137c60 | SVG: ~12 KB / GIF: &lt; 2 MB |

## Reproducible Build Tooling

All assets can be completely re-generated and verified using scripts under `scripts/media/`:

```bash
# 1. Inspect authentic recorded traces from origin/state branch
python3 scripts/media/extract_traces.py

# 2. Generate all vector SVGs
python3 scripts/media/generate_svgs.py

# 3. Verify SVGs in headless Chromium (motion checks, 0 errors, 0 network calls, 1440px and 360px widths)
node scripts/media/verify_media.js

# 4. Export GIF fallbacks via headless Chromium and ffmpeg (< 2 MB each)
node scripts/media/export_gifs.js
```

## Verification Results

Headless Chromium automated test runs confirm:
- Motion confirmed across timepoints (t0, t1, t2 frames differ on document timeline).
- Zero console errors across all SVGs.
- Zero external network requests across all SVGs.
- Clean visual scaling and legibility at 1440px and 360px viewports.
- All exported GIFs are under 2.0 MB.
