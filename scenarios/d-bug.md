---
scenario: d
title: Lowercase tracking numbers are rejected as invalid
type: bug
---
## What happens

Searching for a tracking number typed in lowercase shows the error "invalid tracking number", even though the same number in capitals works. People often type or paste tracking numbers from emails in lowercase, so many lookups fail for no good reason.

## Steps to reproduce

1. Open the home page.
2. Type `pk1000000001` in the Tracking number field and press Track.
3. Observe the invalid tracking number error.
4. Repeat with `PK1000000001`: the parcel page loads normally.

The API behaves the same way: `GET /api/parcels/pk1000000001` returns `400 {"error":"invalid_tracking_number"}` while `GET /api/parcels/PK1000000001` returns `200`.

## Expected

Tracking numbers are accepted case-insensitively and normalised to capitals, so `pk1000000001` shows the same parcel as `PK1000000001`. Genuinely malformed numbers (wrong prefix, wrong digit count) must still be rejected.

## Impact

Affects every user who types in lowercase. There is a workaround (retype in capitals), so the service is not down, but it causes failed lookups and support contacts.
