---
scenario: a
title: Show when the parcel was last updated on the parcel page
type: feature
---
## Context

Recipients want to know how fresh the information is. The parcel page shows a timeline, but the newest event is only visible by reading the whole list. The timeline already carries a timestamp for every event.

## User story

As a parcel recipient, I want to see when my parcel was last updated, so that I can tell how current the status is without reading the timeline.

## Acceptance criteria

1. The parcel page shows the text `Last updated: 10 Oct 2026, 06:42 UTC` directly below the status badge, using the timestamp of the newest event and the same date format as the timeline (day, short month, year, 24 hour time, UTC).
2. The newest event is the one with the latest timestamp, regardless of the order the events arrive in.
3. When the parcel has no events, the line is not shown and the page does not display `null`, `undefined` or `Invalid Date`.
4. The line is a real text node inside the parcel summary region, readable by a screen reader in reading order.
5. Existing behaviour (timeline, loading state, error states) is unchanged.

## Scope

Web only (`app/web`). No API or carrier changes: the events are already returned.

## Out of scope

Relative times such as "5 minutes ago", automatic refresh, and other languages.
