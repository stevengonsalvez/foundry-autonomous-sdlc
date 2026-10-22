---
scenario: d
title: Parcel API returns 404 for a tracking number URL with a trailing slash
type: bug
---
## What happens

The parcel lookup API answers `404 {"error":"not_found"}` when the URL has a trailing slash. Many HTTP clients and link builders add one, so a valid parcel looks like it does not exist.

## Steps to reproduce

1. Call `GET /api/parcels/PK1000000001`. It returns `200` with the parcel.
2. Call `GET /api/parcels/PK1000000001/` (the same URL with a trailing slash). It returns `404 {"error":"not_found"}`.
3. Call `GET /api/parcels/` (the list URL with a trailing slash). It also returns `404`.

## Expected

A single trailing slash is accepted, so step 2 returns the same `200` parcel as step 1 and step 3 returns the same list as `GET /api/parcels`. Everything else is unchanged: unknown paths such as `/api/shipments` and `/api/shipments/` still return `404 {"error":"not_found"}`, a tracking number that is invalid still returns `400`, and non-GET methods still return `405` with an `Allow: GET` header.

## Impact

Integrations that add a trailing slash fail for a parcel that exists.

## Scope

`app/api` only. No web or core changes.
