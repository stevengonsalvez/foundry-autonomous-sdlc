# Metrics dashboard

A static page that shows how the autonomous SDLC is doing. No build step, no framework, no external requests: plain HTML, CSS and ES modules, with charts drawn as inline SVG. It reads `./metrics.json` (schema version 1, defined in [docs/architecture.md](../docs/architecture.md), section "Metrics") and renders it.

## What it shows

Header: repository, time the data was generated, and counts of issues, released and escalated issues, plus total spend against the cap.

| Panel | Shows | Notes |
|-------|-------|-------|
| Cycle time per stage | Median time in each stage across issues, and one stacked bar per issue | Stages still running are drawn faded and left out of the median, never counted as zero. A table with every value sits behind the charts. |
| Gate pass rates | Per gate: share of issues that passed on the first attempt and eventually, with counts | First attempt needs per-issue `gate_attempts` (see below). Without it the panel says so and shows only the eventual rate. |
| Defect owner and resolution time | Bugs only: owner, severity, time from opened to release | Open bugs show no resolution time. |
| Cost per issue | Model cost, coder cost (runtime plus its model), calls and total per issue, and the total against the 5 USD cap | Progress bar marks the 4.50 USD point where the loop stops new work. Orchestrator compute is its own row. Each row shows the 1 USD per issue line and flags issues over it. |
| Scenarios and issues | Every issue with scenario, type, outcome, and links to its GitHub issue, pull request and release | Links are built from `repo` and the numbers in the data. |

Page states: loading, no data yet (file missing or empty, or no issues), and error (fetch failure, invalid JSON, or an unsupported schema version, with a retry button). The dashboard never invents data.

## Data

`metrics.json` is written by the orchestrator to the `metrics` branch. `scripts/build_pages.sh` validates it (JSON object, matching `version`) and copies it to `dashboard/metrics.json` in the Pages artifact.

Fields read beyond the base schema (the orchestrator writes all of them; each is optional for the dashboard):

- `gate_attempts` on an entry: ordered check conclusions per gate, oldest first. First element is the first attempt, the final `gates` value is the eventual result.
- `gate_pass_rates[gate]`: `pass` and `fail` count evaluated heads and are shown as run counts; `first_pass` and `first_fail` give the first-attempt rate across all objects. Without them the first attempt is derived from `gate_attempts`, and without those it shows "n/a".
- The stage an object is in has `in_progress: true` and `seconds: 0`. The dashboard measures it up to `generated_at`, draws it faded, and keeps it out of the medians. Terminal stages (`stage:released`, `escalated:*`) have no duration and are not charted.
- An entry with `kind: "pr"` and `number: null` (the maintenance PR) is identified by its `pr` and shown as "PR #n".
- `escalation` is shown next to the Escalated outcome. `resolution_seconds` is opened to released, so the defect column reads "Opened to release".
- Cost: "Coder" is `coder_usd` plus `coder_model_usd`. `totals.orchestrator_usd` is its own row in the cost table and part of the total. `totals.escalated` feeds the header count.
- A missing stage `seconds` is derived from the next stage's `entered_at`; `type` and `owner` may carry their label prefix.

Entries with neither an issue number nor a `pr` are skipped and the page says how many.

## Layout

```
index.html          page shell
css/styles.css      tokens (light and dark), layout, components
js/aggregate.js     pure functions: parse, median, stage durations, gate rates, cost, defects, links
js/format.js        durations, money, percentages, timestamps
js/charts.js        SVG drawing, (width, data) -> SVG element
js/panels.js        panels and page states, DOM only
js/main.js          fetch, state selection
js/dom.js           element builders, resize-aware chart host
test/               tests, dev server, fixture (never published)
```

All data is inserted as text nodes. No `innerHTML`.

## Develop locally

Needs Node 22 or newer.

```sh
cd dashboard
npm run dev                          # http://127.0.0.1:8080/ with the sample fixture as metrics.json
npm run dev -- --state empty         # also: bad-version, invalid-json, http-500
npm run dev -- --port 9000
npm test                             # unit tests for aggregation and for scripts/build_pages.sh
```

The dev server answers `/metrics.json` from `test/fixtures/metrics.sample.json` without copying it anywhere. Open the page through the server, not from disk, because browsers block `fetch` on `file://`.

## Publishing

```sh
scripts/build_pages.sh <output_dir> [metrics_checkout_dir]
```

The app lands at the root of `output_dir` and the dashboard at `/dashboard/`. Only `index.html`, `css/` and `js/` are copied, so tests, the fixture, `package.json` and this file never reach the site; the script also fails if anything test-shaped ends up in the output. Set `APP_DIST` to use a prebuilt app directory instead of running `npm ci && npm run build:pages`.

## Accessibility

Landmarks, a skip link, real tables for every chart (collapsed under "Show data table" for the two charts), charts exposed as labelled images with the table as the full alternative, visible focus, keyboard-scrollable table regions, text on every status badge, `prefers-color-scheme` and `prefers-reduced-motion` honoured, usable from 360 px.
