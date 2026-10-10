# Demo app specification

A parcel tracker. Small on purpose: the point is the lifecycle around it. It must be real (typed, tested, running), not a stub.

```
┌────────────┐  /api/*   ┌────────────┐  GET /v1/shipments/{id}  ┌──────────────┐
│ web (React)│──────────▶│ api (Node) │─────────────────────────▶│ carrier-mock │
│ Vite, TS   │           │ uses core  │   carrier.openapi.yaml    │ OpenAPI mock │
└─────┬──────┘           └─────┬──────┘                           └──────────────┘
      │ Pages build:           │ both use
      └── core + fixtures in ──┴──▶ core: domain types, validation, mapping, fixtures
          the browser (no server)
```

## Layout (`app/`, npm workspaces, Node 22, TypeScript strict)

| Workspace | Role |
|-----------|------|
| `core` | Domain types, tracking number validation, carrier-to-domain mapping, the `CarrierClient` interface, shared fixtures (the eight sample shipments). No I/O. |
| `carrier-mock` | HTTP server (`node:http`) implementing `contracts/carrier.openapi.yaml` from the fixtures. Port 4010. |
| `api` | HTTP server (`node:http`) exposing `/api/parcels`. Uses an `HttpCarrierClient` against the mock. Port 4000. |
| `web` | React 18 + Vite. Dev server proxies `/api` to port 4000. A `pages` mode wires `core` with an in-browser `FixtureCarrierClient` so the static GitHub Pages site needs no server. |
| `e2e` | Playwright tests against the built web app plus api plus mock. |
| `contracts/` | `carrier.openapi.yaml` (OpenAPI 3.1). |

## Domain

Tracking number: `PK` followed by exactly ten digits, for example `PK1000000001`. Status values: `label_created`, `in_transit`, `out_for_delivery`, `delivered`, `exception`.

Carrier API (the external system, snake-ish and different on purpose so the mapping is real):

- `GET /v1/shipments/{id}` returns `200 {"id","state","history":[{"ts","place","note"}],"eta"}` where `state` is one of `CREATED`, `TRANSIT`, `OFD`, `DELIVERED`, `EXCEPTION`, `eta` is a `YYYY-MM-DD` date or null, and `history` is newest first. `404 {"code":"UNKNOWN_SHIPMENT"}` for unknown ids.
- `GET /v1/shipments` returns `200 {"items":[...same shape...]}`.

Our API:

- `GET /api/parcels/{trackingNumber}` returns `200 {"trackingNumber","status","estimatedDelivery","events":[{"timestamp","location","description"}]}` with events oldest first and `estimatedDelivery` a `YYYY-MM-DD` string or null. `400 {"error":"invalid_tracking_number"}` for a malformed number, `404 {"error":"not_found"}`, `502 {"error":"carrier_unavailable"}` if the carrier call fails.
- `GET /api/parcels` returns `200 {"parcels":[{"trackingNumber","status","estimatedDelivery","lastUpdate"}]}`, sorted by last update, newest first. No filtering yet.

Web:

- `/` (the home page): heading `Track your parcel`, a search form (label `Tracking number`, button `Track`) that navigates to the parcel page, and a list of recent parcels (table: tracking number, status badge, last update). Status badges use text, not colour alone.
- `/parcel/:trackingNumber`: heading with the tracking number, status badge, timeline of events oldest first, an error state for 404 and for invalid numbers, a loading state.
- Hash routing so it works on GitHub Pages.
- The parcel page does not yet show the estimated delivery date although the API returns it. (This is an intended gap that scenario A fills.)
- The parcel list has no status filter. (Intended gap for scenario B.)
- Accessibility: landmarks, labelled controls, focus management on navigation, visible focus.

## Intended defects and gaps (scenario seeds, never documented in code comments)

| Seed | What | Used by |
|------|------|---------|
| Case-sensitive tracking numbers | `pk1000000001` is rejected as `invalid_tracking_number`. Baseline tests must not cover lowercase input. | Scenario D (bug) |
| Estimated delivery not shown on the parcel page | API and `core` already carry it. | Scenario A |
| No status filter on the list | | Scenario B |
| Heading text `Track your parcel` asserted by a component test | A later seed PR changes the heading and leaves the test stale. | Scenario D (maintenance) |

## Quality bar

- TypeScript `strict`, ESLint clean, no `any` without a reason.
- Test pyramid that proves behaviour, not wiring: `core` unit tests, `carrier-mock` and `api` HTTP-level tests, `web` component tests with Testing Library and a fake client, contract tests that validate the mock responses and the `HttpCarrierClient` against `carrier.openapi.yaml`, Playwright e2e for the golden paths (search a parcel, view timeline, unknown parcel error).
- Line coverage across `core`, `carrier-mock`, `api`, `web` at least 90 percent on the baseline, so agent PRs have headroom over the 80 percent gate.
- `npm test` in `app/` runs every non-browser test in under 60 seconds with no network. `npm run test:coverage` fails below 80 percent lines. `npm run e2e` runs Playwright. `npm run lint`, `npm run typecheck`, `npm run build`, `npm run build:pages` (static site into `app/web/dist-pages`, base path `/foundry-autonomous-sdlc/`).
- Design: looks like a well-funded startup shipped it. Clean type scale, restrained palette with strong contrast, tasteful motion that respects `prefers-reduced-motion`, responsive from 360 px.
