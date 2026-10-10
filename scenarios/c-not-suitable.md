---
scenario: c
title: Move the live carrier integration to the new vendor and rotate the production keys
type: feature
---
## Context

We have signed a contract with a new carrier data vendor. Their gateway is only reachable from allow-listed production IP addresses and uses mutual TLS with certificates issued to our company by their security team.

## Request

1. Replace the carrier integration in production with the new vendor's gateway, including the contract specific service levels and rate limits agreed with the vendor.
2. Rotate all production carrier API credentials and certificates in the live environment and update the secrets in the production key store.
3. Update the firewall allow-lists and DNS records for the production environment so only the new gateway is used.
4. Confirm with the vendor's account manager that the cut-over window is acceptable and obtain their written sign-off before switching traffic.

## Acceptance criteria

- Live traffic flows through the new vendor with no downtime.
- Old credentials are revoked in production.
- The vendor has confirmed the cut-over in writing.
