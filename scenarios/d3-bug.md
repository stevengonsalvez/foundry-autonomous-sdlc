---
scenario: d
title: Tracking numbers with surrounding spaces are rejected by the API
type: bug
---
## What happens

The parcel lookup API rejects a tracking number that has a space or a line break around it. People copy tracking numbers from emails and chat messages, and a stray space comes along. The web search box trims what you type, but other callers of the API do not, so they get an error for a number that is fine.

## Steps to reproduce

1. Call `GET /api/parcels/PK1000000001`. It returns `200`.
2. Call `GET /api/parcels/%20PK1000000001%20` (the same number with a space before and after). It returns `400 {"error":"invalid_tracking_number"}`.

## Expected

Leading and trailing whitespace (spaces, tabs, line breaks) around the tracking number is ignored, so step 2 returns the same `200` parcel as step 1. Numbers that are malformed once trimmed (wrong prefix, wrong digit count, spaces inside the number) must still be rejected.

## Impact

Integrations and pasted links fail for a valid number.

## Scope

`app/core` and `app/api`. No web changes.
