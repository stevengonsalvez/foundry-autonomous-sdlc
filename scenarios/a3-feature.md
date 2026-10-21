---
scenario: a
title: Show how many shipment events a parcel has next to the history heading
type: feature
---
## Context

Recipients scanning the parcel page cannot tell how long the shipment history is without scrolling the whole timeline. The page already has the list of events.

## User story

As a parcel recipient, I want to see how many events are in my shipment history, so that I can tell at a glance how much has happened.

## Acceptance criteria

1. The `Shipment history` heading on the parcel page is followed by the event count in parentheses, for example `Shipment history (3)` when the parcel has three events.
2. With exactly one event the heading reads `Shipment history (1)`.
3. When the parcel has no events the count is not shown and the heading stays `Shipment history`.
4. The count is part of the heading's text node, so a screen reader reads it with the heading, and the heading keeps its `id` and its link to the timeline.
5. Existing behaviour (timeline, loading state, error states) is unchanged.

## Scope

Web only (`app/web`). No API or carrier changes: the events are already returned.

## Out of scope

Pagination, filtering, and other languages.
