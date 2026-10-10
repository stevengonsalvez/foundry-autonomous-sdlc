---
scenario: a
title: Show the estimated delivery date on the parcel page
type: feature
---
## Context

Recipients open a parcel page to answer one question: when will it arrive? The API already returns an `estimatedDelivery` date (`YYYY-MM-DD`, or null) for every parcel, but the parcel page does not show it, so people have to guess from the event timeline.

## User story

As a parcel recipient, I want to see the estimated delivery date on the parcel page, so that I know when to expect my parcel without reading the whole timeline.

## Acceptance criteria

1. When a parcel has an `estimatedDelivery` and its status is `label_created`, `in_transit` or `out_for_delivery`, the parcel page shows the text `Estimated delivery: Mon 12 Oct 2026` (weekday, day, short month, year, English UK format), directly below the status badge.
2. The date is formatted from the date-only value without any time zone shift: `2026-10-12` always renders as 12 Oct 2026 regardless of the viewer's time zone.
3. When the status is `delivered`, the estimated delivery line is not shown.
4. When the status is `exception`, or when `estimatedDelivery` is null, the line is not shown and the page does not display `null`, `undefined` or `Invalid Date`.
5. The date line is a real text node inside the parcel summary region, readable by a screen reader in reading order (not an image, not CSS generated content).
6. Existing behaviour (timeline, loading state, error states) is unchanged.

## Scope

Web only (`app/web`). No API or carrier changes: the data is already returned.

## Out of scope

Time of day windows, delivery date notifications, localisation to languages other than English.
