# Product Roadmap: Parcel Tracker

This document defines the progressive enhancement roadmap for the parcel tracker application (`app/`).
It serves as the backlog for the Simulated Human product owner loop.

---

## Operating Rules for the Simulated Human

1. **Selection Policy**: When the repository is idle and within spend caps, the persona selects the NEXT `todo` item whose dependencies are all satisfied (`done` or `filed`).
2. **Issue Generation**: The persona copies the item title, user value, testable acceptance criteria, and explicit `app/` scope into the new issue, referencing the roadmap ID.
3. **Memory Tracking**: The persona marks the item as `filed` in `po/MEMORY.md` with the filed issue number. The persona NEVER edits `po/ROADMAP.md` directly; updates to this roadmap occur only via merged pull requests.
4. **Maintainer Escalation**: When fewer than 5 `todo` items remain in this roadmap, the persona files ONE issue titled `roadmap: extend po/ROADMAP.md` carrying label `needs-maintainer` and pauses new feature intake.
5. **Scope Boundary**: Every item is strictly confined to `app/` (`app/core`, `app/contracts`, `app/carrier-mock`, `app/api`, `app/web`, `app/e2e`). No item may touch root configuration, workflows, or infrastructure.

---

## Roadmap Backlog

### ITEM-001: feat(web): display event location and icons in parcel timeline
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, timeline, web
- **Gap Anchor**: `app/web/src/components/Timeline.tsx#L12-L21` and `app/contracts/carrier.openapi.yaml#L63`. Carrier provides `place` mapped to `ParcelEvent.location` in `app/core/src/mapping.ts#L18`, but timeline renders plain text without distinct icon badges.
- **User Value**: Recipients can visually scan the history timeline and quickly identify event types and scan locations.
- **Files Touched**:
  - `app/web/src/components/Timeline.tsx`
  - `app/web/src/components/Icons.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. Each timeline item renders a location pin indicator next to `event.location` when location is non-empty.
  2. When `event.location` is empty or undefined, no empty location tag or broken icon is rendered.
  3. The latest event visually distinguishes its status icon from past events.
  4. All icons include accessible SVG titles or aria-hidden attributes with visible screen-reader text.

---

### ITEM-002: feat(web): add copy shareable parcel link button
- **Status**: todo
- **Dependencies**: [ITEM-001]
- **Cost Class**: S
- **Tags**: ui, sharing, web
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L73-L80`. The parcel header displays the tracking number but provides no one-click copy button for sharing the parcel link.
- **User Value**: Recipients can easily copy a direct link to their parcel tracking page to share with family or support agents.
- **Files Touched**:
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/src/components/Icons.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. A "Copy link" button is rendered next to the tracking number in `app/web/src/pages/ParcelPage.tsx`.
  2. Clicking the button writes the current parcel URL (including hash route) to the browser clipboard via `navigator.clipboard.writeText`.
  3. A temporary confirmation tooltip or label change ("Copied!") appears for 2 seconds after successful copy.
  4. The button has `aria-label="Copy shareable link for parcel <trackingNumber>"`.

---

### ITEM-003: feat(web): store and display recent searches in local storage
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, storage, web
- **Gap Anchor**: `app/web/src/pages/HomePage.tsx#L34`. Users who search for parcels lose their search history upon navigation because search terms are not saved to browser localStorage.
- **User Value**: Returning users can instantly revisit previously tracked parcels without retyping tracking numbers.
- **Files Touched**:
  - `app/web/src/pages/HomePage.tsx`
  - `app/web/src/components/SearchForm.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/home-page.test.tsx`
- **Acceptance Criteria**:
  1. Successful parcel searches store the tracking number in `localStorage` under key `recent_searches` (up to 5 unique items).
  2. The home page displays a "Recent searches" chip list beneath the search input when items exist in localStorage.
  3. Clicking a search chip navigates immediately to that parcel page.
  4. A "Clear history" button clears the saved searches from localStorage and removes the chips.

---

### ITEM-004: feat(web): real-time search input format validation with helpful error messages
- **Status**: todo
- **Dependencies**: [ITEM-003]
- **Cost Class**: S
- **Tags**: ux, validation, web
- **Gap Anchor**: `app/web/src/components/SearchForm.tsx#L10-L15`. Form only validates non-empty string and does not warn users if they enter fewer than 10 digits or invalid prefixes before submitting.
- **User Value**: Users get immediate feedback about invalid tracking number patterns before form submission, reducing failed lookups.
- **Files Touched**:
  - `app/web/src/components/SearchForm.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/home-page.test.tsx`
- **Acceptance Criteria**:
  1. Submitting a number that does not match `^PK[0-9]{10}$` displays an inline error: "Tracking numbers must begin with PK followed by 10 digits".
  2. Input automatically trims leading and trailing whitespace on submit.
  3. The error message is linked to the input via `aria-describedby="tracking-number-error"`.
  4. Entering text clears the previous validation error state.

---

### ITEM-005: feat(web): enhance empty and error states with recovery actions
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ux, feedback, web
- **Gap Anchor**: `app/web/src/components/Feedback.tsx#L4-L24` and `app/web/src/pages/NotFoundPage.tsx`. Empty states show simple plain text without guidance on what to do next.
- **User Value**: Users encountering 404s or empty parcel lists receive actionable troubleshooting steps and quick links back home.
- **Files Touched**:
  - `app/web/src/components/Feedback.tsx`
  - `app/web/src/pages/NotFoundPage.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. `ParcelNotFoundError` view displays a dedicated "Check tracking number" tip and a primary "Return to Search" button.
  2. Generic server errors provide a visible "Try again" button calling the retry callback.
  3. Empty state on `HomePage` displays a helper note explaining when carrier records typically appear.
  4. All error containers use role="alert" for assistive technology announcement.

---

### ITEM-006: feat(web): keyboard navigation and focus management improvements
- **Status**: todo
- **Dependencies**: [ITEM-005]
- **Cost Class**: S
- **Tags**: accessibility, a11y, web
- **Gap Anchor**: `app/web/src/App.tsx#L48-L50` and `app/web/src/components/ParcelTable.tsx`. Focus indicator styling in `styles.css` is minimal and table rows lack keyboard navigation shortcuts.
- **User Value**: Keyboard-only users and screen-reader users can smoothly navigate through parcel details and tables without losing focus.
- **Files Touched**:
  - `app/web/src/App.tsx`
  - `app/web/src/components/ParcelTable.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/home-page.test.tsx`
- **Acceptance Criteria**:
  1. All interactive elements (buttons, links, inputs, selects) have a prominent 2px focus ring with 2px offset.
  2. Pressing Escape while focused inside a search or filter input resets focus to the main content container.
  3. Skip link is visible on tab focus and jumps directly to `#main-content`.
  4. Tab order on `ParcelPage` flows logically: Skip link -> Brand -> Back link -> Header actions -> Timeline items.

---

### ITEM-007: feat(web): accessible ARIA live regions for tracking status updates
- **Status**: todo
- **Dependencies**: [ITEM-006]
- **Cost Class**: S
- **Tags**: accessibility, a11y, web
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L102-L109`. Dynamic loading and error states lack live region announcements.
- **User Value**: Visually impaired users using screen readers receive immediate audible notification when parcel data finishes loading.
- **Files Touched**:
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/src/components/Feedback.tsx`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. `Loading` component renders with `aria-live="polite"` and `aria-busy="true"`.
  2. When parcel data resolves successfully, status badge state is announced via an `aria-live="polite"` announcement container.
  3. Error messages use `role="alert"` with `aria-live="assertive"`.
  4. Automated accessibility check verifies zero missing label or contrast violations in the parcel header.

---

### ITEM-008: feat(web): dark mode theme toggle with persistent preference
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: M
- **Tags**: ui, theme, web
- **Gap Anchor**: `app/web/src/styles.css#L43`. The CSS hardcodes `color-scheme: light;` and light surface colors without dark mode support or user toggle.
- **User Value**: Users in low-light environments can switch to dark mode for comfortable viewing.
- **Files Touched**:
  - `app/web/src/App.tsx`
  - `app/web/src/components/Icons.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/home-page.test.tsx`
- **Acceptance Criteria**:
  1. A theme toggle button (Sun/Moon icon) is added to the site header in `App.tsx`.
  2. Toggle switches between `data-theme="light"` and `data-theme="dark"` on the root document element.
  3. User selection is persisted in `localStorage` under key `parcel_theme`.
  4. Dark mode defines high-contrast tokens: `--bg: #0f172a`, `--surface: #1e293b`, `--ink: #f8fafc`, `--line: #334155`.
  5. Default theme respects system `prefers-color-scheme: dark` media query if no local preference is saved.

---

### ITEM-009: feat(web): multi-parcel watchlist table in local storage
- **Status**: todo
- **Dependencies**: [ITEM-003]
- **Cost Class**: M
- **Tags**: ui, storage, web
- **Gap Anchor**: `app/web/src/pages/HomePage.tsx#L37-L75`. Home page only lists server-wide parcels and cannot maintain a personalized watchlist of tracked parcels.
- **User Value**: Users managing multiple deliveries can pin and monitor their specific packages in a unified watchlist.
- **Files Touched**:
  - `app/web/src/pages/HomePage.tsx`
  - `app/web/src/components/ParcelTable.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/home-page.test.tsx`
- **Acceptance Criteria**:
  1. Each parcel row and parcel header includes a "Pin to watchlist" toggle button.
  2. Pinned parcel numbers are stored in `localStorage` under `parcel_watchlist`.
  3. The home page displays a "My Watchlist" tab or section when at least one parcel is pinned.
  4. Users can remove a parcel from the watchlist with one click.

---

### ITEM-010: feat(core): delivery exception status details and explanations
- **Status**: todo
- **Dependencies**: [ITEM-001]
- **Cost Class**: S
- **Tags**: domain, core, web
- **Gap Anchor**: `app/core/src/domain.ts#L6` and `app/web/src/components/StatusBadge.tsx#L6`. The domain defines `exception` status, but the UI does not explain what an exception means or recommend customer actions.
- **User Value**: When a shipment encounters a customs hold, severe weather, or incorrect address, recipients understand what happened and what steps to take.
- **Files Touched**:
  - `app/core/src/domain.ts`
  - `app/core/src/mapping.ts`
  - `app/web/src/components/StatusBadge.tsx`
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/tests/status-badge.test.tsx`
- **Acceptance Criteria**:
  1. `app/core/src/domain.ts` exports helper `getExceptionGuidance(event: ParcelEvent): string`.
  2. When status is `exception`, `ParcelPage` renders an alert box explaining the delivery exception and suggesting next steps.
  3. Status badge for `exception` displays high-contrast warning styling (amber/red badge with accessible text).
  4. Unit tests in `core` and `web` verify exception guidance messages for weather, customs, and address hold scenarios.

---

### ITEM-011: feat(web): carrier support details panel on parcel page
- **Status**: todo
- **Dependencies**: [ITEM-010]
- **Cost Class**: S
- **Tags**: ui, support, web
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L104-L109`. Parcel page provides no carrier contact details, FAQ links, or support information for delayed packages.
- **User Value**: Users with delivery issues can quickly find carrier support hours and contact instructions.
- **Files Touched**:
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. A "Need help with this delivery?" collapsible card is rendered beneath the shipment history timeline.
  2. Card lists mock carrier support phone, operating hours (Mon-Fri 08:00 to 18:00 UTC), and a link to report a missing package.
  3. Card can be toggled open and closed with keyboard accessible button (`aria-expanded`).
  4. Print styles hide the support panel to conserve paper.

---

### ITEM-012: feat(web): milestone progress tracker bar
- **Status**: todo
- **Dependencies**: [ITEM-001]
- **Cost Class**: M
- **Tags**: ui, visualization, web
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L73-L100`. The parcel header shows status badge and date, but lacks a visual stage progression bar showing where the parcel sits in its journey.
- **User Value**: Users can immediately understand their parcel journey at a glance without reading through the raw event timestamps.
- **Files Touched**:
  - `app/web/src/components/ProgressBar.tsx`
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. A 4-step progress bar is rendered: 1. Label Created, 2. In Transit, 3. Out for Delivery, 4. Delivered.
  2. Steps up to and including the current status are marked as complete.
  3. If status is `exception`, the progress bar indicates an alert state on the active step.
  4. The component is accessible via `role="progressbar"` with `aria-valuenow` representing current stage (1 to 4).

---

### ITEM-013: feat(web): simulated delivery notifications opt-in modal
- **Status**: todo
- **Dependencies**: [ITEM-002]
- **Cost Class**: S
- **Tags**: ui, notifications, web
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L80`. Recipients have no interface to opt into delivery notifications or simulated alerts.
- **User Value**: Users can simulate setting up email or SMS alerts for milestone updates.
- **Files Touched**:
  - `app/web/src/components/NotificationModal.tsx`
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. A "Get updates" button in `ParcelPage` opens a dialog modal.
  2. Dialog contains input fields for simulated email or mobile phone and checkboxes for milestone events.
  3. Submitting the modal saves preferences to `localStorage` under `parcel_notifications_<trackingNumber>` and displays a confirmation notice.
  4. Dialog traps focus when opened, can be closed via Escape key, and restores focus to trigger button upon close.

---

### ITEM-014: feat(web): internationalization support with Spanish language dictionary
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: M
- **Tags**: i18n, localization, web
- **Gap Anchor**: `app/web/src/pages/HomePage.tsx#L31` and `app/web/src/pages/ParcelPage.tsx#L70`. All UI labels, headings, and status badges are hardcoded English strings.
- **User Value**: Spanish-speaking users can navigate and track parcels in their preferred language.
- **Files Touched**:
  - `app/web/src/i18n.ts`
  - `app/web/src/App.tsx`
  - `app/web/src/pages/HomePage.tsx`
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/src/components/StatusBadge.tsx`
  - `app/web/tests/home-page.test.tsx`
- **Acceptance Criteria**:
  1. `app/web/src/i18n.ts` defines string dictionaries for English (`en`) and Spanish (`es`).
  2. A language selector toggle (`EN | ES`) is available in the footer or header.
  3. Status labels translate accurately (e.g. `in_transit` -> `En transito`, `delivered` -> `Entregado`).
  4. Language choice is persisted in `localStorage` under `parcel_locale` and defaults to `en`.

---

### ITEM-015: feat(api): HTTP cache control and ETag validation headers
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: api, http, performance
- **Gap Anchor**: `app/api/src/server.ts#L27`. Server unconditionally sends `cache-control: no-store` on all endpoints.
- **User Value**: API clients benefit from standard caching headers and conditional `304 Not Modified` responses for unchanged parcel records.
- **Files Touched**:
  - `app/api/src/server.ts`
  - `app/api/tests/api.test.ts`
- **Acceptance Criteria**:
  1. `GET /api/parcels/:id` returns an `ETag` header generated from shipment payload hash.
  2. If request contains matching `If-None-Match`, API returns `304 Not Modified` with empty body.
  3. `Cache-Control` header is set to `public, max-age=30, must-revalidate` for completed/delivered parcels and `no-cache` for active deliveries.
  4. Unit tests in `app/api/tests/api.test.ts` verify 304 response and ETag matching.

---

### ITEM-016: feat(api): pagination parameters for parcel listings
- **Status**: todo
- **Dependencies**: [ITEM-015]
- **Cost Class**: M
- **Tags**: api, pagination, backend
- **Gap Anchor**: `app/api/src/server.ts#L60` and `app/core/src/service.ts`. Listing endpoint returns all parcels at once without limit and offset parameters.
- **User Value**: API consumers can query parcels in smaller pages, improving response times and network overhead as shipments grow.
- **Files Touched**:
  - `app/api/src/server.ts`
  - `app/core/src/service.ts`
  - `app/api/tests/api.test.ts`
- **Acceptance Criteria**:
  1. `GET /api/parcels` accepts optional `limit` (default 20, max 100) and `offset` (default 0) query parameters.
  2. Response payload format: `{"parcels": [...], "total": number, "limit": number, "offset": number}`.
  3. Non-numeric or negative pagination parameters return HTTP 400 with `{"error": "invalid_pagination_parameters"}`.
  4. Tests verify offset slicing and limit boundary conditions.

---

### ITEM-017: feat(contracts): expanded OpenAPI schema validation and negative test suite
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: contracts, testing, openapi
- **Gap Anchor**: `app/contracts/tests/contract.test.ts` and `app/contracts/carrier.openapi.yaml#L50-L52`. Existing contract tests only cover 200 OK responses with sample shipments.
- **User Value**: Prevents contract regressions by enforcing strict OpenAPI schema validation on edge-case carrier payloads.
- **Files Touched**:
  - `app/contracts/tests/contract.test.ts`
  - `app/contracts/carrier.openapi.yaml`
- **Acceptance Criteria**:
  1. Contract tests validate that invalid state strings (e.g. `UNKNOWN_STATE`) fail schema validation.
  2. Contract tests assert that timestamps in history entries strictly follow ISO 8601 date-time format.
  3. Negative test cases assert 404 response payload conforms to `UnknownShipmentError` schema.
  4. Running `npm test --workspace @parcel/contracts` executes all contract validations cleanly.

---

### ITEM-018: feat(e2e): end-to-end tests for status filtering and search validation
- **Status**: todo
- **Dependencies**: [ITEM-004]
- **Cost Class**: S
- **Tags**: e2e, playwright, testing
- **Gap Anchor**: `app/e2e/tests/parcel-tracking.spec.ts`. E2E suite verifies basic navigation but lacks coverage for status filter dropdown interactions and search validation errors.
- **User Value**: Automated regression protection for core user search and filtering journeys.
- **Files Touched**:
  - `app/e2e/tests/parcel-tracking.spec.ts`
- **Acceptance Criteria**:
  1. Test verifies selecting "delivered" filter displays only delivered parcels and updates URL hash to `#/status=delivered`.
  2. Test verifies selecting "All statuses" restores all parcel rows.
  3. Test verifies submitting invalid tracking number "PK123" displays inline error message and does not navigate.
  4. All Playwright tests pass in headless mode via `npm run test --workspace @parcel/e2e`.

---

### ITEM-019: feat(web): relative time formatting helper for updates and timeline events
- **Status**: todo
- **Dependencies**: [ITEM-001]
- **Cost Class**: S
- **Tags**: format, ux, web
- **Gap Anchor**: `app/web/src/format.ts#L1-L15`. Format utility only outputs absolute date-times like "Oct 14, 2026, 12:00 UTC" without human-friendly relative offsets.
- **User Value**: Users can immediately see how recently a scan occurred (e.g. "15 minutes ago" or "Yesterday").
- **Files Touched**:
  - `app/web/src/format.ts`
  - `app/web/src/components/ParcelTable.tsx`
  - `app/web/src/components/Timeline.tsx`
  - `app/web/tests/format.test.ts`
- **Acceptance Criteria**:
  1. `formatRelativeTime(isoString, now)` returns relative strings: "just now", "X minutes ago", "X hours ago", "yesterday", or "X days ago".
  2. Parcel table and timeline display the relative time with full ISO string inside `title` attribute for tooltip inspection.
  3. Unit tests in `app/web/tests/format.test.ts` verify all relative time interval boundaries.
  4. Handles future timestamps gracefully without negative values.

---

### ITEM-020: feat(web): estimated delivery countdown badge on parcel page
- **Status**: todo
- **Dependencies**: [ITEM-019]
- **Cost Class**: S
- **Tags**: ui, eta, web
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L96-L99`. Estimated delivery date renders as static date without a countdown badge (e.g. "Arriving tomorrow" or "Arriving in 2 days").
- **User Value**: Recipients can quickly digest how soon their parcel will arrive without calculating dates mentally.
- **Files Touched**:
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/src/format.ts`
  - `app/web/src/styles.css`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. When parcel has `estimatedDelivery` and status is active, render countdown badge: "Arriving today", "Arriving tomorrow", or "Arriving in X days".
  2. If delivery date is in the past and parcel is not delivered, badge displays "Delivery delayed".
  3. If status is `delivered`, countdown badge is omitted.
  4. Badge text has high-contrast styling and appropriate aria label.

---

### ITEM-021: feat(web): manual refresh button with polling indicator on parcel detail page
- **Status**: todo
- **Dependencies**: [ITEM-002]
- **Cost Class**: S
- **Tags**: ux, data, web
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L52`. Page fetches data once on mount; users must reload the whole browser tab to check for fresh tracking events.
- **User Value**: Recipients can refresh tracking status with one click while waiting for an out-for-delivery update.
- **Files Touched**:
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/src/components/Icons.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. A "Refresh" button with a reload icon is rendered in the parcel page header.
  2. Clicking refresh re-executes `service.getParcel(trackingNumber)` without resetting scroll position.
  3. During refresh, the icon animates with a CSS spin class and button is disabled to prevent double clicks.
  4. Screen readers announce "Refreshing parcel details" and "Parcel details updated" via live region.

---

### ITEM-022: feat(carrier-mock): simulated latency and chaos query parameters for carrier mock
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: mock, testing, chaos
- **Gap Anchor**: `app/carrier-mock/src/server.ts#L36-L51`. Carrier mock responds immediately without configurable latency or simulated 500 error modes.
- **User Value**: Enables developers and automated resilience tests to verify client behavior under slow or flaky carrier network conditions.
- **Files Touched**:
  - `app/carrier-mock/src/server.ts`
  - `app/carrier-mock/tests/carrier-mock.test.ts`
- **Acceptance Criteria**:
  1. Carrier mock inspects `?delay_ms=<number>` query param and delays HTTP response by the specified milliseconds (capped at 5000ms).
  2. Query param `?chaos=error` forces HTTP 500 response with `{"code": "CARRIER_INTERNAL_ERROR"}`.
  3. Default behavior without query params remains instant and unchanged.
  4. Unit tests in `carrier-mock.test.ts` verify delay timing and chaos error codes.

---

### ITEM-023: feat(web): print stylesheet optimization for parcel tracking summary
- **Status**: todo
- **Dependencies**: [ITEM-001]
- **Cost Class**: S
- **Tags**: css, print, web
- **Gap Anchor**: `app/web/src/styles.css`. No `@media print` rules exist, resulting in dark backgrounds, search buttons, and back links showing up on printed receipts.
- **User Value**: Users can print clean physical delivery receipts or save them as tidy PDF summaries.
- **Files Touched**:
  - `app/web/src/styles.css`
- **Acceptance Criteria**:
  1. `@media print` rules hide back links, search form, theme toggle, and refresh buttons.
  2. Page background is forced to white and text color to black for printer toner efficiency.
  3. Shipment history timeline renders in a clean single-column printable receipt format with visible borders.
  4. Page breaks inside timeline cards are prevented via `break-inside: avoid`.

---

### ITEM-024: feat(web): bundle size performance budget enforcement in Vite build
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: performance, build, vite
- **Gap Anchor**: `app/web/vite.config.ts`. Vite build lacks chunk size budgets and compression monitoring to prevent bundle regressions.
- **User Value**: Ensures the web application stays lean, loads instantly, and avoids shipping unnecessary bundle weight.
- **Files Touched**:
  - `app/web/vite.config.ts`
  - `app/web/tests/vite-config.test.ts`
- **Acceptance Criteria**:
  1. `vite.config.ts` sets `build.chunkSizeWarningLimit` to 150 (KB) for client chunks.
  2. Build configuration defines manual chunking splitting vendor dependencies (`react`, `react-dom`) into a cached vendor chunk.
  3. `app/web/tests/vite-config.test.ts` asserts that the configuration includes strict chunk limits.
  4. Running `npm run build --workspace @parcel/web` completes without chunk size warnings.

---

### ITEM-025: feat(web): estimated delivery date column in recent parcels table
- **Status**: todo
- **Dependencies**: [ITEM-003]
- **Cost Class**: S
- **Tags**: ui, table, web
- **Gap Anchor**: `app/web/src/components/ParcelTable.tsx#L9-L15` and `app/core/src/domain.ts#L32`. Table only renders Tracking number, Status, and Last update, omitting Estimated Delivery even though `ParcelSummary.estimatedDelivery` is available.
- **User Value**: Users reviewing the recent parcels table can see delivery dates without opening each parcel record individually.
- **Files Touched**:
  - `app/web/src/components/ParcelTable.tsx`
  - `app/web/src/pages/HomePage.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/home-page.test.tsx`
- **Acceptance Criteria**:
  1. `ParcelTable` header includes an "Estimated delivery" column between "Status" and "Last update".
  2. Table rows display formatted estimated delivery date (e.g. "Oct 18, 2026") or "N/A" if estimatedDelivery is null.
  3. Mobile responsive styles format the new column cleanly with matching `data-label="Estimated delivery"`.
  4. Existing unit tests for `ParcelTable` and `HomePage` are updated and pass with the new column.
