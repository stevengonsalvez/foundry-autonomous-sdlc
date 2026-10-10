# Parcel tracker

A small parcel tracking app: search a tracking number, read the shipment timeline, browse recent parcels. It is a real, typed and tested application (React, Node, TypeScript strict) and it is the codebase the autonomous SDLC in the repository root works on.

```
┌────────────┐  /api/*   ┌────────────┐  GET /v1/shipments/{id}  ┌──────────────┐
│ web (React)│──────────▶│ api (Node) │─────────────────────────▶│ carrier-mock │
│ Vite, TS   │           │ uses core  │   carrier.openapi.yaml    │ OpenAPI mock │
└─────┬──────┘           └─────┬──────┘                           └──────────────┘
      │ Pages build:           │ both use
      └── core + fixtures in ──┴──▶ core: domain types, validation, mapping, fixtures
          the browser (no server)
```

## Layout

| Workspace | Role | Port |
|-----------|------|------|
| `core` | Domain types, tracking number validation, carrier-to-domain mapping, the `CarrierClient` and `ParcelService` interfaces, the eight sample shipments. No I/O. | none |
| `contracts` | `carrier.openapi.yaml` (OpenAPI 3.1) and a JSON Schema based validator used by contract tests. | none |
| `carrier-mock` | `node:http` server implementing the carrier contract from the sample shipments. | 4010 |
| `api` | `node:http` server exposing `/api/parcels` through an `HttpCarrierClient`. | 4000 |
| `web` | React 18 and Vite. Dev and preview servers proxy `/api` to the API. | 5173 dev, 4173 preview |
| `e2e` | Playwright tests against the built web app, the API and the mock. | none |

The tracking number format is `PK` followed by exactly ten digits, for example `PK1000000001`. The sample shipments are `PK1000000001` to `PK1000000008` and cover every status.

## Requirements

Node 22.12 or newer and npm. Everything is pinned to exact versions in `package-lock.json`.

```sh
npm ci
```

## Run it

```sh
npm run dev
```

starts the carrier mock, the API and the Vite dev server together, then open http://localhost:5173. To run them separately: `npm run start --workspace @parcel/carrier-mock`, `npm run start --workspace @parcel/api` (reads `PORT` and `CARRIER_URL`), `npm run dev --workspace @parcel/web` (reads `API_URL`).

API:

```sh
curl http://127.0.0.1:4000/api/parcels
curl http://127.0.0.1:4000/api/parcels/PK1000000001
```

## npm scripts (run from `app/`)

| Script | What it does |
|--------|--------------|
| `npm run dev` | Mock, API and Vite dev server together. |
| `npm run lint` | ESLint (typescript-eslint, react-hooks, jsx-a11y) over every workspace. |
| `npm run typecheck` | `tsc --noEmit` in every workspace, strict mode. |
| `npm test` | Every non-browser test (core, contracts, carrier-mock, api, web) with Vitest. No network, a few seconds. |
| `npm run test:coverage` | Same tests with V8 coverage over `core`, `carrier-mock`, `api` and `web`. Fails below 80 percent lines. Writes `coverage/` (text, `coverage-summary.json`, `lcov.info`). |
| `npm run build` | Type checks and builds the web app into `web/dist`. |
| `npm run build:pages` | Static build into `web/dist-pages` with base path `/foundry-autonomous-sdlc/`. It wires `core` with an in-browser `FixtureCarrierClient`, so no server is needed. |
| `npm run e2e` | Playwright (Chromium). Starts the mock, the API and the built web app itself, then runs the golden paths and an accessibility check. |

Install the browser once with `npx playwright install chromium`. The e2e ports default to 4010, 4000 and 4173 and can be moved with `MOCK_PORT`, `API_PORT` and `WEB_PORT`. Servers are never reused, so a busy port fails loudly.

To check the Pages build the way GitHub Pages serves it, serve `web/dist-pages` under `/foundry-autonomous-sdlc/` and open `/foundry-autonomous-sdlc/` (routing uses the URL hash, so deep links work).

## Where tests live

| Kind | Location | Notes |
|------|----------|-------|
| Unit | `core/tests` | Validation, mapping, the service, fixtures. |
| HTTP level | `carrier-mock/tests`, `api/tests` | Real HTTP against ephemeral ports. |
| Contract | `carrier-mock/tests`, `api/tests/http-carrier-client.test.ts` | Real responses and the `HttpCarrierClient` exchanges validated against `contracts/carrier.openapi.yaml`. |
| Component | `web/tests` | Testing Library with a fake service. |
| End to end | `e2e/tests` | Playwright. |

## The carrier contract

`contracts/carrier.openapi.yaml` is the source of truth for the external carrier. Its field names (`state`, `history`, `ts`, `place`, `note`, `eta`) and state codes (`CREATED`, `TRANSIT`, `OFD`, `DELIVERED`, `EXCEPTION`) differ from the app's own model on purpose, so `core` has a real mapping layer. Change the contract first, then the mock, then the client.
