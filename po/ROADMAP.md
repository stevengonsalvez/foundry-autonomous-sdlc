# Product Roadmap: Parcel Tracker

This document defines the progressive enhancement roadmap for the parcel tracker application (`app/`).
It serves as the backlog for the Simulated Human product owner loop.

---

## Operating Rules for the Simulated Human

1. **Selection Policy**: When the repository is idle and within spend caps, the persona selects the NEXT `todo` item whose dependencies are all satisfied (`done` in `po/ROADMAP.md` or marked `stage:released` or `stage:merged` in GitHub issues).
2. **Issue Generation**: The persona copies the item title, user value, testable acceptance criteria, and explicit `app/` scope into the new issue, referencing the roadmap ID with marker `Roadmap item: ITEM-0NN`.
3. **Memory Tracking**: The persona records the item as `filed` in `po/MEMORY.md` with the filed issue number. The persona NEVER edits `po/ROADMAP.md` directly; updates to this roadmap occur only via merged pull requests.
4. **Roadmap Extension Logging**: When fewer than 5 `todo` items remain in this roadmap, the persona records a one-line maintainer extension request in its run log and continues intake with the remaining `todo` items without opening an issue about the roadmap.
5. **Scope Boundary**: Every item is strictly confined to `app/` (`app/core`, `app/contracts`, `app/carrier-mock`, `app/api`, `app/web`, `app/e2e`). No item may touch root configuration, workflows, or infrastructure.

---

## Roadmap Backlog

### ITEM-001: feat(web): display event location pin in parcel timeline
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, timeline, web
- **Gap Anchor**: `app/web/src/components/Timeline.tsx#L11-L21` and `app/web/src/components/Icons.tsx#L23-L59`. Timeline already renders `event.location`, `:11` has `is-latest`, and line 14 has the Latest tag. Carrier contract requires `place` with `minLength: 1`. Note that issue #72 ('current location in header') overlaps and escalated with agent error. Scope here is narrowed strictly to visual location pin iconography.
- **User Value**: Recipients can visually scan the history timeline and quickly identify scan locations.
- **Files Touched**:
  - `app/web/src/components/Timeline.tsx`
  - `app/web/src/components/Icons.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. Render a location pin icon indicator next to the location text in each timeline item.
  2. Ensure the location pin icon includes an accessible SVG title or aria-hidden attribute with visible screen-reader text.

---

### ITEM-002: feat(web): add copy shareable parcel link button
- **Status**: todo
- **Dependencies**: []
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
  1. A "Copy link" button is rendered next to the tracking number in the parcel header.
  2. Clicking the button writes the current parcel URL to the browser clipboard via navigator clipboard API.
  3. A temporary confirmation tooltip or label change appears for two seconds after successful copy.
  4. The button provides an accessible aria-label identifying the parcel tracking number.

---

### ITEM-003: feat(web): store and display recent searches in local storage
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, storage, web
- **Gap Anchor**: `app/web/src/pages/HomePage.tsx#L34` and `app/web/src/pages/ParcelPage.tsx`. Users who search for parcels lose their search history upon navigation because search terms are not saved to browser localStorage.
- **User Value**: Returning users can instantly revisit previously tracked parcels without retyping tracking numbers.
- **Files Touched**:
  - `app/web/src/pages/HomePage.tsx`
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/src/components/SearchForm.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/home-page.test.tsx`
- **Acceptance Criteria**:
  1. Successful parcel searches store the tracking number in localStorage under key recent_searches up to five unique items.
  2. The home page displays a recent searches chip list beneath the search input when items exist in localStorage.
  3. Clicking a search chip navigates immediately to that parcel page.
  4. A clear history button removes saved searches from localStorage and hides the chips.

---

### ITEM-004: feat(web): real-time search input validation with parseTrackingNumber
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ux, validation, web
- **Gap Anchor**: `app/web/src/components/SearchForm.tsx#L10-L15` and `app/core/src/tracking-number.ts#L3-L7`. Form checks only non-empty string and does not validate against parseTrackingNumber before submission. Core accepts case-insensitive input via regex /^PK\d{10}$/i.
- **User Value**: Users get immediate feedback about invalid tracking number patterns before form submission, reducing failed lookups.
- **Files Touched**:
  - `app/web/src/components/SearchForm.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/home-page.test.tsx`
- **Acceptance Criteria**:
  1. Validate the search input with parseTrackingNumber from @parcel/core case-insensitively before submitting.
  2. If the value does not parse as a valid tracking number, display an inline error message stating tracking numbers start with PK followed by ten digits.
  3. Prevent form submission and navigation when input validation fails.

---

### ITEM-006: feat(web): keyboard navigation and focus management improvements
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: accessibility, a11y, web
- **Gap Anchor**: `app/web/src/components/SearchForm.tsx` and `app/e2e/tests/parcel-tracking.spec.ts`. Pressing Escape inside search inputs does not reset focus, and tab order lacks Playwright regression verification.
- **User Value**: Keyboard-only users and screen-reader users can smoothly navigate through parcel details and tables without losing focus.
- **Files Touched**:
  - `app/web/src/components/SearchForm.tsx`
  - `app/web/src/styles.css`
  - `app/e2e/tests/parcel-tracking.spec.ts`
- **Acceptance Criteria**:
  1. Focus target on parcel load moves to parcel page main heading `<h1>` (tracking number) rather than remaining on body.
  2. Pressing the Escape key while focused inside the search form input clears any active error and resets focus cleanly.
  3. Playwright test verifies that pressing Tab navigates in logical order from skip link to brand to search input to submit button.
  4. Ensure all interactive table links and navigation controls remain reachable by keyboard tab navigation alone.

---

### ITEM-007: feat(web): accessible live region announcement on parcel load
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: accessibility, a11y, web
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L73-L85`. Dynamic parcel details resolution does not announce status updates to assistive technologies upon completion.
- **User Value**: Visually impaired users using screen readers receive immediate audible notification when parcel data finishes loading.
- **Files Touched**:
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. Render an aria-live polite region on ParcelPage that announces status upon successful parcel data load.
  2. Announcement text includes the tracking number and the current human-readable status label.
  3. Live announcement container is visually hidden from DOM presentation while accessible to screen readers.

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
  1. A theme toggle button with sun and moon icon is added to the site header in App.tsx.
  2. Toggle switches between data-theme="light" and data-theme="dark" on the root document element.
  3. User selection is persisted in localStorage under key parcel_theme.
  4. Dark mode defines high-contrast tokens with dark background, dark surface, and light text.
  5. Default theme respects system prefers-color-scheme media query if no local preference is saved.

---

### ITEM-009: feat(web): multi-parcel watchlist table in local storage
- **Status**: todo
- **Dependencies**: [ITEM-003]
- **Cost Class**: M
- **Tags**: ui, storage, web
- **Gap Anchor**: `app/web/src/pages/HomePage.tsx#L37-L75` and `app/web/src/pages/ParcelPage.tsx`. Home page only lists server-wide parcels and cannot maintain a personalized watchlist of tracked parcels.
- **User Value**: Users managing multiple deliveries can pin and monitor their specific packages in a unified watchlist.
- **Files Touched**:
  - `app/web/src/pages/HomePage.tsx`
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/src/components/ParcelTable.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/home-page.test.tsx`
- **Acceptance Criteria**:
  1. Each parcel row and parcel header includes a pin to watchlist toggle button.
  2. Pinned parcel numbers are stored in localStorage under key parcel_watchlist.
  3. The home page displays a dedicated My Watchlist section when at least one parcel is pinned.
  4. Users can remove a parcel from the watchlist with one click.

---

### ITEM-010: feat(core): delivery exception status details and explanations
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: domain, core, web
- **Gap Anchor**: `app/core/src/domain.ts#L6` and `app/core/src/fixtures.ts#L51,L84`. The domain defines exception status, but provides no explanation guidance. The two real fixture notes for EXCEPTION are "Held for customs documents" and "Delivery attempt failed, recipient not available".
- **User Value**: When a shipment encounters a customs hold or failed delivery attempt, recipients understand what happened and what steps to take.
- **Files Touched**:
  - `app/core/src/domain.ts`
  - `app/core/src/mapping.ts`
  - `app/core/tests/mapping.test.ts`
  - `app/web/src/components/StatusBadge.tsx`
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/tests/status-badge.test.tsx`
- **Acceptance Criteria**:
  1. Export a helper function in core mapping guidance for delivery exception notes.
  2. Provide specific explanation text for customs document holds and failed delivery attempts based on fixture notes.
  3. When parcel status is exception, ParcelPage displays the mapped guidance box below the status badge.
  4. Unit tests verify exception guidance mapping for both fixture exception scenarios.

---

### ITEM-011: feat(web): carrier support details panel on parcel page
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, support, web
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L104-L109`. Parcel page provides no carrier contact details, FAQ links, or support information for delayed packages.
- **User Value**: Users with delivery issues can quickly find carrier support hours and contact instructions.
- **Files Touched**:
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. A collapsible support card is rendered beneath the shipment history timeline.
  2. The card lists carrier support contact details and operating hours.
  3. The card toggles open and closed with accessible button controls and aria-expanded state.
  4. Print styles hide the support panel to conserve paper.

---

### ITEM-012: feat(web): milestone progress tracker bar
- **Status**: todo
- **Dependencies**: []
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
  1. Render a milestone progress element with role="progressbar", aria-valuemin="1", aria-valuemax="4", and aria-valuenow="N".
  2. Stages cover Label Created, In Transit, Out for Delivery, and Delivered.
  3. Completed stages receive filled visual markers and active stages receive prominent focus indicators.
  4. If status is exception, progress progression halts at the exception stage with warning badge styling and accessible exception state label.

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
  1. Define string translation dictionaries for English and Spanish covering all page headings, form labels, and status badges.
  2. Add an accessible language toggle in the header or footer switching between English and Spanish.
  3. Status labels translate accurately including in transit to En transito and delivered to Entregado.
  4. Persist language choice in localStorage under key parcel_locale with English as default.

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
  1. GET endpoints compute and return an ETag header based on shipment payload content.
  2. If an incoming request includes matching If-None-Match header, return HTTP 304 with empty body.
  3. For non-terminal parcels (in_transit, out_for_delivery), set Cache-Control to 'private, max-age=30'.
  4. Unit tests in api.test.ts verify 304 responses and header generation.

---

### ITEM-016: feat(api): pagination parameters for parcel listings
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: M
- **Tags**: api, pagination, backend
- **Gap Anchor**: `app/api/src/server.ts#L60` and `app/web/src/http-parcel-service.ts#L24-L28`. Endpoint returns all parcels without limit or offset. Default when limit is omitted must remain unbounded so existing clients receive all parcels.
- **User Value**: API consumers can query parcels in smaller pages, improving response times and network overhead as shipments grow.
- **Files Touched**:
  - `app/api/src/server.ts`
  - `app/core/src/service.ts`
  - `app/web/src/http-parcel-service.ts`
  - `app/api/tests/api.test.ts`
- **Acceptance Criteria**:
  1. Support optional limit and offset query parameters on GET /api/parcels endpoint.
  2. When limit query parameter is omitted, default behavior remains unbounded and returns all parcel summaries.
  3. When limit and offset are provided, response returns sliced parcel summaries along with total count metadata.
  4. Non-numeric or negative pagination parameters return HTTP 400 with invalid_pagination_parameters error code.

---

### ITEM-018: feat(e2e): end-to-end tests for status filtering and search validation
- **Status**: todo
- **Dependencies**: [ITEM-004]
- **Cost Class**: S
- **Tags**: e2e, playwright, testing
- **Gap Anchor**: `app/e2e/tests/parcel-tracking.spec.ts` and `app/web/src/router.ts#L43`. E2E suite verifies basic navigation but lacks coverage for status filter dropdown interactions and search validation errors. URL hash format is `#/?status=delivered`.
- **User Value**: Automated regression protection for core user search and filtering journeys.
- **Files Touched**:
  - `app/e2e/tests/parcel-tracking.spec.ts`
- **Acceptance Criteria**:
  1. Playwright test verifies selecting delivered status filter displays only delivered parcels and updates hash to #/?status=delivered.
  2. Playwright test verifies selecting All statuses restores the complete parcel list.
  3. Playwright test verifies submitting invalid tracking number displays inline validation error and prevents page navigation.

---

### ITEM-019: feat(web): relative time formatting helper for updates and timeline events
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: format, ux, web
- **Gap Anchor**: `app/web/src/format.ts#L1-L15`. Format utility only outputs absolute date-times like "Oct 14, 2026, 12:00 UTC" without human-friendly relative offsets.
- **User Value**: Users can immediately see how recently a scan occurred such as "15 minutes ago" or "Yesterday".
- **Files Touched**:
  - `app/web/src/format.ts`
  - `app/web/src/components/ParcelTable.tsx`
  - `app/web/src/components/Timeline.tsx`
  - `app/web/tests/format.test.ts`
- **Acceptance Criteria**:
  1. Add formatRelativeTime helper in format.ts returning friendly relative strings such as just now, minutes ago, hours ago, or yesterday.
  2. Keep absolute timestamp visible in timeline and update text ('10 Oct 2026, 06:42 UTC') and append relative time beside it or in title attribute.
  3. Use vi.useFakeTimers in unit tests to guarantee deterministic relative time calculations.
  4. Display relative elapsed time in title tooltip on parcel table last update cells.

---

### ITEM-020: feat(web): estimated delivery countdown badge on parcel page
- **Status**: todo
- **Dependencies**: [ITEM-019]
- **Cost Class**: S
- **Tags**: ui, eta, web
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L96-L99`. Estimated delivery date renders as static date without a countdown badge such as "Arriving tomorrow" or "Arriving in 2 days".
- **User Value**: Recipients can quickly digest how soon their parcel will arrive without calculating dates mentally.
- **Files Touched**:
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/src/format.ts`
  - `app/web/src/styles.css`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. When parcel has estimated delivery date and active status, display countdown badge indicating days remaining.
  2. If delivery date is in the past and status is not delivered, display delivery delayed indicator.
  3. If status is delivered, omit the countdown badge.
  4. Ensure countdown badge text meets accessible contrast standards and includes screen-reader description.

---

### ITEM-021: feat(web): manual refresh button with polling indicator on parcel detail page
- **Status**: todo
- **Dependencies**: []
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
  1. Render a refresh button with reload icon in the parcel page header.
  2. Clicking refresh re-executes service getParcel without resetting page scroll position.
  3. During refresh, the icon animates with CSS spin class and the button disables to prevent duplicate submissions.
  4. Live region announces refresh in progress and refresh complete to screen readers.

---

### ITEM-023: feat(web): print stylesheet optimization for parcel tracking summary
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: css, print, web
- **Gap Anchor**: `app/web/src/styles.css#L43`. Theme defines `color-scheme: light;`, but stylesheet lacks `@media print` rules, causing screen layout elements (navigation links, buttons, search input) to print wastefully.
- **User Value**: Users can print clean physical delivery receipts or save them as tidy PDF summaries.
- **Files Touched**:
  - `app/web/src/styles.css`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. Add `@media print` section hiding interactive screen controls like `.back-link` and action buttons.
  2. Ensure tracking number header, shipment status, and timeline event list print with high-contrast text on white backgrounds.
  3. Prevent page breaks inside timeline event entries during printing.

---

### ITEM-024: feat(web): bundle size budget check and vendor chunk splitting in Vite
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
  1. Configure manual chunk splitting in vite.config.ts to isolate React and React DOM vendor dependencies into a dedicated vendor chunk.
  2. Configure build warning threshold and add an automated test in vite-config.test.ts asserting vendor chunking and size rules.
  3. Running web package build produces clean chunk output within budgeted size targets.

---

### ITEM-025: feat(web): estimated delivery date column in recent parcels table
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, table, web
- **Gap Anchor**: `app/web/src/components/ParcelTable.tsx#L11-L13` and `app/core/src/domain.ts#L32`. Table only renders Tracking number, Status, and Last update, omitting Estimated Delivery even though ParcelSummary carries it.
- **User Value**: Users reviewing the recent parcels table can see delivery dates without opening each parcel record individually.
- **Files Touched**:
  - `app/web/src/components/ParcelTable.tsx`
  - `app/web/src/pages/HomePage.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/home-page.test.tsx`
- **Acceptance Criteria**:
  1. Add an Estimated delivery column header between Status and Last update in ParcelTable.
  2. Render formatted estimated delivery date in table rows or N/A when estimatedDelivery is null.
  3. Update mobile responsive table view to format the new column cleanly with data-label attribute.
  4. Update component tests for ParcelTable and HomePage to verify the new column renders correctly.
