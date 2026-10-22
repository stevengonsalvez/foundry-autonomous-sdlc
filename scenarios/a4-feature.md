---
scenario: a
title: Show where the parcel was last seen on the parcel page
type: feature
---
## Context

Recipients want to know where their parcel is, not only when it was last updated. Every timeline event already carries a location, but the newest one is only visible by reading the whole history.

## User story

As a parcel recipient, I want to see where my parcel was last seen, so that I know its position at a glance.

## Acceptance criteria

1. The parcel page shows the text `Last seen: Manchester Hub` directly below the `Last updated` line, using the location of the newest event. The newest event is the one with the latest timestamp, regardless of the order the events arrive in.
2. When the parcel has no events, the line is not shown and the page does not display `null`, `undefined` or an empty `Last seen:`.
3. When the newest event has an empty location, the line is not shown.
4. The line is a real text node inside the parcel summary region, readable by a screen reader in reading order.
5. Existing behaviour (timeline, loading state, error states, the `Last updated` line) is unchanged.

## Scope

Web only (`app/web`). No API or carrier changes: the events are already returned.

## Out of scope

Maps, geocoding, and other languages.
