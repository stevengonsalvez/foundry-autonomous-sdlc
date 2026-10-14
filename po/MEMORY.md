# Persona Memory: Simulated Human

Notice: The persona command allow-list permits GitHub CLI operations (`gh issue ...`) but does not permit git commit or push operations, and resumed worktrees do not synchronize uncommitted local edits across distinct host machines. Therefore, `po/MEMORY.md` serves as a local session scratchpad. GitHub (`Roadmap item: ITEM-0NN` markers, issue state, and comments) is the authoritative source of truth for filed and completed work.

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
| 52 | Intake probe three | System intake timing validation | Closed |

---

## Escalations Handled

| Issue # | Title | Escalation Reason | Resolution |
|---------|-------|-------------------|------------|
| 45 | Move the live carrier integration to the new vendor and rotate the production keys | `escalated:not-agent-suitable` | Closed with rationale via Hat 3 (requires live vendor secrets/infrastructure outside `app/`) |
| 17 | Move the live carrier integration to the new vendor and rotate the production keys | `escalated:not-agent-suitable` | Closed with rationale via Hat 3 (requires live vendor secrets/infrastructure outside `app/`) |

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

The backlog is sequenced in `po/ROADMAP.md` (read canonically from `origin/main:po/ROADMAP.md`).
The persona tracks intake status by checking GitHub issues with `gh issue list --state all --search '"Roadmap item: ITEM-0NN" in:body'`.
A dependency counts as satisfied only when its issue is `stage:released` or `stage:merged`.
Selection policy: Pick the next unblocked item whose dependencies are completed. When fewer than 5 `todo` items remain unfiled, write a one-line request to the run log and continue intake with the remaining `todo` items without filing an issue about the roadmap.
