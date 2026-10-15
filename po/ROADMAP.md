# Product Roadmap: Parcel Tracker

This document defines the progressive enhancement roadmap for the parcel tracker application (`app/`).
It serves as the backlog for the Simulated Human product owner loop.

---

## Operating Rules for the Simulated Human

1. **Selection Policy**: When the repository is idle and within spend caps, the persona selects the NEXT unblocked `todo` item whose dependencies are all satisfied (`done` in `po/ROADMAP.md` or marked `stage:released` in GitHub issues). When multiple unblocked candidate items are ready, the persona prefers the highest-visibility ready item first.
2. **Visible Surface and UI Proof**: Every issue filed by the persona must name the visible surface it changes (`home` or `parcel page`) and include an acceptance criterion that the `ui-proof` screenshot for that surface differs from the previous release (new visible element with a stable test id or text).
3. **Issue Generation**: The persona copies the item title, visible surface, user value, testable acceptance criteria, and explicit `app/` scope into the new issue, referencing the roadmap ID with marker `Roadmap item: ITEM-0NN`.
4. **Roadmap Extension Logging**: When fewer than 5 `todo` items remain in this roadmap, the persona records a one-line maintainer extension request in its run log and continues intake with the remaining `todo` items without opening an issue about the roadmap.
5. **Scope Boundary**: Every item is strictly confined to `app/` (`app/core`, `app/contracts`, `app/carrier-mock`, `app/api`, `app/web`, `app/e2e`). No item may touch root configuration, workflows, or infrastructure.

---

## Roadmap Backlog

### ITEM-001: feat(web): display event location pin in parcel timeline
- **Status**: done
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, timeline, web
- **Visible Surface**: parcel page
- **Gap Anchor**: `app/web/src/components/Timeline.tsx#L11-L21` and `app/web/src/components/Icons.tsx#L23-L59`. Timeline already renders `event.location`, `:11` has `is-latest`, and line 14 has the Latest tag. Carrier contract requires `place` with `minLength: 1`. Note that issue #72 ('current location in header') overlaps and escalated with agent error. Scope here is narrowed strictly to visual location pin iconography.
- **User Value**: Recipients can visually scan the history timeline and quickly identify scan locations.
- **Files Touched**:
  - `app/web/src/components/Timeline.tsx`
  - `app/web/src/components/Icons.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. Each li.timeline__item .timeline__where starts with an svg[aria-hidden="true"] with location text unchanged.
  2. parcel-page.test.tsx asserts 5 pin icons and items[0] still has text Rotterdam, NL.
  3. The ui-proof screenshot for parcel page differs from previous release by showing location pin icons in the timeline.

---

### ITEM-002: feat(web): add copy shareable parcel link button
- **Status**: done
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, sharing, web
- **Visible Surface**: parcel page
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L163-L171`. The parcel header displays the tracking number but provides no one-click copy button for sharing the parcel link.
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
  5. The ui-proof screenshot for parcel page differs from previous release by showing the copy link button in the header.

---

### ITEM-003: feat(web): store and display recent searches in local storage
- **Status**: done
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, storage, web
- **Visible Surface**: home
- **Gap Anchor**: `app/web/src/pages/HomePage.tsx#L34` and `app/web/src/components/SearchForm.tsx`. Users who search for parcels lose their search history upon navigation because search terms are not saved to browser localStorage.
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
  5. The ui-proof screenshot for home surface differs from previous release by showing the recent searches chip container.

---

### ITEM-004: feat(web): redesigned home hero banner with brand identity badge and primary action button
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, hero, home, high-visibility
- **Visible Surface**: home
- **Gap Anchor**: `app/web/src/pages/HomePage.tsx#L29-L35` and `app/web/src/components/SearchForm.tsx#L57-L62`. The home hero section currently shows an unstyled heading and generic button, lacking distinctive brand identity and prominent primary action styling on the initial screen.
- **User Value**: Visitors to the home page immediately see a professional, branded parcel tracking hero with an official carrier badge and a clear primary action button.
- **Files Touched**:
  - `app/web/src/pages/HomePage.tsx`
  - `app/web/src/components/SearchForm.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/home-page.test.tsx`
- **Acceptance Criteria**:
  1. The home hero renders an official carrier identity badge with data-testid="brand-identity-badge" displaying "Official Carrier Tracking".
  2. The search submit button displays primary call-to-action text "Track shipment" with data-testid="track-shipment-button".
  3. The hero includes a dedicated tagline element with class hero__tagline highlighting live status updates.
  4. The ui-proof screenshot for home surface differs from previous release by showing the brand identity badge with test id brand-identity-badge and primary action button.

---

### ITEM-005: feat(web): parcel journey progress stepper on parcel page
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: M
- **Tags**: ui, stepper, progress, parcel-page, high-visibility
- **Visible Surface**: parcel page
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L163-L191` and `app/core/src/domain.ts#L6-L11`. The parcel header displays text status but lacks a visual milestone progress stepper showing the journey stages (Label created, In transit, Out for delivery, Delivered) at a glance.
- **User Value**: Recipients immediately understand their parcel journey stage through a prominent four-step visual stepper above the detailed timeline.
- **Files Touched**:
  - `app/web/src/components/ProgressBar.tsx`
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. Render a horizontal milestone progress stepper with data-testid="journey-progress-stepper" and role="progressbar" above the shipment history.
  2. Stepper illustrates four sequential stages: Label created, In transit, Out for delivery, and Delivered.
  3. Completed stages receive checkmark indicators and the current active stage receives highlighted focus styling.
  4. When status is exception, the active step renders an exception alert styling with data-step-state="exception".
  5. The ui-proof screenshot for parcel page surface differs from previous release by displaying the journey progress stepper with test id journey-progress-stepper.

---

### ITEM-006: feat(web): interactive status summary filter chips with parcel counts on home page
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, filter, chips, home, high-visibility
- **Visible Surface**: home
- **Gap Anchor**: `app/web/src/pages/HomePage.tsx#L41-L57` and `app/web/src/components/ParcelTable.tsx`. Filtering is restricted to a compact select dropdown; users cannot see at a glance how many parcels are in each status category before filtering.
- **User Value**: Users can see live summary totals for each status and click status filter chips to filter the parcels table instantly.
- **Files Touched**:
  - `app/web/src/pages/HomePage.tsx`
  - `app/web/src/components/ParcelTable.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/home-page.test.tsx`
- **Acceptance Criteria**:
  1. Render a status summary chips container with data-testid="status-summary-chips" above the recent parcels table.
  2. Each chip displays the status label and dynamic count of parcels matching that status, including All parcels.
  3. Clicking a status chip filters the table to matching shipments and updates aria-pressed="true" on the selected chip.
  4. Keyboard navigation allows cycling focus between chips with arrow keys or Tab.
  5. The ui-proof screenshot for home surface differs from previous release by displaying the status summary chips with test id status-summary-chips.

---

### ITEM-007: feat(web): dark mode theme toggle with persistent preference
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: M
- **Tags**: ui, theme, dark-mode, high-visibility
- **Visible Surface**: home, parcel page
- **Gap Anchor**: `app/web/src/styles.css#L43` and `app/web/src/App.tsx#L51-L58`. The application hardcodes light theme variables without support for dark mode or user theme switching.
- **User Value**: Users viewing the tracker in dim environments can switch to dark mode, reducing eye strain and persisting their preference.
- **Files Touched**:
  - `app/web/src/App.tsx`
  - `app/web/src/components/Icons.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/home-page.test.tsx`
- **Acceptance Criteria**:
  1. A theme toggle button with data-testid="theme-toggle" and sun/moon icon is placed in the site header.
  2. Clicking the button toggles attribute data-theme between light and dark on the document root element.
  3. User theme selection persists in localStorage under key parcel_theme across page reloads.
  4. Dark mode styles define high-contrast dark backgrounds, surfaces, and legible light text tokens.
  5. The ui-proof screenshot for home and parcel page surfaces differs from previous release by including the theme toggle button with test id theme-toggle in the top header.

---

### ITEM-008: feat(web): last-known-location map card with inline SVG route on parcel page
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, map, parcel-page, high-visibility
- **Visible Surface**: parcel page
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L195-L200` and `app/web/src/components/Timeline.tsx#L11-L21`. The shipment history displays text events but lacks a geographic route illustration showing the last known checkpoint location.
- **User Value**: Recipients can visualize the geographic scan location on a static, lightweight route card without third-party mapping dependencies or external requests.
- **Files Touched**:
  - `app/web/src/components/LocationMap.tsx`
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. Render a static location map card with data-testid="location-map-card" containing an inline SVG route illustration on ParcelPage.
  2. Map card displays the most recent scan location label and a styled pin marker positioned along the route path.
  3. Inline SVG contains zero external asset requests, zero external web fonts, and no executable scripts.
  4. Map card contains an accessible aria-label identifying the current parcel location.
  5. The ui-proof screenshot for parcel page surface differs from previous release by displaying the static location map card with test id location-map-card.

---

### ITEM-009: feat(web): delivery countdown and arrival window banner on parcel page
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, eta, countdown, parcel-page, high-visibility
- **Visible Surface**: parcel page
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L182-L191` and `app/web/src/format.ts#L10-L15`. Estimated delivery date renders as an unstyled text line without calculated days remaining or an arrival window banner.
- **User Value**: Recipients can glance at a prominent countdown banner telling them exactly when to expect delivery (e.g. "Arriving in 2 days" or "Arriving today").
- **Files Touched**:
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/src/format.ts`
  - `app/web/src/styles.css`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. Render a delivery countdown banner with data-testid="eta-countdown-banner" in the parcel header.
  2. Banner calculates remaining days from estimatedDelivery and displays friendly text like "Arriving in 2 days" or "Arriving today".
  3. If estimated delivery date has passed without delivery, banner displays a delayed notification advice.
  4. When status is delivered, banner displays confirmed delivery completion text.
  5. The ui-proof screenshot for parcel page surface differs from previous release by displaying the delivery countdown banner with test id eta-countdown-banner.

---

### ITEM-010: feat(web): onboarding sample tracking numbers card on home page
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, onboarding, samples, home, high-visibility
- **Visible Surface**: home
- **Gap Anchor**: `app/web/src/pages/HomePage.tsx#L34-L36` and `app/core/src/fixtures.ts#L30-L55`. First-time users without a tracking number must search through fixture documentation to test the parcel tracker application.
- **User Value**: New visitors can explore the tracking application with one click by trying sample parcel numbers for common delivery states.
- **Files Touched**:
  - `app/web/src/pages/HomePage.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/home-page.test.tsx`
- **Acceptance Criteria**:
  1. Render an onboarding sample cards section with data-testid="onboarding-samples" directly beneath the search form on HomePage.
  2. Section provides three quick-try buttons for valid fixture parcels: In transit (PK1000000001), Out for delivery (PK1000000002), and Exception (PK1000000005).
  3. Clicking a sample button populates the tracking input and navigates directly to that parcel page.
  4. The sample section provides accessible button labels explaining each test shipment.
  5. The ui-proof screenshot for home surface differs from previous release by displaying the onboarding samples card with test id onboarding-samples.

---

### ITEM-011: feat(web): real-time search input validation with parseTrackingNumber
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ux, validation, web
- **Visible Surface**: home
- **Gap Anchor**: `app/web/src/components/SearchForm.tsx#L30-L40` and `app/core/src/tracking-number.ts#L3-L7`. Form checks only non-empty string and does not validate against parseTrackingNumber before submission. Core accepts case-insensitive input via regex /^PK\d{10}$/i.
- **User Value**: Users get immediate feedback about invalid tracking number patterns before form submission, reducing failed lookups.
- **Files Touched**:
  - `app/web/src/components/SearchForm.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/home-page.test.tsx`
- **Acceptance Criteria**:
  1. Validate the search input with parseTrackingNumber from @parcel/core case-insensitively before submitting.
  2. If the value does not parse as a valid tracking number, display an inline error message stating tracking numbers start with PK followed by ten digits.
  3. Prevent form submission and navigation when input validation fails.
  4. The ui-proof screenshot for invalid input surface differs from previous release by displaying the inline validation error notice.

---

### ITEM-012: feat(web): keyboard navigation and focus management improvements
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: accessibility, a11y, web
- **Visible Surface**: home
- **Gap Anchor**: `app/web/src/components/SearchForm.tsx` and `app/e2e/tests/parcel-tracking.spec.ts`. Pressing Escape inside search inputs does not reset focus, and tab order lacks Playwright regression verification.
- **User Value**: Keyboard-only users and screen-reader users can smoothly navigate through parcel details and tables without losing focus.
- **Files Touched**:
  - `app/web/src/App.tsx`
  - `app/web/src/components/SearchForm.tsx`
  - `app/web/src/styles.css`
  - `app/e2e/tests/parcel-tracking.spec.ts`
- **Acceptance Criteria**:
  1. On initial deep-link load to #/parcel/PK..., document.activeElement is h1#page-title.
  2. On pressing Escape key inside input#tracking-number, the empty error flag clears and removes p#tracking-number-error from the DOM.
  3. Playwright test verifies that pressing Tab navigates in logical order from skip link to brand to search input to submit button.
  4. The ui-proof screenshot for home surface confirms keyboard focus rings and active heading elements remain visible.

---

### ITEM-013: feat(web): accessible live region announcement on parcel load
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: accessibility, a11y, web
- **Visible Surface**: parcel page
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L163-L175`. Dynamic parcel details resolution does not announce status updates to assistive technologies upon completion.
- **User Value**: Visually impaired users using screen readers receive immediate audible notification when parcel data finishes loading.
- **Files Touched**:
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. Render a shared aria-live polite region on ParcelPage that announces status upon successful parcel data load.
  2. Announcement text includes the tracking number and the current human-readable status label.
  3. Live announcement container is visually hidden from DOM presentation while accessible to screen readers.
  4. The ui-proof screenshot for parcel page confirms the polite aria-live container element is mounted with data-testid="parcel-live-region".

---

### ITEM-014: feat(web): multi-parcel watchlist table in local storage
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: M
- **Tags**: ui, storage, web
- **Visible Surface**: home
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
  5. The ui-proof screenshot for home surface displays the My Watchlist table with test id parcel-watchlist-table.

---

### ITEM-015: feat(core): delivery exception status details and explanations
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: domain, core, web
- **Visible Surface**: parcel page
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
  1. Export a helper function getExceptionGuidance in @parcel/core mapping for delivery exception notes.
  2. Provide specific explanation text for customs document holds and failed delivery attempts based on fixture notes.
  3. When parcel status is exception, ParcelPage displays the mapped guidance box below the status badge.
  4. Unit tests verify exception guidance mapping for both fixture exception scenarios.
  5. The ui-proof screenshot for parcel page displays the exception guidance callout box with test id exception-guidance.

---

### ITEM-016: feat(web): carrier support details panel on parcel page
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, support, web
- **Visible Surface**: parcel page
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L195-L205`. Parcel page provides no carrier contact details, FAQ links, or support information for delayed packages.
- **User Value**: Users with delivery issues can quickly find carrier support hours and contact instructions.
- **Files Touched**:
  - `app/web/src/pages/ParcelPage.tsx`
  - `app/web/src/styles.css`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. A collapsible support card is rendered beneath the shipment history timeline.
  2. The card toggles open and closed with accessible button controls and aria-expanded state.
  3. The collapsible panel contains helper text explaining how to initiate an inquiry for delayed packages.
  4. The ui-proof screenshot for parcel page displays the collapsible carrier support card with test id carrier-support-panel.

---

### ITEM-017: feat(web): internationalization support with Spanish language dictionary
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: M
- **Tags**: i18n, localization, web
- **Visible Surface**: home, parcel page
- **Gap Anchor**: `app/web/src/pages/HomePage.tsx#L30` and `app/web/src/pages/ParcelPage.tsx#L160`. All UI labels, headings, and status badges are hardcoded English strings.
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
  2. Add an accessible language toggle in the header switching between English and Spanish.
  3. Status labels translate accurately including in transit to En transito and delivered to Entregado.
  4. Persist language choice in localStorage under key parcel_locale with English as default.
  5. The ui-proof screenshot for home and parcel page surfaces includes the language selector toggle with test id language-toggle.

---

### ITEM-018: feat(api): HTTP cache control and ETag validation headers
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: api, http, performance
- **Visible Surface**: parcel page
- **Gap Anchor**: `app/api/src/server.ts#L27`. Server unconditionally sends `cache-control: no-store` on all endpoints.
- **User Value**: API clients benefit from standard caching headers and conditional `304 Not Modified` responses for unchanged parcel records.
- **Files Touched**:
  - `app/api/src/server.ts`
  - `app/api/tests/api.test.ts`
  - `app/web/src/pages/ParcelPage.tsx`
- **Acceptance Criteria**:
  1. GET endpoints compute and return an ETag header based on shipment payload content.
  2. If an incoming request includes matching If-None-Match header, return HTTP 304 with empty body.
  3. For non-terminal parcels (in_transit, out_for_delivery), set Cache-Control to 'private, max-age=30'.
  4. The ui-proof screenshot for parcel page confirms data freshness timestamp indicator with test id data-freshness-indicator.

---

### ITEM-019: feat(api): pagination parameters and navigation controls for parcel listings
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: M
- **Tags**: api, pagination, backend
- **Visible Surface**: home
- **Gap Anchor**: `app/api/src/server.ts#L60` and `app/web/src/http-parcel-service.ts#L24-L28`. Endpoint returns all parcels without limit or offset. Default when limit is omitted must remain unbounded so existing clients receive all parcels.
- **User Value**: API consumers and web clients can query parcels in smaller pages, improving response times and network overhead as shipments grow.
- **Files Touched**:
  - `app/api/src/server.ts`
  - `app/core/src/service.ts`
  - `app/web/src/http-parcel-service.ts`
  - `app/web/src/components/ParcelTable.tsx`
  - `app/api/tests/api.test.ts`
- **Acceptance Criteria**:
  1. Support optional limit and offset query parameters on GET /api/parcels endpoint.
  2. When limit query parameter is omitted, default behavior remains unbounded and returns all parcel summaries.
  3. When limit and offset are provided, response returns sliced parcel summaries along with total count metadata.
  4. The ui-proof screenshot for home surface displays pagination page size controls with test id parcel-pagination-controls.

---

### ITEM-020: feat(e2e): end-to-end tests for status filtering and search validation
- **Status**: todo
- **Dependencies**: [ITEM-011]
- **Cost Class**: S
- **Tags**: e2e, playwright, testing
- **Visible Surface**: home
- **Gap Anchor**: `app/e2e/tests/parcel-tracking.spec.ts` and `app/web/src/router.ts#L43`. E2E suite verifies basic navigation but lacks coverage for status filter dropdown interactions and search validation errors. URL hash format is `#/?status=delivered`.
- **User Value**: Automated regression protection for core user search and filtering journeys.
- **Files Touched**:
  - `app/e2e/tests/parcel-tracking.spec.ts`
- **Acceptance Criteria**:
  1. Playwright test verifies selecting delivered status filter displays only delivered parcels and updates hash to #/?status=delivered.
  2. Playwright test verifies selecting All statuses restores the complete parcel list.
  3. Playwright test verifies submitting invalid tracking number displays inline validation error and prevents page navigation.
  4. The ui-proof screenshot for home surface verifies status filter hash updates without visual layout breakage.

---

### ITEM-021: feat(web): relative time formatting helper for updates and timeline events
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: format, ux, web
- **Visible Surface**: parcel page
- **Gap Anchor**: `app/web/src/format.ts#L1-L15`. Format utility formatDateTime outputs absolute timestamps like '10 Oct 2026, 06:42 UTC' without human-friendly relative offsets.
- **User Value**: Users can immediately see how recently a scan occurred such as "15 minutes ago" or "Yesterday".
- **Files Touched**:
  - `app/web/src/format.ts`
  - `app/web/src/components/ParcelTable.tsx`
  - `app/web/src/components/Timeline.tsx`
  - `app/web/tests/format.test.ts`
- **Acceptance Criteria**:
  1. Add formatRelativeTime helper in format.ts returning friendly relative strings such as just now, minutes ago, hours ago, or yesterday.
  2. Keep absolute timestamp visible in timeline and update text ('10 Oct 2026, 06:42 UTC') and append relative time beside it or in title attribute.
  3. Display relative elapsed time in title tooltip on parcel table last update cells.
  4. The ui-proof screenshot for parcel page displays relative timestamp annotations next to event dates.

---

### ITEM-022: feat(web): manual refresh button with polling indicator on parcel detail page
- **Status**: todo
- **Dependencies**: [ITEM-013]
- **Cost Class**: S
- **Tags**: ux, data, web
- **Visible Surface**: parcel page
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L140-L155`. Page fetches data once on mount; users must reload the whole browser tab to check for fresh tracking events.
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
  4. The ui-proof screenshot for parcel page displays the manual refresh button with test id parcel-refresh-button.

---

### ITEM-023: feat(web): print stylesheet optimization for parcel tracking summary
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: css, print, web
- **Visible Surface**: parcel page
- **Gap Anchor**: `app/web/src/styles.css#L43`. Theme defines `color-scheme: light;`, but stylesheet lacks `@media print` rules, causing screen layout elements (navigation links, buttons, search input) to print wastefully.
- **User Value**: Users can print clean physical delivery receipts or save them as tidy PDF summaries.
- **Files Touched**:
  - `app/web/src/styles.css`
  - `app/web/tests/parcel-page.test.tsx`
- **Acceptance Criteria**:
  1. Add `@media print` section hiding interactive screen controls like `.back-link` and action buttons.
  2. Ensure tracking number header, shipment status, and timeline event list print with high-contrast text on white backgrounds.
  3. Prevent page breaks inside timeline event entries during printing.
  4. The ui-proof screenshot for parcel page confirms print button control is visible in header with test id print-summary-button.

---

### ITEM-024: feat(web): bundle size budget check and vendor chunk splitting in Vite
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: performance, build, vite
- **Visible Surface**: home
- **Gap Anchor**: `app/web/vite.config.ts`. Vite build lacks chunk size budgets and compression monitoring to prevent bundle regressions.
- **User Value**: Ensures the web application stays lean, loads instantly, and avoids shipping unnecessary bundle weight.
- **Files Touched**:
  - `app/web/vite.config.ts`
  - `app/web/tests/vite-config.test.ts`
- **Acceptance Criteria**:
  1. Configure manual chunk splitting in vite.config.ts to isolate React and React DOM vendor dependencies into a dedicated vendor chunk.
  2. Configure build warning threshold and add an automated test in vite-config.test.ts asserting vendor chunking and size rules.
  3. The ui-proof screenshot for home surface confirms initial page load renders without script bundle regressions.

---

### ITEM-025: feat(web): estimated delivery date column in recent parcels table
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, table, web
- **Visible Surface**: home
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
  4. The ui-proof screenshot for home surface displays the Estimated delivery column header in the table.
