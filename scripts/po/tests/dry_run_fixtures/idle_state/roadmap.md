# Product Roadmap: Parcel Tracker

### ITEM-001: feat(web): display event location pin in parcel timeline
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, timeline, web
- **Gap Anchor**: `app/web/src/components/Timeline.tsx#L11-L21` and `app/web/src/components/Icons.tsx#L23-L59`. Timeline already renders event.location, :11 has is-latest, and line 14 has the Latest tag. Carrier contract requires place with minLength 1.
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
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L73-L80`.
- **User Value**: Share parcel link.
- **Files Touched**:
  - `app/web/src/pages/ParcelPage.tsx`
- **Acceptance Criteria**:
  1. Copy link button rendered in parcel header.
  2. Clicking writes URL to clipboard.
  3. Aria label identifies parcel number.

---

### ITEM-003: feat(web): store and display recent searches in local storage
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, storage, web
- **Gap Anchor**: `app/web/src/pages/HomePage.tsx#L34`.
- **User Value**: Recent searches list.
- **Files Touched**:
  - `app/web/src/pages/HomePage.tsx`
- **Acceptance Criteria**:
  1. Stores searches in localStorage.
  2. Displays recent search chips.
  3. Clicking chip navigates to parcel.

---

### ITEM-004: feat(web): real-time search input validation with parseTrackingNumber
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ux, validation, web
- **Gap Anchor**: `app/web/src/components/SearchForm.tsx#L10`.
- **User Value**: Validation feedback.
- **Files Touched**:
  - `app/web/src/components/SearchForm.tsx`
- **Acceptance Criteria**:
  1. Validates input with parseTrackingNumber.
  2. Displays error when invalid.
  3. Prevents invalid form submission.

---

### ITEM-006: feat(web): keyboard navigation and focus management improvements
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: accessibility, web
- **Gap Anchor**: `app/web/src/components/SearchForm.tsx`.
- **User Value**: Keyboard navigation.
- **Files Touched**:
  - `app/web/src/components/SearchForm.tsx`
- **Acceptance Criteria**:
  1. Focus moves to parcel page main heading.
  2. Escape key resets search input.
  3. Tab order verified with Playwright test.

---

### ITEM-007: feat(web): accessible live region announcement on parcel load
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: accessibility, web
- **Gap Anchor**: `app/web/src/pages/ParcelPage.tsx#L73`.
- **User Value**: Live region announcements.
- **Files Touched**:
  - `app/web/src/pages/ParcelPage.tsx`
- **Acceptance Criteria**:
  1. Live region announces parcel status.
  2. Announcement includes tracking number.
  3. Visually hidden from DOM presentation.
