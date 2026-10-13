# Persona Memory: Simulated Human

This document maintains persistent memory across scheduled runs.
The persona updates this file at the conclusion of each execution cycle to ensure it never repeats filed issues, maintains a coherent product roadmap, and tracks rejected proposals.

---

## Themes Covered

- Parcel Tracking Timeline: Display of events, counts, and status badges on web and API.
- Estimated Delivery: Date calculation and UK English date rendering on parcel details.
- Event Count Presentation: Screen-reader accessible event counter on parcel header.
- Continuous Deployment and Rollback: Smoke testing and soak verification for web releases.
- Control Center Visibility: Real-time board, cost gap monitoring, and escalation queue views.

---

## Issues Filed and History

| Issue # | Title | Motivation / Gap Linked | Outcome |
|---------|-------|--------------------------|---------|
| 51 | feat: Show how many tracking events a parcel has | Missing event count in parcel header (`app/web`) | Merged in PR #54, released in v0.4.0 |
| 52 | feat: Timing intake probe three | System intake timing validation | Closed |

---

## Ideas Rejected (Do Not File)

1. **Multi-select status filter on home page**:
   - Rejected reason: Out of scope for demo simplicity; parcel tracker home page status filter is strictly single-select per product architecture.
2. **Real-time SMS / Push notifications for carrier updates**:
   - Rejected reason: Requires third-party vendor credentials, external webhooks, and production secrets, making it infeasible for autonomous agents (`escalated:not-agent-suitable`).
3. **Re-releasing rolled-back builds without code fixes**:
   - Rejected reason: Violates CD rollback guardrail; fixes must come through a new passing PR.
4. **Raising cost caps or overriding 22 USD halt limit**:
   - Rejected reason: Strictly forbidden by spend guardrails; cost overruns must park or close work instead.

---

## Planned Themes and Gap Candidates

Candidates identified from real gaps in repository and control center:

1. **Parcel timeline event location tag**:
   - Gap: Carrier openapi contract (`app/contracts/carrier.openapi.yaml`) returns `location` string for events, but web timeline only renders `description` and `timestamp`.
   - Priority: High (feature candidate when repository is idle).
2. **Control Center rollback badge on ticket detail**:
   - Gap: When CD rollback flags `escalated:deploy-failed`, ticket detail view in `apps/control-center/js/ticket.js` shows general escalation but does not link to the failed CD run URL.
   - Priority: Medium.
3. **Carrier mock exception status simulation**:
   - Gap: Scenario tests have `label_created`, `in_transit`, `delivered`, but lack explicit contract tests for `exception` events.
   - Priority: Low.
