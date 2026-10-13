#!/usr/bin/env python3
"""Generate the animated SVG assets for the autonomous SDLC demonstration.
Pure vector SVGs with inline SMIL and CSS keyframe animations.
No scripts, no external fonts, no network requests.
Tokens matching apps/control-center/DESIGN.md dark navy control-room theme.
"""

import os
import sys

# Color tokens from apps/control-center/DESIGN.md & styles.css
CANVAS = "#02080f"
SURFACE_0 = "#040f17"
SURFACE_1 = "#07151f"
SURFACE_2 = "#0f1f2a"
SURFACE_3 = "#162936"
EDGE = "#202d37"
EDGE_SUBTLE = "#101a21"
EDGE_FOCUS = "#00bae9"

FG = "#dfe9f1"
FG_DIM = "#b0bdc6"
FG_MUTED = "#87949f"

TONE_RUN = "#25df75"     # Emerald mint: active, auto, success
TONE_WAIT = "#e8a838"    # Golden amber: pending, sim, refining
TONE_BLOCK = "#ff4979"   # Crimson / coral: gate, blocked, rollback, escalation
TONE_INFO = "#00c1eb"    # Sky azure: contracts, staging, links
TONE_AGENT = "#b99cff"   # Electric violet: prompt agents, coder
TONE_DONE = "#41d2b3"    # Teal: shipped, prod

FONT_MONO = 'ui-monospace, "SF Mono", Monaco, Menlo, Consolas, "Liberation Mono", monospace'


def common_style():
    return f"""
    <style>
      text {{
        font-family: {FONT_MONO};
        user-select: none;
      }}
      .mono-xs {{ font-size: 8.5px; font-weight: 500; }}
      .mono-sm {{ font-size: 10px; font-weight: 500; }}
      .mono-md {{ font-size: 11.5px; font-weight: 600; }}
      .mono-lg {{ font-size: 13px; font-weight: 700; }}
      .mono-title {{ font-size: 13.5px; font-weight: 700; letter-spacing: 0.05em; }}

      @media (prefers-reduced-motion: reduce) {{
        * {{
          animation: none !important;
        }}
        animate, animateMotion, animateTransform {{
          display: none !important;
        }}
      }}
    </style>
    """


def generate_topology_svg():
    """Generates docs/media/topology.svg"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 560" width="100%" height="100%">
  {common_style()}
  <defs>
    <filter id="glow-run" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="3" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
    <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">
      <path d="M 20 0 L 0 0 0 20" fill="none" stroke="{EDGE_SUBTLE}" stroke-width="0.5" />
    </pattern>
    <marker id="arrow" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="4" markerHeight="4" orient="auto-start-reverse">
      <path d="M 0 0 L 6 3 L 0 6 z" fill="{FG_MUTED}" />
    </marker>
  </defs>

  <!-- Background Canvas -->
  <rect width="960" height="560" fill="{CANVAS}" />
  <rect width="960" height="560" fill="url(#grid)" opacity="0.6" />

  <!-- Outer Frame -->
  <rect x="12" y="12" width="936" height="536" rx="6" fill="none" stroke="{EDGE}" stroke-width="1" />

  <!-- Header Bar -->
  <rect x="12" y="12" width="936" height="42" fill="{SURFACE_0}" rx="6" />
  <line x1="12" y1="54" x2="948" y2="54" stroke="{EDGE}" stroke-width="1" />
  
  <circle cx="32" cy="33" r="5" fill="{TONE_RUN}" filter="url(#glow-run)">
    <animate attributeName="opacity" values="1;0.4;1" dur="2s" repeatCount="indefinite" />
  </circle>
  <text x="46" y="37" fill="{FG}" class="mono-title">SYSTEM TOPOLOGY // AUTONOMOUS SDLC</text>
  
  <!-- Header Telemetry Chips -->
  <rect x="520" y="24" width="96" height="18" rx="3" fill="{SURFACE_2}" stroke="{TONE_WAIT}" stroke-width="0.8" />
  <text x="528" y="36" fill="{TONE_WAIT}" class="mono-xs">POLL: */5 MIN</text>

  <rect x="626" y="24" width="106" height="18" rx="3" fill="{SURFACE_2}" stroke="{TONE_INFO}" stroke-width="0.8" />
  <text x="634" y="36" fill="{TONE_INFO}" class="mono-xs">BRANCH: state</text>

  <rect x="742" y="24" width="96" height="18" rx="3" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.8" />
  <text x="752" y="36" fill="{TONE_RUN}" class="mono-xs">FLEET: 10 AGTS</text>

  <rect x="848" y="24" width="90" height="18" rx="3" fill="{SURFACE_2}" stroke="{TONE_DONE}" stroke-width="0.8" />
  <text x="858" y="36" fill="{TONE_DONE}" class="mono-xs">LIVE EDGES</text>

  <!-- ==================== SYSTEM NODES ==================== -->

  <!-- NODE 1: Routine Timer (Cron) -->
  <g id="node-routine">
    <rect x="360" y="68" width="240" height="54" rx="4" fill="{SURFACE_1}" stroke="{EDGE}" stroke-width="1" />
    <rect x="360" y="68" width="240" height="2" fill="{TONE_WAIT}" />
    <text x="374" y="88" fill="{FG}" class="mono-md">ROUTINE TIMER</text>
    <rect x="528" y="75" width="62" height="16" rx="2" fill="{SURFACE_2}" stroke="{TONE_WAIT}" stroke-width="0.8" />
    <text x="535" y="87" fill="{TONE_WAIT}" class="mono-xs">CRON */5m</text>
    <text x="374" y="108" fill="{FG_MUTED}" class="mono-xs">Azure schedule wakes orchestrator</text>
  </g>

  <!-- NODE 2: GitHub Repository -->
  <g id="node-github">
    <rect x="36" y="156" width="220" height="110" rx="4" fill="{SURFACE_1}" stroke="{EDGE}" stroke-width="1" />
    <rect x="36" y="156" width="220" height="2" fill="{TONE_INFO}" />
    <text x="50" y="178" fill="{FG}" class="mono-md">GITHUB REPOSITORY</text>
    <rect x="180" y="165" width="66" height="16" rx="2" fill="{SURFACE_2}" stroke="{TONE_INFO}" stroke-width="0.8" />
    <text x="188" y="177" fill="{TONE_INFO}" class="mono-xs">HUB (PAT)</text>
    <text x="50" y="198" fill="{FG_DIM}" class="mono-sm">Issues (owner-only intake)</text>
    <text x="50" y="216" fill="{FG_DIM}" class="mono-sm">Pull requests (coder branches)</text>
    <text x="50" y="234" fill="{FG_MUTED}" class="mono-xs">Labels, status checks, releases</text>
    <text x="50" y="250" fill="{FG_MUTED}" class="mono-xs">Ruleset: main-gates (no bypass)</text>
  </g>

  <!-- NODE 3: sdlc-orchestrator (The Brain) -->
  <g id="node-orchestrator">
    <rect x="340" y="156" width="280" height="110" rx="4" fill="{SURFACE_1}" stroke="{TONE_RUN}" stroke-width="1.2" />
    <rect x="340" y="156" width="280" height="2" fill="{TONE_RUN}" />
    <circle cx="356" cy="176" r="4" fill="{TONE_RUN}" filter="url(#glow-run)" />
    <text x="368" y="180" fill="{FG}" class="mono-md">SDLC-ORCHESTRATOR</text>
    <rect x="548" y="165" width="62" height="16" rx="2" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.8" />
    <text x="556" y="177" fill="{TONE_RUN}" class="mono-xs">HOSTED</text>
    <text x="354" y="200" fill="{FG_DIM}" class="mono-sm">Deterministic state machine</text>
    <text x="354" y="218" fill="{FG_DIM}" class="mono-sm">Owns all merges . Enforces $3/$25 cap</text>
    <text x="354" y="236" fill="{FG_MUTED}" class="mono-xs">PAT from Key Vault . Invocations protocol</text>
    <text x="354" y="250" fill="{FG_MUTED}" class="mono-xs">Lock holder: tick state lease</text>
  </g>

  <!-- NODE 4: Prompt Agents Cluster -->
  <g id="node-prompt-agents">
    <rect x="700" y="130" width="224" height="144" rx="4" fill="{SURFACE_1}" stroke="{EDGE}" stroke-width="1" />
    <rect x="700" y="130" width="224" height="2" fill="{TONE_AGENT}" />
    <text x="714" y="152" fill="{FG}" class="mono-md">PROMPT AGENTS</text>
    <rect x="826" y="139" width="88" height="16" rx="2" fill="{SURFACE_2}" stroke="{TONE_AGENT}" stroke-width="0.8" />
    <text x="832" y="151" fill="{TONE_AGENT}" class="mono-xs">SPECIALIZED</text>
    
    <text x="714" y="172" fill="{FG_DIM}" class="mono-xs">req-gate (score 0..100)</text>
    <text x="714" y="188" fill="{FG_DIM}" class="mono-xs">sdlc-product-owner (SIM)</text>
    <text x="714" y="204" fill="{FG_DIM}" class="mono-xs">sdlc-feasibility (GitHub MCP)</text>
    <text x="714" y="220" fill="{FG_DIM}" class="mono-xs">sdlc-test-designer (TDD)</text>
    <text x="714" y="236" fill="{FG_DIM}" class="mono-xs">sdlc-reviewer (independent)</text>
    <text x="714" y="252" fill="{FG_MUTED}" class="mono-xs">triage . ci-triage . release-notes</text>
    <text x="714" y="266" fill="{FG_MUTED}" class="mono-xs">Responses API . JSON schema recheck</text>
  </g>

  <!-- NODE 5: CI Gates -->
  <g id="node-ci-gates">
    <rect x="36" y="306" width="220" height="106" rx="4" fill="{SURFACE_1}" stroke="{EDGE}" stroke-width="1" />
    <rect x="36" y="306" width="220" height="2" fill="{TONE_BLOCK}" />
    <text x="50" y="326" fill="{FG}" class="mono-md">CI GATES (main-gates)</text>
    <rect x="186" y="315" width="60" height="16" rx="2" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="0.8" />
    <text x="194" y="327" fill="{TONE_BLOCK}" class="mono-xs">HARD GATE</text>
    <text x="50" y="346" fill="{FG_DIM}" class="mono-xs">1. test (vitest, contracts)</text>
    <text x="50" y="362" fill="{FG_DIM}" class="mono-xs">2. coverage (line &gt;= 80%)</text>
    <text x="50" y="378" fill="{FG_DIM}" class="mono-xs">3. e2e (Playwright tests)</text>
    <text x="50" y="394" fill="{FG_MUTED}" class="mono-xs">4. gitleaks  5. tdd-order  6. agent-scope</text>
    <text x="50" y="406" fill="{FG_MUTED}" class="mono-xs">Plain CI: never drives an agent</text>
  </g>

  <!-- NODE 6: sdlc-coder -->
  <g id="node-coder">
    <rect x="340" y="306" width="280" height="106" rx="4" fill="{SURFACE_1}" stroke="{EDGE}" stroke-width="1" />
    <rect x="340" y="306" width="280" height="2" fill="{TONE_AGENT}" />
    <text x="354" y="326" fill="{FG}" class="mono-md">SDLC-CODER (SANDBOX)</text>
    <rect x="548" y="315" width="62" height="16" rx="2" fill="{SURFACE_2}" stroke="{TONE_AGENT}" stroke-width="0.8" />
    <text x="556" y="327" fill="{TONE_AGENT}" class="mono-xs">HOSTED</text>
    <text x="354" y="346" fill="{FG_DIM}" class="mono-sm">git, node, agy CLI, tests</text>
    <text x="354" y="364" fill="{FG_DIM}" class="mono-sm">Commits tests first (red assertion)</text>
    <text x="354" y="382" fill="{FG_DIM}" class="mono-sm">Iterates code until green; opens PR</text>
    <text x="354" y="400" fill="{FG_MUTED}" class="mono-xs">Touches app/ only . 2h deadline cap</text>
  </g>

  <!-- NODE 7: sdlc-ledger -->
  <g id="node-ledger">
    <rect x="700" y="306" width="224" height="66" rx="4" fill="{SURFACE_1}" stroke="{EDGE}" stroke-width="1" />
    <rect x="700" y="306" width="224" height="2" fill="{TONE_INFO}" />
    <text x="714" y="326" fill="{FG}" class="mono-md">SDLC-LEDGER</text>
    <rect x="834" y="315" width="80" height="16" rx="2" fill="{SURFACE_2}" stroke="{TONE_INFO}" stroke-width="0.8" />
    <text x="842" y="327" fill="{TONE_INFO}" class="mono-xs">AUTO-SCALE</text>
    <text x="714" y="344" fill="{FG_DIM}" class="mono-sm">Folds events, reconciles state</text>
    <text x="714" y="360" fill="{FG_MUTED}" class="mono-xs">Writes one commit per tick</text>
  </g>

  <!-- NODE 8: Continuous Deployment (CD) -->
  <g id="node-cd">
    <rect x="36" y="442" width="584" height="74" rx="4" fill="{SURFACE_1}" stroke="{EDGE}" stroke-width="1" />
    <rect x="36" y="442" width="584" height="2" fill="{TONE_DONE}" />
    <text x="50" y="462" fill="{FG}" class="mono-md">CONTINUOUS DEPLOYMENT (cd.yml on merge)</text>
    <rect x="520" y="449" width="90" height="16" rx="2" fill="{SURFACE_2}" stroke="{TONE_DONE}" stroke-width="0.8" />
    <text x="532" y="461" fill="{TONE_DONE}" class="mono-xs">ZERO HUMAN</text>
    
    <rect x="50" y="476" width="60" height="26" rx="3" fill="{SURFACE_2}" stroke="{EDGE}" />
    <text x="66" y="493" fill="{FG_DIM}" class="mono-xs">PLAN</text>

    <text x="117" y="492" fill="{FG_MUTED}">→</text>

    <rect x="130" y="476" width="60" height="26" rx="3" fill="{SURFACE_2}" stroke="{EDGE}" />
    <text x="144" y="493" fill="{FG_DIM}" class="mono-xs">BUILD</text>

    <text x="197" y="492" fill="{FG_MUTED}">→</text>

    <rect x="210" y="476" width="76" height="26" rx="3" fill="{SURFACE_2}" stroke="{TONE_INFO}" stroke-width="0.8" />
    <text x="220" y="493" fill="{TONE_INFO}" class="mono-xs">/staging/</text>

    <text x="293" y="492" fill="{FG_MUTED}">→</text>

    <rect x="306" y="476" width="86" height="26" rx="3" fill="{SURFACE_2}" stroke="{TONE_WAIT}" stroke-width="0.8" />
    <text x="314" y="493" fill="{TONE_WAIT}" class="mono-xs">SMOKE (E2E)</text>

    <text x="399" y="492" fill="{FG_MUTED}">→</text>

    <rect x="412" y="476" width="80" height="26" rx="3" fill="{SURFACE_2}" stroke="{TONE_WAIT}" stroke-width="0.8" />
    <text x="420" y="493" fill="{TONE_WAIT}" class="mono-xs">SOAK (10m)</text>

    <text x="499" y="492" fill="{FG_MUTED}">→</text>

    <rect x="512" y="476" width="98" height="26" rx="3" fill="{SURFACE_2}" stroke="{TONE_DONE}" stroke-width="0.8" />
    <text x="522" y="493" fill="{TONE_DONE}" class="mono-xs">PROD (SITE)</text>
  </g>

  <!-- NODE 9: Branch State -->
  <g id="node-branch-state">
    <rect x="700" y="394" width="224" height="54" rx="4" fill="{SURFACE_1}" stroke="{EDGE}" stroke-width="1" />
    <rect x="700" y="394" width="224" height="2" fill="{TONE_RUN}" />
    <text x="714" y="414" fill="{FG}" class="mono-md">BRANCH `state`</text>
    <rect x="834" y="401" width="80" height="16" rx="2" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.8" />
    <text x="844" y="413" fill="{TONE_RUN}" class="mono-xs">COMMITTED</text>
    <text x="714" y="434" fill="{FG_MUTED}" class="mono-xs">state.json . events.jsonl (229 events)</text>
  </g>

  <!-- NODE 10: Control Center -->
  <g id="node-control-center">
    <rect x="700" y="468" width="224" height="48" rx="4" fill="{SURFACE_1}" stroke="{EDGE}" stroke-width="1" />
    <rect x="700" y="468" width="224" height="2" fill="{TONE_INFO}" />
    <text x="714" y="488" fill="{FG}" class="mono-md">/control-center/</text>
    <rect x="834" y="474" width="80" height="16" rx="2" fill="{SURFACE_2}" stroke="{TONE_INFO}" stroke-width="0.8" />
    <text x="846" y="486" fill="{TONE_INFO}" class="mono-xs">8 VIEWS</text>
    <text x="714" y="504" fill="{FG_MUTED}" class="mono-xs">Live matrix, swimlanes, cost telemetry</text>
  </g>

  <!-- ==================== EDGES & MOVING DOTS ==================== -->

  <!-- Path 1: Routine Timer -> Orchestrator (cron trigger) -->
  <path id="path-routine-orch" d="M 480 122 L 480 156" stroke="{EDGE}" stroke-width="1.5" stroke-dasharray="3,3" />
  <circle cx="480" cy="122" r="3.5" fill="{TONE_WAIT}">
    <animateMotion dur="2.5s" repeatCount="indefinite" path="M 0 0 L 0 34" />
  </circle>

  <!-- Path 2: GitHub <-> Orchestrator (Intake & Sync) -->
  <path id="path-gh-orch" d="M 256 195 L 340 195" stroke="{EDGE}" stroke-width="1.5" stroke-dasharray="3,3" />
  <circle cx="256" cy="195" r="3.5" fill="{TONE_INFO}">
    <animateMotion dur="3s" repeatCount="indefinite" path="M 0 0 L 84 0" />
  </circle>

  <!-- Path 3: Orchestrator <-> Prompt Agents (Responses API) -->
  <path id="path-orch-agents" d="M 620 195 L 700 195" stroke="{EDGE}" stroke-width="1.5" stroke-dasharray="3,3" />
  <circle cx="620" cy="195" r="3.5" fill="{TONE_AGENT}">
    <animateMotion dur="2s" repeatCount="indefinite" path="M 0 0 L 80 0" />
  </circle>
  <circle cx="700" cy="205" r="3.5" fill="{TONE_RUN}">
    <animateMotion dur="2s" begin="1s" repeatCount="indefinite" path="M 0 0 L -80 0" />
  </circle>

  <!-- Path 4: Orchestrator -> Coder (Task Invocations) -->
  <path id="path-orch-coder" d="M 480 266 L 480 306" stroke="{EDGE}" stroke-width="1.5" stroke-dasharray="3,3" />
  <circle cx="480" cy="266" r="3.5" fill="{TONE_AGENT}">
    <animateMotion dur="2.5s" repeatCount="indefinite" path="M 0 0 L 0 40" />
  </circle>

  <!-- Path 5: Coder -> GitHub (Push branch & Open PR) -->
  <path id="path-coder-gh" d="M 340 330 L 290 330 L 290 230 L 256 230" stroke="{EDGE}" stroke-width="1.5" stroke-dasharray="3,3" fill="none" />
  <circle cx="340" cy="330" r="3.5" fill="{TONE_INFO}">
    <animateMotion dur="4s" repeatCount="indefinite" path="M 0 0 L -50 0 L -50 -100 L -84 -100" />
  </circle>

  <!-- Path 6: GitHub -> CI Gates (Trigger Required Checks) -->
  <path id="path-gh-ci" d="M 146 266 L 146 306" stroke="{EDGE}" stroke-width="1.5" stroke-dasharray="3,3" />
  <circle cx="146" cy="266" r="3.5" fill="{TONE_BLOCK}">
    <animateMotion dur="2.2s" repeatCount="indefinite" path="M 0 0 L 0 40" />
  </circle>

  <!-- Path 7: CI Gates -> Orchestrator (Check Results Green) -->
  <path id="path-ci-orch" d="M 256 360 L 300 360 L 300 250 L 340 250" stroke="{EDGE}" stroke-width="1.5" stroke-dasharray="3,3" fill="none" />
  <circle cx="256" cy="360" r="3.5" fill="{TONE_RUN}">
    <animateMotion dur="3.5s" repeatCount="indefinite" path="M 0 0 L 44 0 L 44 -110 L 84 -110" />
  </circle>

  <!-- Path 8: Orchestrator -> GitHub Merge & CD Trigger -->
  <path id="path-orch-merge" d="M 340 215 L 256 215" stroke="{EDGE}" stroke-width="1.5" stroke-dasharray="3,3" />
  <circle cx="340" cy="215" r="3.5" fill="{TONE_RUN}">
    <animateMotion dur="2.8s" repeatCount="indefinite" path="M 0 0 L -84 0" />
  </circle>

  <path id="path-gh-cd" d="M 110 266 L 110 442" stroke="{EDGE}" stroke-width="1.5" stroke-dasharray="3,3" />
  <circle cx="110" cy="266" r="3.5" fill="{TONE_DONE}">
    <animateMotion dur="3s" repeatCount="indefinite" path="M 0 0 L 0 176" />
  </circle>

  <!-- Path 9: CD Staging -> Prod flow -->
  <path id="path-cd-flow" d="M 110 489 L 512 489" stroke="{EDGE}" stroke-width="1" stroke-dasharray="2,2" />
  <circle cx="110" cy="489" r="3.5" fill="{TONE_DONE}">
    <animateMotion dur="4s" repeatCount="indefinite" path="M 0 0 L 402 0" />
  </circle>

  <!-- Path 10: Orchestrator -> Ledger (Telemetry Events) -->
  <path id="path-orch-ledger" d="M 620 240 L 660 240 L 660 330 L 700 330" stroke="{EDGE}" stroke-width="1.5" stroke-dasharray="3,3" fill="none" />
  <circle cx="620" cy="240" r="3.5" fill="{TONE_INFO}">
    <animateMotion dur="3.2s" repeatCount="indefinite" path="M 0 0 L 40 0 L 40 90 L 80 90" />
  </circle>

  <!-- Path 11: Ledger -> Branch State (Single Commit per Tick) -->
  <path id="path-ledger-state" d="M 812 372 L 812 394" stroke="{EDGE}" stroke-width="1.5" stroke-dasharray="3,3" />
  <circle cx="812" cy="372" r="3.5" fill="{TONE_RUN}">
    <animateMotion dur="2s" repeatCount="indefinite" path="M 0 0 L 0 22" />
  </circle>

  <!-- Path 12: Branch State -> Control Center (Telemetry Poll) -->
  <path id="path-state-cc" d="M 812 448 L 812 468" stroke="{EDGE}" stroke-width="1.5" stroke-dasharray="3,3" />
  <circle cx="812" cy="448" r="3.5" fill="{TONE_INFO}">
    <animateMotion dur="2.2s" repeatCount="indefinite" path="M 0 0 L 0 20" />
  </circle>

  <!-- ==================== FOOTER STATUS ==================== -->
  <rect x="12" y="524" width="936" height="24" fill="{SURFACE_0}" rx="3" />
  <text x="24" y="540" fill="{FG_MUTED}" class="mono-xs">TIMINGS COMPRESSED (12m-45m WALL CLOCK) . REAL RECORDED TRACES (BRANCH ORIGIN/STATE) . ZERO SCRIPTS . PURE VECTOR SVG</text>
</svg>
"""


def generate_scenario_feature_svg():
    """Generates docs/media/scenario-feature.svg (Issue #24)"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 440" width="100%" height="100%">
  {common_style()}
  <defs>
    <filter id="glow-feat" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="3" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
  </defs>

  <!-- Background -->
  <rect width="960" height="440" fill="{CANVAS}" />
  <rect x="12" y="12" width="936" height="416" rx="6" fill="none" stroke="{EDGE}" stroke-width="1" />

  <!-- Top Bar -->
  <rect x="12" y="12" width="936" height="42" fill="{SURFACE_0}" rx="6" />
  <line x1="12" y1="54" x2="948" y2="54" stroke="{EDGE}" stroke-width="1" />
  
  <circle cx="32" cy="33" r="5" fill="{TONE_RUN}" filter="url(#glow-feat)" />
  <text x="46" y="37" fill="{FG}" class="mono-title">SCENARIO 1 // FEATURE HAPPY PATH (ISSUE #24)</text>
  
  <!-- Top Badges -->
  <rect x="530" y="24" width="76" height="18" rx="9" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="1" />
  <text x="543" y="37" fill="{TONE_RUN}" class="mono-xs">AUTO: RUN</text>

  <rect x="614" y="24" width="104" height="18" rx="9" fill="{SURFACE_2}" stroke="{TONE_INFO}" stroke-width="1" />
  <text x="624" y="37" fill="{TONE_INFO}" class="mono-xs">SPEND: $0.0816</text>

  <rect x="726" y="24" width="210" height="18" rx="9" fill="{SURFACE_2}" stroke="{TONE_DONE}" stroke-width="1" />
  <text x="736" y="37" fill="{TONE_DONE}" class="mono-xs">PROD: RELEASED v0.3.0</text>

  <!-- Macrobands Strip -->
  <rect x="36" y="66" width="300" height="22" fill="{SURFACE_1}" />
  <line x1="36" y1="66" x2="336" y2="66" stroke="{TONE_INFO}" stroke-width="2" />
  <text x="44" y="81" fill="{TONE_INFO}" class="mono-xs" letter-spacing="0.08em">SHAPE . BUSINESS</text>

  <rect x="344" y="66" width="310" height="22" fill="{SURFACE_1}" />
  <line x1="344" y1="66" x2="654" y2="66" stroke="{TONE_AGENT}" stroke-width="2" />
  <text x="352" y="81" fill="{TONE_AGENT}" class="mono-xs" letter-spacing="0.08em">BUILD . ENGINEERING</text>

  <rect x="662" y="66" width="262" height="22" fill="{SURFACE_1}" />
  <line x1="662" y1="66" x2="924" y2="66" stroke="{TONE_DONE}" stroke-width="2" />
  <text x="670" y="81" fill="{TONE_DONE}" class="mono-xs" letter-spacing="0.08em">RELEASE . OPERATIONS</text>

  <!-- Stage Headers Row -->
  <!-- Col 1: Backlog -->
  <rect x="36" y="94" width="94" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="44" y="110" fill="{FG}" class="mono-xs">BACKLOG</text>
  <rect x="44" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.6" />
  <text x="48" y="123" fill="{TONE_RUN}" style="font-size: 7.5px;">AUTO</text>

  <!-- Col 2: Refining -->
  <rect x="136" y="94" width="98" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="144" y="110" fill="{FG}" class="mono-xs">REFINING</text>
  <rect x="144" y="114" width="30" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_WAIT}" stroke-width="0.6" />
  <text x="148" y="123" fill="{TONE_WAIT}" style="font-size: 7.5px;">SIM</text>

  <!-- Col 3: Feasible -->
  <rect x="240" y="94" width="96" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="248" y="110" fill="{FG}" class="mono-xs">FEASIBLE</text>
  <rect x="248" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.6" />
  <text x="252" y="123" fill="{TONE_RUN}" style="font-size: 7.5px;">AUTO</text>

  <!-- Col 4: Tests -->
  <rect x="344" y="94" width="98" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="352" y="110" fill="{FG}" class="mono-xs">TESTS (TDD)</text>
  <rect x="352" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.6" />
  <text x="356" y="123" fill="{TONE_RUN}" style="font-size: 7.5px;">AUTO</text>

  <!-- Col 5: Building -->
  <rect x="448" y="94" width="98" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="456" y="110" fill="{FG}" class="mono-xs">BUILDING</text>
  <rect x="456" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.6" />
  <text x="460" y="123" fill="{TONE_RUN}" style="font-size: 7.5px;">AUTO</text>

  <!-- Col 6: Review -->
  <rect x="552" y="94" width="102" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="560" y="110" fill="{FG}" class="mono-xs">REVIEW (CI)</text>
  <rect x="560" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="0.6" />
  <text x="564" y="123" fill="{TONE_BLOCK}" style="font-size: 7.5px;">GATE</text>

  <!-- Col 7: Staging -->
  <rect x="662" y="94" width="124" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="670" y="110" fill="{FG}" class="mono-xs">STAGING (SMOKE)</text>
  <rect x="670" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="0.6" />
  <text x="674" y="123" fill="{TONE_BLOCK}" style="font-size: 7.5px;">GATE</text>

  <!-- Col 8: Prod -->
  <rect x="794" y="94" width="130" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="802" y="110" fill="{FG}" class="mono-xs">PROD (RELEASE)</text>
  <rect x="802" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.6" />
  <text x="806" y="123" fill="{TONE_RUN}" style="font-size: 7.5px;">AUTO</text>

  <!-- Matrix Grid Background / Lane -->
  <rect x="36" y="136" width="888" height="140" fill="{SURFACE_1}" stroke="{EDGE}" stroke-width="0.8" />

  <!-- Column Dividers for Matrix Look -->
  <line x1="133" y1="136" x2="133" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="237" y1="136" x2="237" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="341" y1="136" x2="341" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="445" y1="136" x2="445" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="549" y1="136" x2="549" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="659" y1="136" x2="659" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="791" y1="136" x2="791" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />

  <!-- Flow Lane Guide Line -->
  <path id="lane-feature" d="M 80 200 L 180 200 L 285 200 L 390 200 L 495 200 L 600 200 L 720 200 L 850 200" stroke="{EDGE}" stroke-width="2" stroke-dasharray="4,4" fill="none" />

  <!-- Verification Gates Along Lane -->
  <g id="gate-1">
    <circle cx="180" cy="200" r="14" fill="{SURFACE_2}" stroke="{TONE_WAIT}" stroke-width="1.5" />
    <text x="174" y="204" fill="{TONE_WAIT}" class="mono-xs">90%</text>
    <text x="156" y="226" fill="{FG_MUTED}" class="mono-xs">PO Answer</text>
  </g>

  <g id="gate-2">
    <circle cx="285" cy="200" r="14" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="1.5" />
    <text x="277" y="204" fill="{TONE_RUN}" class="mono-xs">OK</text>
    <text x="264" y="226" fill="{FG_MUTED}" class="mono-xs">Feasible</text>
  </g>

  <g id="gate-3">
    <circle cx="390" cy="200" r="14" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="1.5" />
    <text x="380" y="204" fill="{TONE_RUN}" class="mono-xs">TDD</text>
    <text x="366" y="226" fill="{FG_MUTED}" class="mono-xs">c0f5713 (red)</text>
  </g>

  <g id="gate-4">
    <circle cx="495" cy="200" r="14" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="1.5" />
    <text x="485" y="204" fill="{TONE_RUN}" class="mono-xs">BLD</text>
    <text x="472" y="226" fill="{FG_MUTED}" class="mono-xs">fcc6f1e (grn)</text>
  </g>

  <g id="gate-5">
    <circle cx="600" cy="200" r="14" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="1.5" />
    <text x="592" y="204" fill="{TONE_RUN}" class="mono-xs">6/6</text>
    <text x="580" y="226" fill="{FG_MUTED}" class="mono-xs">PR #29 Appr</text>
  </g>

  <g id="gate-6">
    <circle cx="720" cy="200" r="14" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="1.5" />
    <text x="710" y="204" fill="{TONE_RUN}" class="mono-xs">10m</text>
    <text x="696" y="226" fill="{FG_MUTED}" class="mono-xs">Smoke + Soak</text>
  </g>

  <g id="gate-7">
    <rect x="826" y="186" width="56" height="28" rx="14" fill="{SURFACE_2}" stroke="{TONE_DONE}" stroke-width="1.5" />
    <text x="834" y="204" fill="{TONE_DONE}" class="mono-xs">v0.3.0</text>
    <text x="838" y="226" fill="{FG_MUTED}" class="mono-xs">Shipped</text>
  </g>

  <!-- MOVING TICKET PILL CHIP (#24) -->
  <g id="active-pill" transform="translate(80, 200)">
    <rect x="-44" y="-12" width="88" height="24" rx="12" fill="{SURFACE_3}" stroke="{TONE_RUN}" stroke-width="1.5" filter="url(#glow-feat)" />
    <circle cx="-32" cy="0" r="4" fill="{TONE_RUN}" />
    <text x="-24" y="4" fill="{FG}" class="mono-sm">#24</text>
    <rect x="0" y="-7" width="18" height="14" rx="2" fill="{SURFACE_1}" />
    <text x="3" y="4" fill="{TONE_AGENT}" class="mono-xs">CO</text>
    <text x="22" y="4" fill="{TONE_RUN}" class="mono-xs">AUTO</text>

    <!-- Path Animation across 14 seconds -->
    <animateMotion dur="14s" repeatCount="indefinite" path="M 0 0 L 100 0 L 205 0 L 310 0 L 415 0 L 520 0 L 640 0 L 770 0" keyTimes="0;0.12;0.25;0.42;0.58;0.72;0.88;1" />
  </g>

  <!-- Live Telemetry Card at Bottom -->
  <rect x="36" y="290" width="888" height="110" rx="4" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <rect x="36" y="290" width="4" height="110" fill="{TONE_INFO}" />

  <text x="50" y="310" fill="{FG}" class="mono-md">CHRONOLOGICAL AUDIT TRAIL // ISSUE #24</text>
  <text x="340" y="310" fill="{FG_MUTED}" class="mono-xs">TITLE: "Make the parcel tracker better" (scenario b)</text>

  <text x="50" y="332" fill="{FG_DIM}" class="mono-xs">00:00  [req-gate] Bounced: score 72 &lt; 80 threshold. Asked 2 clarification questions.</text>
  <text x="50" y="348" fill="{TONE_WAIT}" class="mono-xs">00:03  [product-owner] Simulated PO replied with concrete criteria. Re-score: 90/100 (ready).</text>
  <text x="50" y="364" fill="{FG_DIM}" class="mono-xs">00:05  [feasibility] Suitable: True, risk low. Scoped to parcel tracker view.</text>
  <text x="50" y="380" fill="{TONE_AGENT}" class="mono-xs">00:07  [sdlc-coder] Commit c0f5713 (tests first, 1 failed, 0 loaded) -> Commit fcc6f1e (5 files fixed, green).</text>
  <text x="50" y="394" fill="{TONE_DONE}" class="mono-xs">00:11  [orchestrator] PR #29 merged; CD staged; Playwright smoke passed; 10m soak verified; v0.3.0 live.</text>

  <!-- Footer -->
  <rect x="12" y="408" width="936" height="20" fill="{SURFACE_0}" rx="3" />
  <text x="24" y="422" fill="{FG_MUTED}" class="mono-xs">TIMINGS COMPRESSED (ACTUAL: 18m WALL CLOCK) . RECORDED IN STATE:EVENTS.JSONL . BILLED COST: $0.0816 USD</text>
</svg>
"""


def generate_scenario_bug_svg():
    """Generates docs/media/scenario-bug.svg (Issue #25)"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 440" width="100%" height="100%">
  {common_style()}
  <defs>
    <filter id="glow-bug" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="3" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
  </defs>

  <rect width="960" height="440" fill="{CANVAS}" />
  <rect x="12" y="12" width="936" height="416" rx="6" fill="none" stroke="{EDGE}" stroke-width="1" />

  <!-- Top Bar -->
  <rect x="12" y="12" width="936" height="42" fill="{SURFACE_0}" rx="6" />
  <line x1="12" y1="54" x2="948" y2="54" stroke="{EDGE}" stroke-width="1" />
  
  <circle cx="32" cy="33" r="5" fill="{TONE_BLOCK}" filter="url(#glow-bug)" />
  <text x="46" y="37" fill="{FG}" class="mono-title">SCENARIO 2 // BUG TDD REGRESSION FIRST (ISSUE #25)</text>
  
  <rect x="520" y="24" width="96" height="18" rx="9" fill="{SURFACE_2}" stroke="{TONE_WAIT}" stroke-width="1" />
  <text x="530" y="37" fill="{TONE_WAIT}" class="mono-xs">TRIAGE: S3/API</text>

  <rect x="624" y="24" width="104" height="18" rx="9" fill="{SURFACE_2}" stroke="{TONE_INFO}" stroke-width="1" />
  <text x="634" y="37" fill="{TONE_INFO}" class="mono-xs">SPEND: $0.0368</text>

  <rect x="736" y="24" width="200" height="18" rx="9" fill="{SURFACE_2}" stroke="{TONE_DONE}" stroke-width="1" />
  <text x="746" y="37" fill="{TONE_DONE}" class="mono-xs">PROD: RELEASED v0.1.1</text>

  <!-- Macrobands -->
  <rect x="36" y="66" width="300" height="22" fill="{SURFACE_1}" />
  <line x1="36" y1="66" x2="336" y2="66" stroke="{TONE_WAIT}" stroke-width="2" />
  <text x="44" y="81" fill="{TONE_WAIT}" class="mono-xs" letter-spacing="0.08em">TRIAGE &amp; SHAPE</text>

  <rect x="344" y="66" width="310" height="22" fill="{SURFACE_1}" />
  <line x1="344" y1="66" x2="654" y2="66" stroke="{TONE_AGENT}" stroke-width="2" />
  <text x="352" y="81" fill="{TONE_AGENT}" class="mono-xs" letter-spacing="0.08em">TDD . FAILING REGRESSION TEST FIRST</text>

  <rect x="662" y="66" width="262" height="22" fill="{SURFACE_1}" />
  <line x1="662" y1="66" x2="924" y2="66" stroke="{TONE_DONE}" stroke-width="2" />
  <text x="670" y="81" fill="{TONE_DONE}" class="mono-xs" letter-spacing="0.08em">RELEASE . OPERATIONS</text>

  <!-- Stage Columns -->
  <rect x="36" y="94" width="94" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="44" y="110" fill="{FG}" class="mono-xs">1. TRIAGE</text>
  <rect x="44" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_WAIT}" stroke-width="0.6" />
  <text x="48" y="123" fill="{TONE_WAIT}" style="font-size: 7.5px;">AUTO</text>

  <rect x="136" y="94" width="98" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="144" y="110" fill="{FG}" class="mono-xs">2. REQ-GATE</text>
  <rect x="144" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.6" />
  <text x="148" y="123" fill="{TONE_RUN}" style="font-size: 7.5px;">AUTO</text>

  <rect x="240" y="94" width="96" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="248" y="110" fill="{FG}" class="mono-xs">3. FEASIBLE</text>
  <rect x="248" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.6" />
  <text x="252" y="123" fill="{TONE_RUN}" style="font-size: 7.5px;">AUTO</text>

  <rect x="344" y="94" width="102" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="350" y="110" fill="{TONE_BLOCK}" class="mono-xs">4. TEST (RED)</text>
  <rect x="350" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="0.6" />
  <text x="354" y="123" fill="{TONE_BLOCK}" style="font-size: 7.5px;">FAIL</text>

  <rect x="452" y="94" width="96" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="458" y="110" fill="{TONE_RUN}" class="mono-xs">5. FIX (GRN)</text>
  <rect x="458" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.6" />
  <text x="462" y="123" fill="{TONE_RUN}" style="font-size: 7.5px;">PASS</text>

  <rect x="554" y="94" width="100" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="560" y="110" fill="{FG}" class="mono-xs">6. REVIEW</text>
  <rect x="560" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="0.6" />
  <text x="564" y="123" fill="{TONE_BLOCK}" style="font-size: 7.5px;">GATE</text>

  <rect x="662" y="94" width="124" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="670" y="110" fill="{FG}" class="mono-xs">7. STAGING</text>
  <rect x="670" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="0.6" />
  <text x="674" y="123" fill="{TONE_BLOCK}" style="font-size: 7.5px;">GATE</text>

  <rect x="794" y="94" width="130" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="802" y="110" fill="{FG}" class="mono-xs">8. PROD</text>
  <rect x="802" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.6" />
  <text x="806" y="123" fill="{TONE_RUN}" style="font-size: 7.5px;">AUTO</text>

  <!-- Matrix Grid -->
  <rect x="36" y="136" width="888" height="140" fill="{SURFACE_1}" stroke="{EDGE}" stroke-width="0.8" />
  
  <line x1="133" y1="136" x2="133" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="237" y1="136" x2="237" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="341" y1="136" x2="341" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="445" y1="136" x2="445" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="549" y1="136" x2="549" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="659" y1="136" x2="659" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="791" y1="136" x2="791" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />

  <path id="lane-bug" d="M 80 200 L 180 200 L 285 200 L 390 200 L 495 200 L 600 200 L 720 200 L 850 200" stroke="{EDGE}" stroke-width="2" stroke-dasharray="4,4" fill="none" />

  <!-- Verification Gates -->
  <g id="bgate-1">
    <circle cx="80" cy="200" r="14" fill="{SURFACE_2}" stroke="{TONE_WAIT}" stroke-width="1.5" />
    <text x="73" y="204" fill="{TONE_WAIT}" class="mono-xs">S3</text>
    <text x="60" y="226" fill="{FG_MUTED}" class="mono-xs">owner:api</text>
  </g>

  <g id="bgate-2">
    <circle cx="180" cy="200" r="14" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="1.5" />
    <text x="174" y="204" fill="{TONE_RUN}" class="mono-xs">83</text>
    <text x="160" y="226" fill="{FG_MUTED}" class="mono-xs">score &gt;= 80</text>
  </g>

  <g id="bgate-3">
    <circle cx="285" cy="200" r="14" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="1.5" />
    <text x="278" y="204" fill="{TONE_RUN}" class="mono-xs">OK</text>
    <text x="264" y="226" fill="{FG_MUTED}" class="mono-xs">Feasible</text>
  </g>

  <g id="bgate-4">
    <circle cx="390" cy="200" r="15" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="2" />
    <text x="378" y="204" fill="{TONE_BLOCK}" class="mono-xs">RED</text>
    <text x="360" y="226" fill="{TONE_BLOCK}" class="mono-xs">6816a92 (test)</text>
  </g>

  <g id="bgate-5">
    <circle cx="495" cy="200" r="15" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="2" />
    <text x="484" y="204" fill="{TONE_RUN}" class="mono-xs">GRN</text>
    <text x="470" y="226" fill="{TONE_RUN}" class="mono-xs">a132025 (fix)</text>
  </g>

  <g id="bgate-6">
    <circle cx="600" cy="200" r="14" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="1.5" />
    <text x="592" y="204" fill="{TONE_RUN}" class="mono-xs">6/6</text>
    <text x="580" y="226" fill="{FG_MUTED}" class="mono-xs">PR #26 Appr</text>
  </g>

  <g id="bgate-7">
    <circle cx="720" cy="200" r="14" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="1.5" />
    <text x="710" y="204" fill="{TONE_RUN}" class="mono-xs">OK</text>
    <text x="700" y="226" fill="{FG_MUTED}" class="mono-xs">Smoke Pass</text>
  </g>

  <g id="bgate-8">
    <rect x="826" y="186" width="56" height="28" rx="14" fill="{SURFACE_2}" stroke="{TONE_DONE}" stroke-width="1.5" />
    <text x="834" y="204" fill="{TONE_DONE}" class="mono-xs">v0.1.1</text>
    <text x="838" y="226" fill="{FG_MUTED}" class="mono-xs">Shipped</text>
  </g>

  <!-- MOVING TICKET PILL CHIP (#25) -->
  <g id="active-bug-pill" transform="translate(80, 200)">
    <rect x="-44" y="-12" width="88" height="24" rx="12" fill="{SURFACE_3}" stroke="{TONE_WAIT}" stroke-width="1.5" filter="url(#glow-bug)" />
    <circle cx="-32" cy="0" r="4" fill="{TONE_BLOCK}" />
    <text x="-24" y="4" fill="{FG}" class="mono-sm">#25</text>
    <rect x="0" y="-7" width="18" height="14" rx="2" fill="{SURFACE_1}" />
    <text x="3" y="4" fill="{TONE_AGENT}" class="mono-xs">CO</text>
    <text x="22" y="4" fill="{TONE_BLOCK}" class="mono-xs">BUG</text>

    <animateMotion dur="14s" repeatCount="indefinite" path="M 0 0 L 100 0 L 205 0 L 310 0 L 415 0 L 520 0 L 640 0 L 770 0" keyTimes="0;0.12;0.25;0.42;0.58;0.72;0.88;1" />
  </g>

  <!-- Telemetry Card -->
  <rect x="36" y="290" width="888" height="110" rx="4" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <rect x="36" y="290" width="4" height="110" fill="{TONE_WAIT}" />

  <text x="50" y="310" fill="{FG}" class="mono-md">CHRONOLOGICAL AUDIT TRAIL // ISSUE #25</text>
  <text x="340" y="310" fill="{FG_MUTED}" class="mono-xs">TITLE: "Lowercase tracking numbers are rejected as invalid" (scenario d)</text>

  <text x="50" y="332" fill="{TONE_WAIT}" class="mono-xs">00:00  [triage] Bug triaged automatically: assigned severity=s3, owner=api. Label bug:triaged set.</text>
  <text x="50" y="348" fill="{FG_DIM}" class="mono-xs">00:02  [req-gate &amp; feasibility] Scored 83/100 (ready). Feasibility: suitable (confined to input normalization).</text>
  <text x="50" y="364" fill="{TONE_BLOCK}" class="mono-xs">00:05  [tdd-order verification] Commit 1 (6816a92) is tests-only. Assertion failed for the right reason (RED).</text>
  <text x="50" y="380" fill="{TONE_RUN}" class="mono-xs">00:08  [coder fix] Commit 2 (a132025) normalizes tracking number to uppercase before validation (GREEN).</text>
  <text x="50" y="394" fill="{TONE_DONE}" class="mono-xs">00:11  [orchestrator &amp; CD] PR #26 approved by reviewer; merged af1a742; smoke verified; release v0.1.1 tagged.</text>

  <!-- Footer -->
  <rect x="12" y="408" width="936" height="20" fill="{SURFACE_0}" rx="3" />
  <text x="24" y="422" fill="{FG_MUTED}" class="mono-xs">TIMINGS COMPRESSED (ACTUAL: 14m WALL CLOCK) . RECORDED IN STATE:EVENTS.JSONL . BILLED COST: $0.0368 USD</text>
</svg>
"""


def generate_scenario_escalation_svg():
    """Generates docs/media/scenario-escalation.svg (Issue #17)"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 440" width="100%" height="100%">
  {common_style()}
  <defs>
    <filter id="glow-coral" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="3" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
  </defs>

  <rect width="960" height="440" fill="{CANVAS}" />
  <rect x="12" y="12" width="936" height="416" rx="6" fill="none" stroke="{EDGE}" stroke-width="1" />

  <!-- Top Bar -->
  <rect x="12" y="12" width="936" height="42" fill="{SURFACE_0}" rx="6" />
  <line x1="12" y1="54" x2="948" y2="54" stroke="{EDGE}" stroke-width="1" />
  
  <circle cx="32" cy="33" r="5" fill="{TONE_BLOCK}" filter="url(#glow-coral)">
    <animate attributeName="opacity" values="1;0.3;1" dur="1.5s" repeatCount="indefinite" />
  </circle>
  <text x="46" y="37" fill="{FG}" class="mono-title">SCENARIO 3 // VAGUE &amp; NOT-AGENT-SUITABLE (ISSUE #17)</text>
  
  <rect x="540" y="24" width="76" height="18" rx="9" fill="{SURFACE_2}" stroke="{TONE_WAIT}" stroke-width="1" />
  <text x="553" y="37" fill="{TONE_WAIT}" class="mono-xs">SIM: PO</text>

  <rect x="624" y="24" width="104" height="18" rx="9" fill="{SURFACE_2}" stroke="{TONE_INFO}" stroke-width="1" />
  <text x="634" y="37" fill="{TONE_INFO}" class="mono-xs">SPEND: $0.0153</text>

  <rect x="736" y="24" width="200" height="18" rx="9" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="1" />
  <text x="746" y="37" fill="{TONE_BLOCK}" class="mono-xs">HALTED: HUMAN DESK</text>

  <!-- Macrobands -->
  <rect x="36" y="66" width="410" height="22" fill="{SURFACE_1}" />
  <line x1="36" y1="66" x2="446" y2="66" stroke="{TONE_INFO}" stroke-width="2" />
  <text x="44" y="81" fill="{TONE_INFO}" class="mono-xs" letter-spacing="0.08em">SHAPE . SIMULATED REFINEMENT</text>

  <rect x="454" y="66" width="470" height="22" fill="{SURFACE_1}" />
  <line x1="454" y1="66" x2="924" y2="66" stroke="{TONE_BLOCK}" stroke-width="2" />
  <text x="462" y="81" fill="{TONE_BLOCK}" class="mono-xs" letter-spacing="0.08em">ESCALATED . INCIDENT DESK (CORAL TONE)</text>

  <!-- Stage Headers -->
  <rect x="36" y="94" width="120" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="44" y="110" fill="{FG}" class="mono-xs">1. BACKLOG</text>
  <rect x="44" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.6" />
  <text x="48" y="123" fill="{TONE_RUN}" style="font-size: 7.5px;">AUTO</text>

  <rect x="164" y="94" width="134" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="172" y="110" fill="{FG}" class="mono-xs">2. REFINING</text>
  <rect x="172" y="114" width="30" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_WAIT}" stroke-width="0.6" />
  <text x="176" y="123" fill="{TONE_WAIT}" style="font-size: 7.5px;">SIM</text>

  <rect x="306" y="94" width="140" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="314" y="110" fill="{FG}" class="mono-xs">3. FEASIBILITY</text>
  <rect x="314" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.6" />
  <text x="318" y="123" fill="{TONE_RUN}" style="font-size: 7.5px;">AUTO</text>

  <rect x="454" y="94" width="470" height="34" fill="{SURFACE_0}" stroke="{TONE_BLOCK}" stroke-width="1" />
  <text x="466" y="110" fill="{TONE_BLOCK}" class="mono-xs">4. ESCALATED: NOT-AGENT-SUITABLE (TERMINAL)</text>
  <rect x="466" y="114" width="56" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="0.6" />
  <text x="472" y="123" fill="{TONE_BLOCK}" style="font-size: 7.5px;">OPERATOR</text>

  <!-- Flow Lane Grid -->
  <rect x="36" y="136" width="888" height="140" fill="{SURFACE_1}" stroke="{EDGE}" stroke-width="0.8" />

  <line x1="160" y1="136" x2="160" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="302" y1="136" x2="302" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="450" y1="136" x2="450" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />

  <!-- Standard path leading to Feasibility -->
  <path d="M 80 180 L 220 180 L 370 180" stroke="{EDGE}" stroke-width="2" stroke-dasharray="4,4" fill="none" />
  
  <!-- CORAL ESCALATION DIVERGENCE PATH -->
  <path id="lane-coral-diverge" d="M 370 180 Q 420 180 440 220 L 480 220 L 530 220" stroke="{TONE_BLOCK}" stroke-width="2.5" fill="none" filter="url(#glow-coral)" />

  <!-- Bypassed Stages (Hatched) -->
  <g opacity="0.4">
    <line x1="454" y1="180" x2="924" y2="180" stroke="{EDGE_SUBTLE}" stroke-width="1.5" stroke-dasharray="2,4" />
    <text x="600" y="174" fill="{FG_MUTED}" class="mono-xs">bypasses coding &amp; release stages</text>
  </g>

  <!-- Waypoints -->
  <g id="egate-1">
    <circle cx="80" cy="180" r="14" fill="{SURFACE_2}" stroke="{TONE_INFO}" stroke-width="1.5" />
    <text x="74" y="184" fill="{TONE_INFO}" class="mono-xs">#17</text>
    <text x="58" y="206" fill="{FG_MUTED}" class="mono-xs">Opened</text>
  </g>

  <g id="egate-2">
    <circle cx="220" cy="180" r="14" fill="{SURFACE_2}" stroke="{TONE_WAIT}" stroke-width="1.5" />
    <text x="210" y="184" fill="{TONE_WAIT}" class="mono-xs">BOUNCE</text>
    <text x="194" y="206" fill="{TONE_WAIT}" class="mono-xs">SIM PO Q&amp;A</text>
  </g>

  <g id="egate-3">
    <circle cx="370" cy="180" r="15" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="2" />
    <text x="358" y="184" fill="{TONE_BLOCK}" class="mono-xs">EVAL</text>
    <text x="340" y="206" fill="{FG_MUTED}" class="mono-xs">sdlc-feasibility</text>
  </g>

  <!-- ESCALATION CARD BOX (In Coral Tone) -->
  <g id="escalation-terminal-box">
    <rect x="490" y="152" width="424" height="114" rx="4" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="1.5" />
    <rect x="490" y="152" width="5" height="114" fill="{TONE_BLOCK}" />
    
    <circle cx="510" cy="172" r="5" fill="{TONE_BLOCK}" filter="url(#glow-coral)" />
    <text x="522" y="176" fill="{TONE_BLOCK}" class="mono-md">TERMINAL ESCALATION REASONS (STOPPED):</text>
    
    <text x="510" y="196" fill="{FG_DIM}" class="mono-xs">1. Requires production credentials, certs and secret rotation in Key Vault</text>
    <text x="510" y="211" fill="{FG_DIM}" class="mono-xs">2. Needs firewall, DNS and infra changes outside app/ workspace</text>
    <text x="510" y="226" fill="{FG_DIM}" class="mono-xs">3. Requires coordination and written sign-off with external vendor</text>
    <text x="510" y="244" fill="{TONE_BLOCK}" class="mono-xs">Action: Ticket parked for operator . Zero rogue edits . Capped at $0.015</text>
  </g>

  <!-- MOVING PILL (DIVERGES TO CORAL) -->
  <g id="active-coral-pill" transform="translate(80, 180)">
    <rect x="-44" y="-12" width="88" height="24" rx="12" fill="{SURFACE_3}" stroke="{TONE_BLOCK}" stroke-width="1.5" filter="url(#glow-coral)" />
    <circle cx="-32" cy="0" r="4" fill="{TONE_BLOCK}" />
    <text x="-24" y="4" fill="{FG}" class="mono-sm">#17</text>
    <rect x="0" y="-7" width="18" height="14" rx="2" fill="{SURFACE_1}" />
    <text x="3" y="4" fill="{TONE_BLOCK}" class="mono-xs">ES</text>
    <text x="22" y="4" fill="{TONE_BLOCK}" class="mono-xs">HALT</text>

    <!-- Path animation along the coral divergence curve -->
    <animateMotion dur="14s" repeatCount="indefinite" path="M 0 0 L 140 0 L 290 0 Q 340 0 360 40 L 450 40" keyTimes="0;0.2;0.45;0.65;1" />
  </g>

  <!-- Telemetry Card -->
  <rect x="36" y="290" width="888" height="110" rx="4" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <rect x="36" y="290" width="4" height="110" fill="{TONE_BLOCK}" />

  <text x="50" y="310" fill="{FG}" class="mono-md">CHRONOLOGICAL AUDIT TRAIL // ISSUE #17</text>
  <text x="340" y="310" fill="{FG_MUTED}" class="mono-xs">TITLE: "Move the live carrier integration to the new vendor and rotate the production keys"</text>

  <text x="50" y="332" fill="{FG_DIM}" class="mono-xs">00:00  [intake] Issue filed. Initial scoring gate: unclear requirements, scored below 80.</text>
  <text x="50" y="348" fill="{TONE_WAIT}" class="mono-xs">00:02  [simulated-po] Simulated product owner clarifies key rotation scope. Re-scored to 90/100 (ready).</text>
  <text x="50" y="364" fill="{TONE_BLOCK}" class="mono-xs">00:05  [sdlc-feasibility] Feasibility inspects workspace with GitHub MCP: suitable=False, risk=high.</text>
  <text x="50" y="380" fill="{TONE_BLOCK}" class="mono-xs">00:07  [escalation] Assigned terminal label escalated:not-agent-suitable. State comment posted.</text>
  <text x="50" y="394" fill="{FG_MUTED}" class="mono-xs">00:09  [orchestrator] Workflow safely halted with zero code edits. Final cost: $0.0153 USD (under cap).</text>

  <!-- Footer -->
  <rect x="12" y="408" width="936" height="20" fill="{SURFACE_0}" rx="3" />
  <text x="24" y="422" fill="{FG_MUTED}" class="mono-xs">TIMINGS COMPRESSED (ACTUAL: 6m WALL CLOCK) . RECORDED IN STATE:EVENTS.JSONL . BILLED COST: $0.0153 USD</text>
</svg>
"""


def generate_scenario_rollback_svg():
    """Generates docs/media/scenario-rollback.svg (PR #46 / Run 38180836579)"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 440" width="100%" height="100%">
  {common_style()}
  <defs>
    <filter id="glow-rollback" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="3" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
  </defs>

  <rect width="960" height="440" fill="{CANVAS}" />
  <rect x="12" y="12" width="936" height="416" rx="6" fill="none" stroke="{EDGE}" stroke-width="1" />

  <!-- Top Bar -->
  <rect x="12" y="12" width="936" height="42" fill="{SURFACE_0}" rx="6" />
  <line x1="12" y1="54" x2="948" y2="54" stroke="{EDGE}" stroke-width="1" />
  
  <circle cx="32" cy="33" r="5" fill="{TONE_BLOCK}" filter="url(#glow-rollback)">
    <animate attributeName="opacity" values="1;0.2;1" dur="1.2s" repeatCount="indefinite" />
  </circle>
  <text x="46" y="37" fill="{FG}" class="mono-title">SCENARIO 4 // CD SMOKE FAIL &amp; ROLLBACK (PR #46)</text>
  
  <rect x="520" y="24" width="96" height="18" rx="9" fill="{SURFACE_2}" stroke="{TONE_INFO}" stroke-width="1" />
  <text x="532" y="37" fill="{TONE_INFO}" class="mono-xs">SHA: 8137c60</text>

  <rect x="624" y="24" width="104" height="18" rx="9" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="1" />
  <text x="634" y="37" fill="{TONE_BLOCK}" class="mono-xs">SMOKE: FAILED</text>

  <rect x="736" y="24" width="200" height="18" rx="9" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="1" />
  <text x="746" y="37" fill="{TONE_BLOCK}" class="mono-xs">ROLLED BACK: 641cb02</text>

  <!-- Macrobands -->
  <rect x="36" y="66" width="300" height="22" fill="{SURFACE_1}" />
  <line x1="36" y1="66" x2="336" y2="66" stroke="{TONE_INFO}" stroke-width="2" />
  <text x="44" y="81" fill="{TONE_INFO}" class="mono-xs" letter-spacing="0.08em">MERGE &amp; CD PIPELINE</text>

  <rect x="344" y="66" width="310" height="22" fill="{SURFACE_1}" />
  <line x1="344" y1="66" x2="654" y2="66" stroke="{TONE_BLOCK}" stroke-width="2" />
  <text x="352" y="81" fill="{TONE_BLOCK}" class="mono-xs" letter-spacing="0.08em">STAGING VERIFICATION &amp; SMOKE FAILURE</text>

  <rect x="662" y="66" width="262" height="22" fill="{SURFACE_1}" />
  <line x1="662" y1="66" x2="924" y2="66" stroke="{TONE_BLOCK}" stroke-width="2" />
  <text x="670" y="81" fill="{TONE_BLOCK}" class="mono-xs" letter-spacing="0.08em">AUTOMATED ROLLBACK (ZERO PROD IMPACT)</text>

  <!-- Stage Columns -->
  <rect x="36" y="94" width="94" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="44" y="110" fill="{FG}" class="mono-xs">1. CI MERGE</text>
  <rect x="44" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.6" />
  <text x="48" y="123" fill="{TONE_RUN}" style="font-size: 7.5px;">6/6 OK</text>

  <rect x="136" y="94" width="98" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="144" y="110" fill="{FG}" class="mono-xs">2. CD PLAN</text>
  <rect x="144" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.6" />
  <text x="148" y="123" fill="{TONE_RUN}" style="font-size: 7.5px;">PASS</text>

  <rect x="240" y="94" width="96" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="248" y="110" fill="{FG}" class="mono-xs">3. BUILD</text>
  <rect x="248" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.6" />
  <text x="252" y="123" fill="{TONE_RUN}" style="font-size: 7.5px;">SITE-813</text>

  <rect x="344" y="94" width="102" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="350" y="110" fill="{TONE_INFO}" class="mono-xs">4. /staging/</text>
  <rect x="350" y="114" width="36" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_INFO}" stroke-width="0.6" />
  <text x="354" y="123" fill="{TONE_INFO}" style="font-size: 7.5px;">DEPLOY</text>

  <rect x="452" y="94" width="100" height="34" fill="{SURFACE_0}" stroke="{TONE_BLOCK}" stroke-width="1" />
  <text x="458" y="110" fill="{TONE_BLOCK}" class="mono-xs">5. SMOKE TEST</text>
  <rect x="458" y="114" width="40" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="0.6" />
  <text x="462" y="123" fill="{TONE_BLOCK}" style="font-size: 7.5px;">FAILED</text>

  <rect x="558" y="94" width="120" height="34" fill="{SURFACE_0}" stroke="{TONE_BLOCK}" stroke-width="1" />
  <text x="566" y="110" fill="{TONE_BLOCK}" class="mono-xs">6. ROLLBACK</text>
  <rect x="566" y="114" width="46" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="0.6" />
  <text x="570" y="123" fill="{TONE_BLOCK}" style="font-size: 7.5px;">RESTORE</text>

  <rect x="684" y="94" width="116" height="34" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <text x="692" y="110" fill="{FG}" class="mono-xs">7. PROD ROOT</text>
  <rect x="692" y="114" width="40" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.6" />
  <text x="696" y="123" fill="{TONE_RUN}" style="font-size: 7.5px;">UNTOUCH</text>

  <rect x="806" y="94" width="118" height="34" fill="{SURFACE_0}" stroke="{TONE_BLOCK}" stroke-width="0.8" />
  <text x="814" y="110" fill="{TONE_BLOCK}" class="mono-xs">8. FLAGGED</text>
  <rect x="814" y="114" width="50" height="11" rx="2" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="0.6" />
  <text x="818" y="123" fill="{TONE_BLOCK}" style="font-size: 7.5px;">ESCALATED</text>

  <!-- Matrix Grid -->
  <rect x="36" y="136" width="888" height="140" fill="{SURFACE_1}" stroke="{EDGE}" stroke-width="0.8" />

  <line x1="133" y1="136" x2="133" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="237" y1="136" x2="237" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="341" y1="136" x2="341" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="445" y1="136" x2="445" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="552" y1="136" x2="552" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="680" y1="136" x2="680" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />
  <line x1="802" y1="136" x2="802" y2="276" stroke="{EDGE_SUBTLE}" stroke-dasharray="2,2" />

  <!-- Outbound Deployment Path -->
  <path d="M 80 180 L 180 180 L 285 180 L 390 180 L 500 180" stroke="{EDGE}" stroke-width="2" stroke-dasharray="4,4" fill="none" />
  
  <!-- ROLLBACK RETURN PATH -->
  <path id="lane-rollback" d="M 500 180 Q 560 180 580 220 L 580 220 Q 520 235 390 235 L 390 235" stroke="{TONE_BLOCK}" stroke-width="2.5" stroke-dasharray="4,4" fill="none" filter="url(#glow-rollback)" />

  <path d="M 580 220 L 860 220" stroke="{TONE_BLOCK}" stroke-width="2" stroke-dasharray="3,3" fill="none" />

  <!-- Waypoints -->
  <g id="rgate-1">
    <circle cx="80" cy="180" r="14" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="1.5" />
    <text x="70" y="184" fill="{TONE_RUN}" class="mono-xs">8137</text>
    <text x="56" y="206" fill="{FG_MUTED}" class="mono-xs">main HEAD</text>
  </g>

  <g id="rgate-2">
    <circle cx="180" cy="180" r="14" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="1.5" />
    <text x="172" y="184" fill="{TONE_RUN}" class="mono-xs">PLAN</text>
    <text x="160" y="206" fill="{FG_MUTED}" class="mono-xs">6 checks OK</text>
  </g>

  <g id="rgate-3">
    <circle cx="285" cy="180" r="14" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="1.5" />
    <text x="278" y="184" fill="{TONE_RUN}" class="mono-xs">BLD</text>
    <text x="260" y="206" fill="{FG_MUTED}" class="mono-xs">Pages built</text>
  </g>

  <g id="rgate-4">
    <circle cx="390" cy="180" r="14" fill="{SURFACE_2}" stroke="{TONE_INFO}" stroke-width="1.5" />
    <text x="378" y="184" fill="{TONE_INFO}" class="mono-xs">STAGE</text>
    <text x="364" y="206" fill="{FG_MUTED}" class="mono-xs">22:34:33Z</text>
  </g>

  <g id="rgate-5">
    <circle cx="500" cy="180" r="16" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="2" filter="url(#glow-rollback)" />
    <text x="488" y="184" fill="{TONE_BLOCK}" class="mono-xs">FAIL</text>
    <text x="472" y="206" fill="{TONE_BLOCK}" class="mono-xs">Playwright Red</text>
  </g>

  <!-- Rollback Target Marker -->
  <g id="rgate-6">
    <rect x="340" y="222" width="100" height="26" rx="4" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="1.2" />
    <text x="348" y="238" fill="{TONE_BLOCK}" class="mono-xs">RESTORE: 641cb02</text>
  </g>

  <!-- Prod Protected Badge -->
  <g id="rgate-7">
    <rect x="692" y="168" width="100" height="26" rx="4" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="1.2" />
    <text x="702" y="184" fill="{TONE_RUN}" class="mono-xs">PROD: UNTOUCHED</text>
  </g>

  <!-- Ticket Flagged Badge -->
  <g id="rgate-8">
    <rect x="810" y="208" width="104" height="26" rx="4" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="1.2" />
    <text x="818" y="224" fill="{TONE_BLOCK}" class="mono-xs">FLAG: escalated</text>
  </g>

  <!-- MOVING DEPLOY PILL THAT TRIGGERS ROLLBACK -->
  <g id="active-rollback-pill" transform="translate(80, 180)">
    <rect x="-44" y="-12" width="88" height="24" rx="12" fill="{SURFACE_3}" stroke="{TONE_BLOCK}" stroke-width="1.5" filter="url(#glow-rollback)" />
    <circle cx="-32" cy="0" r="4" fill="{TONE_BLOCK}" />
    <text x="-24" y="4" fill="{FG}" class="mono-sm">#46</text>
    <rect x="0" y="-7" width="18" height="14" rx="2" fill="{SURFACE_1}" />
    <text x="3" y="4" fill="{TONE_BLOCK}" class="mono-xs">CD</text>
    <text x="22" y="4" fill="{TONE_BLOCK}" class="mono-xs">ROLL</text>

    <!-- Enters staging, fails smoke, sweeps back on rollback path -->
    <animateMotion dur="14s" repeatCount="indefinite" path="M 0 0 L 100 0 L 205 0 L 310 0 L 420 0 Q 480 0 500 40 Q 440 55 310 55" keyTimes="0;0.15;0.30;0.45;0.60;0.75;1" />
  </g>

  <!-- Telemetry Card -->
  <rect x="36" y="290" width="888" height="110" rx="4" fill="{SURFACE_0}" stroke="{EDGE}" stroke-width="0.8" />
  <rect x="36" y="290" width="4" height="110" fill="{TONE_BLOCK}" />

  <text x="50" y="310" fill="{FG}" class="mono-md">CHRONOLOGICAL AUDIT TRAIL // RUN 38180836579 (PR #46)</text>
  <text x="450" y="310" fill="{FG_MUTED}" class="mono-xs">COMMIT: 8137c6015abac2033e1962715727bd06618809a7</text>

  <text x="50" y="332" fill="{FG_DIM}" class="mono-xs">22:34:33Z  [stage] Built site-8137c60 deployed to /staging/. Dispatch pages.yml verified live build.json.</text>
  <text x="50" y="348" fill="{TONE_BLOCK}" class="mono-xs">22:36:20Z  [smoke] Playwright e2e test on staging failed (heading assertion). Job smoke concluded failure.</text>
  <text x="50" y="364" fill="{TONE_BLOCK}" class="mono-xs">22:36:20Z  [rollback] Automated rollback engaged. Copied previous prod sha (641cb02) to staging/.</text>
  <text x="50" y="380" fill="{TONE_RUN}" class="mono-xs">22:37:05Z  [verification] Production root remained 100% healthy at 641cb02. Zero downtime or bad tags.</text>
  <text x="50" y="394" fill="{TONE_BLOCK}" class="mono-xs">22:37:10Z  [ticket] Flagged PR #46 with label escalated:deploy-failed. Orchestrator halted work on ticket.</text>

  <!-- Footer -->
  <rect x="12" y="408" width="936" height="20" fill="{SURFACE_0}" rx="3" />
  <text x="24" y="422" fill="{FG_MUTED}" class="mono-xs">TIMINGS COMPRESSED (ACTUAL: 2m 47s WALL CLOCK) . RECORDED IN ORIGIN/DEPLOY:DEPLOY.JSON . ZERO PROD DOWNTIME</text>
</svg>
"""


def generate_hero_svg():
    """Generates docs/media/hero.svg (Master Header)"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 520" width="100%" height="100%">
  {common_style()}
  <defs>
    <filter id="hero-glow-run" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="3" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
    <filter id="hero-glow-coral" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="3" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
    <pattern id="hero-grid" width="20" height="20" patternUnits="userSpaceOnUse">
      <path d="M 20 0 L 0 0 0 20" fill="none" stroke="{EDGE_SUBTLE}" stroke-width="0.5" />
    </pattern>
  </defs>

  <!-- Canvas -->
  <rect width="1000" height="520" fill="{CANVAS}" />
  <rect width="1000" height="520" fill="url(#hero-grid)" opacity="0.6" />
  <rect x="12" y="12" width="976" height="496" rx="6" fill="none" stroke="{EDGE}" stroke-width="1" />

  <!-- ==================== HEADER BAR ==================== -->
  <rect x="12" y="12" width="976" height="46" fill="{SURFACE_0}" rx="6" />
  <line x1="12" y1="58" x2="988" y2="58" stroke="{EDGE}" stroke-width="1" />
  
  <circle cx="34" cy="35" r="5" fill="{TONE_RUN}" filter="url(#hero-glow-run)">
    <animate attributeName="opacity" values="1;0.4;1" dur="2s" repeatCount="indefinite" />
  </circle>
  <text x="48" y="39" fill="{FG}" class="mono-title">AZURE FOUNDRY // AUTONOMOUS SDLC</text>
  
  <!-- Header Telemetry Chips -->
  <rect x="520" y="24" width="86" height="22" rx="4" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="0.8" />
  <text x="528" y="39" fill="{TONE_RUN}" class="mono-xs">10 AGENTS</text>

  <rect x="614" y="24" width="100" height="22" rx="4" fill="{SURFACE_2}" stroke="{TONE_WAIT}" stroke-width="0.8" />
  <text x="622" y="39" fill="{TONE_WAIT}" class="mono-xs">14s CYCLE (CMP)</text>

  <rect x="722" y="24" width="96" height="22" rx="4" fill="{SURFACE_2}" stroke="{TONE_DONE}" stroke-width="0.8" />
  <text x="730" y="39" fill="{TONE_DONE}" class="mono-xs">ZERO HUMAN</text>

  <!-- Live Spend Pill -->
  <rect x="826" y="24" width="150" height="22" rx="11" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="1" />
  <circle cx="838" cy="35" r="3.5" fill="{TONE_RUN}" />
  <text x="846" y="39" fill="{FG}" class="mono-xs">BILLED: $1.86 / $25 CAP</text>

  <!-- ==================== UPPER SECTION: SYSTEM TOPOLOGY NETWORK ==================== -->
  <rect x="28" y="70" width="944" height="162" rx="4" fill="{SURFACE_1}" stroke="{EDGE}" stroke-width="0.8" />
  <rect x="28" y="70" width="944" height="2" fill="{TONE_INFO}" />

  <text x="42" y="88" fill="{TONE_INFO}" class="mono-xs" letter-spacing="0.08em">SYSTEM TOPOLOGY // AUTOMATED REPOSITORY ENGINE</text>

  <!-- Topology Node 1: GitHub -->
  <g transform="translate(42, 98)">
    <rect width="130" height="50" rx="3" fill="{SURFACE_2}" stroke="{EDGE}" />
    <text x="10" y="20" fill="{FG}" class="mono-xs" font-weight="700">GITHUB REPO</text>
    <text x="10" y="34" fill="{FG_MUTED}" style="font-size: 8px;">issues, PRs, gates</text>
    <rect x="86" y="8" width="36" height="12" rx="2" fill="{SURFACE_0}" stroke="{TONE_INFO}" stroke-width="0.5" />
    <text x="90" y="17" fill="{TONE_INFO}" style="font-size: 7px;">PAT</text>
  </g>

  <!-- Topology Node 2: Routine Timer -->
  <g transform="translate(202, 98)">
    <rect width="130" height="50" rx="3" fill="{SURFACE_2}" stroke="{EDGE}" />
    <text x="10" y="20" fill="{FG}" class="mono-xs" font-weight="700">ROUTINE TIMER</text>
    <text x="10" y="34" fill="{FG_MUTED}" style="font-size: 8px;">cron: */5m wake</text>
    <rect x="86" y="8" width="36" height="12" rx="2" fill="{SURFACE_0}" stroke="{TONE_WAIT}" stroke-width="0.5" />
    <text x="90" y="17" fill="{TONE_WAIT}" style="font-size: 7px;">CRON</text>
  </g>

  <!-- Topology Node 3: Orchestrator -->
  <g transform="translate(362, 92)">
    <rect width="156" height="62" rx="3" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="1.2" />
    <circle cx="16" cy="18" r="3.5" fill="{TONE_RUN}" />
    <text x="24" y="21" fill="{FG}" class="mono-xs" font-weight="700">ORCHESTRATOR</text>
    <text x="12" y="35" fill="{FG_DIM}" style="font-size: 8px;">Deterministic state machine</text>
    <text x="12" y="47" fill="{FG_MUTED}" style="font-size: 8px;">Owns merges . Invocations</text>
    <rect x="104" y="8" width="44" height="12" rx="2" fill="{SURFACE_0}" stroke="{TONE_RUN}" stroke-width="0.5" />
    <text x="108" y="17" fill="{TONE_RUN}" style="font-size: 7px;">HOSTED</text>
  </g>

  <!-- Topology Node 4: Prompt Agents & Coder -->
  <g transform="translate(548, 98)">
    <rect width="144" height="50" rx="3" fill="{SURFACE_2}" stroke="{EDGE}" />
    <text x="10" y="18" fill="{FG}" class="mono-xs" font-weight="700">AGENTS CLUSTER</text>
    <text x="10" y="32" fill="{FG_MUTED}" style="font-size: 8px;">8 prompt agents (specialized)</text>
    <text x="10" y="43" fill="{FG_MUTED}" style="font-size: 8px;">sdlc-coder (sandbox agy)</text>
    <rect x="100" y="8" width="36" height="12" rx="2" fill="{SURFACE_0}" stroke="{TONE_AGENT}" stroke-width="0.5" />
    <text x="104" y="17" fill="{TONE_AGENT}" style="font-size: 7px;">FLEET</text>
  </g>

  <!-- Topology Node 5: CI Gates -->
  <g transform="translate(722, 98)">
    <rect width="116" height="50" rx="3" fill="{SURFACE_2}" stroke="{EDGE}" />
    <text x="10" y="18" fill="{FG}" class="mono-xs" font-weight="700">6 CI GATES</text>
    <text x="10" y="32" fill="{FG_MUTED}" style="font-size: 8px;">test, coverage, e2e</text>
    <text x="10" y="43" fill="{FG_MUTED}" style="font-size: 8px;">gitleaks, tdd, scope</text>
    <rect x="74" y="8" width="34" height="12" rx="2" fill="{SURFACE_0}" stroke="{TONE_BLOCK}" stroke-width="0.5" />
    <text x="78" y="17" fill="{TONE_BLOCK}" style="font-size: 7px;">GATE</text>
  </g>

  <!-- Topology Node 6: CD & Ledger -->
  <g transform="translate(868, 98)">
    <rect width="90" height="50" rx="3" fill="{SURFACE_2}" stroke="{EDGE}" />
    <text x="8" y="18" fill="{FG}" class="mono-xs" font-weight="700">CD &amp; STATE</text>
    <text x="8" y="32" fill="{FG_MUTED}" style="font-size: 8px;">smoke, soak</text>
    <text x="8" y="43" fill="{FG_MUTED}" style="font-size: 8px;">branch state</text>
    <rect x="52" y="8" width="32" height="12" rx="2" fill="{SURFACE_0}" stroke="{TONE_DONE}" stroke-width="0.5" />
    <text x="56" y="17" fill="{TONE_DONE}" style="font-size: 7px;">PROD</text>
  </g>

  <!-- Moving Pulse Dots in Network -->
  <path d="M 172 123 L 362 123" stroke="{EDGE}" stroke-width="1.5" stroke-dasharray="3,3" />
  <circle cx="172" cy="123" r="3" fill="{TONE_INFO}">
    <animateMotion dur="2.4s" repeatCount="indefinite" path="M 0 0 L 190 0" />
  </circle>

  <path d="M 518 123 L 548 123" stroke="{EDGE}" stroke-width="1.5" stroke-dasharray="3,3" />
  <circle cx="518" cy="123" r="3" fill="{TONE_AGENT}">
    <animateMotion dur="1.8s" repeatCount="indefinite" path="M 0 0 L 30 0" />
  </circle>

  <path d="M 692 123 L 722 123" stroke="{EDGE}" stroke-width="1.5" stroke-dasharray="3,3" />
  <circle cx="692" cy="123" r="3" fill="{TONE_RUN}">
    <animateMotion dur="2s" repeatCount="indefinite" path="M 0 0 L 30 0" />
  </circle>

  <path d="M 838 123 L 868 123" stroke="{EDGE}" stroke-width="1.5" stroke-dasharray="3,3" />
  <circle cx="838" cy="123" r="3" fill="{TONE_DONE}">
    <animateMotion dur="2.2s" repeatCount="indefinite" path="M 0 0 L 30 0" />
  </circle>

  <!-- Network Summary Metrics Bar inside upper box -->
  <rect x="42" y="166" width="916" height="52" rx="3" fill="{SURFACE_0}" stroke="{EDGE_SUBTLE}" />
  <text x="56" y="186" fill="{FG_DIM}" class="mono-xs">GATES VERIFIED: 100% (6/6 REQUIRED)</text>
  <text x="56" y="202" fill="{TONE_RUN}" class="mono-xs">TDD ORDER: 100% RED-FIRST COMMIT</text>

  <text x="340" y="186" fill="{FG_DIM}" class="mono-xs">CD PROMOTIONS: 5 SHIPPED TO PROD</text>
  <text x="340" y="202" fill="{TONE_DONE}" class="mono-xs">ZERO-HUMAN ACTIONS: 100% COMPLETED</text>

  <text x="640" y="186" fill="{FG_DIM}" class="mono-xs">RECORDED TRACES: 229 EVENTS COMMITTED</text>
  <text x="640" y="202" fill="{TONE_WAIT}" class="mono-xs">ORCHESTRATOR USD: $0.76 (MODEL $1.86 TOTAL)</text>

  <!-- ==================== LOWER SECTION: 4 CONCURRENT SCENARIOS ==================== -->
  <rect x="28" y="244" width="944" height="236" rx="4" fill="{SURFACE_1}" stroke="{EDGE}" stroke-width="0.8" />
  <rect x="28" y="244" width="944" height="2" fill="{TONE_AGENT}" />

  <!-- Section Title -->
  <text x="42" y="260" fill="{FG}" class="mono-xs" font-weight="700">DELIVERY FLOW LANES // REAL SCENARIOS</text>

  <!-- Macrobands Strip (Dedicated Row) -->
  <line x1="260" y1="258" x2="440" y2="258" stroke="{TONE_INFO}" stroke-width="1.5" />
  <text x="260" y="255" fill="{TONE_INFO}" style="font-size: 7.5px;">SHAPE . BUSINESS</text>

  <line x1="450" y1="258" x2="680" y2="258" stroke="{TONE_AGENT}" stroke-width="1.5" />
  <text x="450" y="255" fill="{TONE_AGENT}" style="font-size: 7.5px;">BUILD (TDD)</text>

  <line x1="690" y1="258" x2="940" y2="258" stroke="{TONE_DONE}" stroke-width="1.5" />
  <text x="690" y="255" fill="{TONE_DONE}" style="font-size: 7.5px;">RELEASE (CD)</text>

  <!-- Lane 1: Feature #24 -->
  <g transform="translate(42, 270)">
    <rect width="916" height="46" rx="3" fill="{SURFACE_0}" stroke="{EDGE_SUBTLE}" />
    <text x="12" y="19" fill="{FG}" class="mono-xs" font-weight="700">1. FEATURE #24</text>
    <text x="12" y="33" fill="{FG_MUTED}" style="font-size: 8px;">Make parcel tracker better</text>
    
    <text x="200" y="27" fill="{TONE_WAIT}" class="mono-xs">Refined (90%)</text>
    <text x="290" y="27" fill="{FG_MUTED}">→</text>
    <text x="310" y="27" fill="{TONE_AGENT}" class="mono-xs">Feasible: OK</text>
    <text x="400" y="27" fill="{FG_MUTED}">→</text>
    <text x="420" y="27" fill="{TONE_RUN}" class="mono-xs">c0f5713 (red)</text>
    <text x="510" y="27" fill="{FG_MUTED}">→</text>
    <text x="530" y="27" fill="{TONE_RUN}" class="mono-xs">fcc6f1e (grn)</text>
    <text x="620" y="27" fill="{FG_MUTED}">→</text>
    <text x="640" y="27" fill="{TONE_RUN}" class="mono-xs">PR #29 (6/6)</text>
    <text x="730" y="27" fill="{FG_MUTED}">→</text>
    <text x="750" y="27" fill="{TONE_DONE}" class="mono-xs">v0.3.0 Live</text>

    <!-- Animated Pill -->
    <g transform="translate(140, 23)">
      <rect x="-30" y="-8" width="60" height="16" rx="8" fill="{SURFACE_2}" stroke="{TONE_RUN}" stroke-width="1" />
      <circle cx="-22" cy="0" r="3" fill="{TONE_RUN}" />
      <text x="-16" y="3" fill="{FG}" style="font-size: 8px;">#24</text>
      <text x="4" y="3" fill="{TONE_RUN}" style="font-size: 7.5px;">$0.08</text>
      <animateMotion dur="14s" repeatCount="indefinite" path="M 0 0 L 110 0 L 220 0 L 330 0 L 440 0 L 560 0 L 680 0" />
    </g>
  </g>

  <!-- Lane 2: Bug #25 -->
  <g transform="translate(42, 324)">
    <rect width="916" height="44" rx="3" fill="{SURFACE_0}" stroke="{EDGE_SUBTLE}" />
    <text x="12" y="19" fill="{FG}" class="mono-xs" font-weight="700">2. BUG #25</text>
    <text x="12" y="32" fill="{FG_MUTED}" style="font-size: 8px;">Lowercase tracking rejected</text>

    <text x="200" y="27" fill="{TONE_WAIT}" class="mono-xs">Triage: s3/api</text>
    <text x="290" y="27" fill="{FG_MUTED}">→</text>
    <text x="310" y="27" fill="{TONE_AGENT}" class="mono-xs">Req: 83/100</text>
    <text x="400" y="27" fill="{FG_MUTED}">→</text>
    <text x="420" y="27" fill="{TONE_BLOCK}" class="mono-xs">6816a92 (red)</text>
    <text x="510" y="27" fill="{FG_MUTED}">→</text>
    <text x="530" y="27" fill="{TONE_RUN}" class="mono-xs">a132025 (fix)</text>
    <text x="620" y="27" fill="{FG_MUTED}">→</text>
    <text x="640" y="27" fill="{TONE_RUN}" class="mono-xs">PR #26 (6/6)</text>
    <text x="730" y="27" fill="{FG_MUTED}">→</text>
    <text x="750" y="27" fill="{TONE_DONE}" class="mono-xs">v0.1.1 Live</text>

    <g transform="translate(140, 22)">
      <rect x="-30" y="-8" width="60" height="16" rx="8" fill="{SURFACE_2}" stroke="{TONE_WAIT}" stroke-width="1" />
      <circle cx="-22" cy="0" r="3" fill="{TONE_BLOCK}" />
      <text x="-16" y="3" fill="{FG}" style="font-size: 8px;">#25</text>
      <text x="4" y="3" fill="{TONE_RUN}" style="font-size: 7.5px;">$0.04</text>
      <animateMotion dur="14s" repeatCount="indefinite" path="M 0 0 L 110 0 L 220 0 L 330 0 L 440 0 L 560 0 L 680 0" />
    </g>
  </g>

  <!-- Lane 3: Escalation #17 -->
  <g transform="translate(42, 374)">
    <rect width="916" height="44" rx="3" fill="{SURFACE_0}" stroke="{EDGE_SUBTLE}" />
    <text x="12" y="19" fill="{TONE_BLOCK}" class="mono-xs" font-weight="700">3. VAGUE &amp; ESC #17</text>
    <text x="12" y="32" fill="{FG_MUTED}" style="font-size: 8px;">Rotate prod vendor keys</text>

    <text x="200" y="27" fill="{TONE_WAIT}" class="mono-xs">Score &lt;80 (Bounce)</text>
    <text x="310" y="27" fill="{FG_MUTED}">→</text>
    <text x="330" y="27" fill="{TONE_WAIT}" class="mono-xs">SIM PO Answers (90)</text>
    <text x="460" y="27" fill="{FG_MUTED}">→</text>
    <text x="480" y="27" fill="{TONE_BLOCK}" class="mono-xs">Feasibility: NOT SUITABLE</text>
    <text x="640" y="27" fill="{FG_MUTED}">→</text>
    <text x="660" y="27" fill="{TONE_BLOCK}" class="mono-xs">HALTED: Operator desk . $0.015</text>

    <g transform="translate(140, 22)">
      <rect x="-30" y="-8" width="60" height="16" rx="8" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="1" />
      <circle cx="-22" cy="0" r="3" fill="{TONE_BLOCK}" />
      <text x="-16" y="3" fill="{FG}" style="font-size: 8px;">#17</text>
      <text x="4" y="3" fill="{TONE_BLOCK}" style="font-size: 7.5px;">HALT</text>
      <animateMotion dur="14s" repeatCount="indefinite" path="M 0 0 L 140 0 L 280 0 L 460 0" />
    </g>
  </g>

  <!-- Lane 4: Rollback #46 -->
  <g transform="translate(42, 424)">
    <rect width="916" height="44" rx="3" fill="{SURFACE_0}" stroke="{EDGE_SUBTLE}" />
    <text x="12" y="19" fill="{TONE_BLOCK}" class="mono-xs" font-weight="700">4. CD SMOKE FAIL #46</text>
    <text x="12" y="32" fill="{FG_MUTED}" style="font-size: 8px;">Deploy run 38180836579</text>

    <text x="200" y="27" fill="{TONE_INFO}" class="mono-xs">Merge: 8137c60</text>
    <text x="290" y="27" fill="{FG_MUTED}">→</text>
    <text x="310" y="27" fill="{TONE_INFO}" class="mono-xs">Staging Deployed</text>
    <text x="430" y="27" fill="{FG_MUTED}">→</text>
    <text x="450" y="27" fill="{TONE_BLOCK}" class="mono-xs">Playwright Smoke FAIL</text>
    <text x="610" y="27" fill="{FG_MUTED}">→</text>
    <text x="630" y="27" fill="{TONE_BLOCK}" class="mono-xs">ROLLBACK to 641cb02 . Prod Intact</text>

    <g transform="translate(140, 22)">
      <rect x="-30" y="-8" width="60" height="16" rx="8" fill="{SURFACE_2}" stroke="{TONE_BLOCK}" stroke-width="1" />
      <circle cx="-22" cy="0" r="3" fill="{TONE_BLOCK}" />
      <text x="-16" y="3" fill="{FG}" style="font-size: 8px;">#46</text>
      <text x="4" y="3" fill="{TONE_BLOCK}" style="font-size: 7.5px;">ROLL</text>
      <animateMotion dur="14s" repeatCount="indefinite" path="M 0 0 L 120 0 L 250 0 L 430 0" />
    </g>
  </g>

  <!-- Footer -->
  <rect x="12" y="488" width="976" height="20" fill="{SURFACE_0}" rx="3" />
  <text x="24" y="502" fill="{FG_MUTED}" class="mono-xs">TIMINGS COMPRESSED (14s LOOP) . REAL RECORDED TRACES (EVENTS.JSONL) . 100% PURE VECTOR SVG . ZERO SCRIPTS</text>
</svg>
"""


def main():
    print("=== Generating Perfected Animated SVG Assets ===")
    os.makedirs("docs/media", exist_ok=True)

    files = {
        "docs/media/topology.svg": generate_topology_svg(),
        "docs/media/scenario-feature.svg": generate_scenario_feature_svg(),
        "docs/media/scenario-bug.svg": generate_scenario_bug_svg(),
        "docs/media/scenario-escalation.svg": generate_scenario_escalation_svg(),
        "docs/media/scenario-rollback.svg": generate_scenario_rollback_svg(),
        "docs/media/hero.svg": generate_hero_svg(),
    }

    for path, content in files.items():
        with open(path, "w", encoding="utf-8") as f:
            f.write(content.strip() + "\n")
        print(f"Generated: {path} ({len(content)} bytes)")

    print("\nAll 6 SVGs generated successfully.")


if __name__ == "__main__":
    main()
