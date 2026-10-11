# Control Center

A read-only static web app that shows the autonomous SDLC end to end: every ticket (GitHub issue) from backlog to production, with its cost, gates, environment hops, agent activity, escalations and the questions-back trail. Plain HTML, CSS and ES modules with inline SVG charts. No build step, no framework, no dependencies, no requests except the GitHub reads listed below.

Live at `https://stevengonsalvez.github.io/foundry-autonomous-sdlc/control-center/`. Tickets are created on GitHub (the "New ticket" and "Report a bug" buttons open the issue forms); this page never writes anything.

## Views

| Route | Shows |
|-------|-------|
| `#/` | Kanban of all tickets in the nine board columns, with type filters, search, a "hide finished older than 7 days" switch, cost bar against the 3 USD per-issue cap, flags, and tickets the ledger has not seen yet ("waiting for ledger") |
| `#/ticket/<n>` | One ticket: stage timeline, gates, cost split, environment hops, pull request and test-first commit order, refinement and coder, questions back, reviewer verdicts, CI triage, escalation |
| `#/cost` | Ledger estimate against Azure billed spend, against the 22 USD halt line and the 25 USD cap, meter breakdown, ledger compute, per-ticket table (sortable) |
| `#/environments` | Staging and production, rollbacks, releases with outcome, full deploy history |
| `#/agents` | The 11 agents with state (text and dot), spend, errors, current object, the last tick and ledger notices |
| `#/escalations` | Every escalation, newest first, with reasons, what the agent tried and evidence |
| `#/flow` | Cycle time per stage, lead time, change failure rate, work in progress, first-attempt gate pass rate, defects, cost against the cap, scenarios. Each chart has a table behind it |
| `#/trail` | Questions back (answered by a simulated product owner), reviewer verdicts and CI triage across tickets, filterable |

Loading skeleton, empty state, error state with retry, light and dark theme (system default, remembered), keyboard and screen reader support, `prefers-reduced-motion` honoured, usable from 360 px.

## Data contract

The single input is `state.json`, schema version 1, written by the ledger (`agents/sdlc_agents/ledger`, see `model.py` for the ticket record and `fold.py` for the rest). `test/fixtures/state.sample.json` is a real sample and is the schema reference for the tests. Every optional field may be missing or null: `js/schema.js` is the one place that coerces, so views never guard against missing data. A malformed file, an unsupported `version` or invalid JSON shows the error state; nothing is invented to fill a gap (billed spend that has not been read says so).

## Fetch strategy and its measured limits

Every request is a `GET`. There is no token anywhere and no write call (`test/static.test.mjs` greps for it).

| Source | URL | Cadence | Notes |
|--------|-----|---------|-------|
| raw | `raw.githubusercontent.com/.../state/state.json` | every 30 s, `cache: "no-store"` | Measured: sends `cache-control: max-age=300` and ignores the query string in its cache key, so it can be up to 5 minutes behind. No rate budget. |
| api | `api.github.com/repos/.../contents/state.json?ref=state`, `Accept: application/vnd.github.raw+json` | every 60 s while the tab is visible, conditional with the ETag | Measured: CORS is open, responses cache for 60 s. |
| issues | `api.github.com/repos/.../issues?state=open&sort=created&direction=desc&per_page=30`, ETag | every 60 s | Pending intake: open issues by the repo owner that the ledger has not recorded yet appear as backlog cards badged "waiting for ledger" within about a minute. Pull requests and other authors are ignored. When `state.json` contains the issue the card is replaced silently. |

api and issues share one unauthenticated budget of 60 requests per hour per IP, and a 304 still counts. So the page reads `x-ratelimit-remaining` and `x-ratelimit-reset` from every response and adapts (`js/data.js`):

- 40 or more remaining: both API calls at their normal 60 s cadence.
- Below 40: the api accelerator stops (raw still covers state) and the issues call, which is the priority, is spread so the remaining calls last until the window resets.
- Below 15: no API calls until reset. raw keeps working.
- 403 or 429: back off until the reset (quota gone), the `retry-after` (secondary limit) or an exponential step. Other failures back off 30 s, doubling up to 10 minutes.

The newest `generated_at` wins and the header says which source supplied what is on screen ("source: raw", "api" or "file"). The header shows the age of `updated_at` (ticking), a STALE badge when `generated_at` is older than 10 minutes (the orchestrator is not ticking or the ledger is down), and a manual refresh. Polling pauses while the tab is hidden and refreshes immediately when it is shown again.

Override for tests and screenshots: `?data=<relative path>.json` loads a same-origin JSON file and makes no GitHub request; `&issues=<relative path>.json` also turns on pending intake from a file. Only paths matching `^[\w./-]+\.json$` without `..`, a leading `/` or `//` are accepted, and the resolved URL must be same origin (`js/safe.js`).

## Security model

All data (issue titles, escalation reasons, agent questions and answers, review findings, error text) is attacker-influenced and is treated as text:

- Data only ever becomes text nodes. There is no `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, inline handler or inline script anywhere; `js/dom.js` is the only place attributes are set and it throws on `on*`, `style`, `src` and any `href` that is not a fragment, a site link or a link into this repository.
- Links are built from known templates (`https://github.com/stevengonsalvez/foundry-autonomous-sdlc/...`). A `url`, `run_url` or `evidence_url` from the data is dropped unless it starts with that prefix after URL normalisation (no userinfo, no port, no `..`). External links use `target="_blank"` and `rel="noopener noreferrer"`. Free text is never turned into a link.
- Long strings are clamped with CSS (and capped where CSS cannot reach: badges, document title, chart labels).
- Content Security Policy in a `<meta>` tag: `default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self' https://raw.githubusercontent.com https://api.github.com; base-uri 'none'; form-action 'none'`. There are no inline styles; dynamic sizes are CSS variables set through the CSSOM, which the policy allows. `frame-ancestors` is deliberately left out: browsers ignore it in a meta tag and log an error for it, and GitHub Pages cannot send response headers.
- `test/browser.test.mjs` renders a fixture full of hostile strings (`<img onerror>`, `</script>`, `javascript:` URLs, 5000 character titles, foreign and traversal links) on every view at desktop and phone width and proves nothing is injected, no handler runs and no unsafe link exists.

## Layout

```
index.html           page shell and CSP
css/styles.css       tokens (light and dark with light-dark()), layout, components
js/theme.js          applies the saved theme before first paint (a classic script, so no inline code is needed)
js/main.js           wiring: poller -> store -> view, routing, polling schedule
js/data.js           fetch strategy: rate budget, ETags, backoff, pending intake (pure, takes fetch and a clock)
js/store.js          newest state wins, source, problems
js/schema.js         parse and normalise state.json
js/model.js          selectors: board, filters, time in stage, gates, cost, trail, environments
js/format.js         durations, money, relative and UTC times
js/safe.js           URL validation, ?data= validation, text limits
js/dom.js            element builders (text only), time helpers, tables
js/charts.js         SVG charts, (width, data) -> SVG element
js/icons.js          inline icons
js/shell.js          nav, freshness, theme switch, spend banner
js/router.js         hash routes
js/views/*.js        one file per view, plus common.js and states.js
test/                tests, dev server, fixtures (never published)
```

## Develop and test

Needs Node 22 or newer.

```sh
cd apps/control-center
npm run dev                         # http://127.0.0.1:8090/?data=state.json&issues=issues.json
npm run dev -- --state stale        # also: normal, empty, missing, bad-version, invalid-json, http-500, hostile
npm run dev -- --port 9000 --fixed  # --fixed keeps the fixture's own timestamps
npm test                            # unit tests, static checks, and the browser tests
npm run shots                       # screenshots into docs/proof/
```

Unless `--fixed`, the dev server shifts every timestamp in the fixture so the snapshot looks two minutes old (35 minutes for `--state stale`).

The browser tests and screenshots use Playwright and axe from the app workspace: `cd app && npm ci && npx playwright install chromium`. Without them the browser tests are skipped with a notice (set `CC_REQUIRE_BROWSER=1` to fail instead). The tests stub GitHub with Playwright routes, so they never touch the network.

## Publishing

`scripts/build_pages.sh` copies only `index.html`, `css/`, `js/` and an optional `assets/` to `/control-center/` on the site and rejects tests and fixtures. Everything the page needs lives in those paths and all URLs are relative, because the site is served under a path prefix.
