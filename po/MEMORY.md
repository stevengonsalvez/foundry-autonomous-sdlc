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
| 72 | feat(web): show current location in parcel header | Missing current location display in parcel header (`app/web`) | Created (#72) / Intake in progress |
| 51 | feat: Show how many tracking events a parcel has | Missing event count in parcel header (`app/web`) | Merged in PR #54, released in v0.4.0 |
| 52 | feat: Timing intake probe three | System intake timing validation | Closed |
| 45 | Move the live carrier integration to the new vendor and rotate the production keys | Escalated `not-agent-suitable` (requires live vendor secrets/infrastructure) | Closed with rationale via Hat 3 (Escalation Owner) |
| 17 | Move the live carrier integration to the new vendor and rotate the production keys | Escalated `not-agent-suitable` (requires live vendor secrets/infrastructure) | Closed with rationale via Hat 3 (Escalation Owner) |

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
5. **Live carrier integration migration & production secret rotation (#17, #45)**:
   - Rejected reason: Requires external vendor contracts, production credentials/secrets, and manual DNS/firewall changes outside `app/`, violating agent feasibility (`escalated:not-agent-suitable`). Autonomous development must use carrier mock contracts.

---

## Product Roadmap Progression

The backlog is sequenced in `po/ROADMAP.md` (25 items). The persona tracks the intake status of roadmap items here:
- `ITEM-001` through `ITEM-025`: Backlog active in `po/ROADMAP.md`.
- Next eligible item by dependency order: `ITEM-001` (`feat(web): display event location and icons in parcel timeline`).
- Selection policy: Pick the next unblocked item whose dependencies are completed; when fewer than 5 `todo` items remain, file `roadmap: extend po/ROADMAP.md` with label `needs-maintainer`.

---

## Run Log

### Run: 2026-10-14T07:39:00Z
- **Precheck Evaluation**: `RUN: pipeline idle, spend within budget (13.5985 USD <= 18.00 USD), daily issues 0/6`
- **Repository State**: Billed spend 13.5985 USD (under 18.00 USD cap). Pipeline idle (0 open issues, 0 issues building or in-review, 0 active escalations). Daily issue count: 0/6 in preceding 24h.
- **Active Hats**:
  - Hat 1 (Requirements Answerer): Inactive (no issues needing refinement).
  - Hat 2 (Triage Lead): Inactive (no untriaged bugs).
  - Hat 3 (Escalation Owner): Inactive (no open escalations).
  - Hat 4 (Product Owner): Applied (repository verified idle, spend under cap, daily cap not reached).
- **Actions Executed**:
  - Verified idle pipeline via precheck and open issue inspection.
  - Identified gap in `app/web/src/pages/ParcelPage.tsx`: recipients cannot see the current/latest location of their parcel in the header without scanning down the shipment history timeline, even though `Parcel.events` includes `location` data from `app/core/src/mapping.ts`.
  - Filed issue #72: `feat(web): show current location in parcel header` with header `### Simulated human (antigravity)`, user story, testable acceptance criteria, explicit bounds (`app/web`), and out-of-scope boundaries.
  - Attempted adding `simulated-human` label via `gh issue edit 72 --add-label "simulated-human"` (label not yet created in repository label taxonomy).
- **Outcome**: Created exactly one new feature issue (#72) to advance the autonomous loop. Zero PRs opened, approved, or merged. Spend caps strictly preserved.

### Run: 2026-10-14T04:05:00Z
- **Precheck Evaluation**: `RUN: open escalation needs response (#45 escalated:not-agent-suitable), spend within budget (13.5613 USD <= 18.00 USD)`
- **Repository State**: Billed spend 13.5613 USD (under 18.00 USD cap). Pipeline not building or in-review. Open escalations detected on issues #45 and #17.
- **Active Hats**:
  - Hat 3 (Escalation Owner): Applied.
  - Hat 1 (Requirements Answerer): Inactive (no `stage:needs-refinement` issues).
  - Hat 2 (Triage Lead): Inactive (no untriaged bugs).
  - Hat 4 (Product Owner): Skipped (precheck indicated open escalations requiring response; not idle).
- **Actions Executed**:
  - Issue #45: Posted comment with header `### Simulated human (antigravity)` stating external operational scope rationale. Closed issue #45.
  - Issue #17: Posted comment with header `### Simulated human (antigravity)` stating external operational scope rationale. Closed issue #17.
- **Outcome**: All active escalations resolved. Repository now idle with 0 open issues. Spend caps preserved.
