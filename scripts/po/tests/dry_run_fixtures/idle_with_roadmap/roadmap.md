# Product Roadmap: Parcel Tracker

### ITEM-001: feat(web): base layout
- **Status**: done
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, web
- **Gap Anchor**: `app/web/src/App.tsx#L50`. Base layout skeleton.
- **User Value**: Basic container.
- **Files Touched**:
  - `app/web/src/App.tsx`
- **Acceptance Criteria**:
  1. Base layout renders header and main container.

---

### ITEM-002: feat(web): advanced filter options
- **Status**: todo
- **Dependencies**: [ITEM-003]
- **Cost Class**: S
- **Tags**: ui, web
- **Gap Anchor**: `app/web/src/pages/HomePage.tsx#L40`. Advanced filter options.
- **User Value**: Extended filters.
- **Files Touched**:
  - `app/web/src/pages/HomePage.tsx`
- **Acceptance Criteria**:
  1. Advanced filters enable compound status searches.

---

### ITEM-003: feat(web): filter dropdown component
- **Status**: todo
- **Dependencies**: [ITEM-001]
- **Cost Class**: S
- **Tags**: ui, web
- **Gap Anchor**: `app/web/src/pages/HomePage.tsx#L45`. Status filter dropdown component.
- **User Value**: Users can filter parcel list by status.
- **Files Touched**:
  - `app/web/src/pages/HomePage.tsx`
  - `app/web/src/components/ParcelTable.tsx`
- **Acceptance Criteria**:
  1. Dropdown renders all valid parcel status options.
  2. Selecting an option filters the table.

---

### ITEM-004: feat(web): filter persistence in local storage
- **Status**: todo
- **Dependencies**: [ITEM-002]
- **Cost Class**: S
- **Tags**: storage, web
- **Gap Anchor**: `app/web/src/pages/HomePage.tsx#L50`. Save filter preference.
- **User Value**: Remembers selected filter.
- **Files Touched**:
  - `app/web/src/pages/HomePage.tsx`
- **Acceptance Criteria**:
  1. Saves active filter in local storage.

---

### ITEM-005: feat(web): clear search query button
- **Status**: todo
- **Dependencies**: [ITEM-001]
- **Cost Class**: S
- **Tags**: ui, web
- **Gap Anchor**: `app/web/src/components/SearchForm.tsx#L25`. Quick clear button.
- **User Value**: Reset search with one click.
- **Files Touched**:
  - `app/web/src/components/SearchForm.tsx`
- **Acceptance Criteria**:
  1. Clicking clear resets input text.

---

### ITEM-006: feat(web): export search results
- **Status**: todo
- **Dependencies**: [ITEM-005]
- **Cost Class**: S
- **Tags**: export, web
- **Gap Anchor**: `app/web/src/components/ParcelTable.tsx#L30`. Export data.
- **User Value**: Download CSV of results.
- **Files Touched**:
  - `app/web/src/components/ParcelTable.tsx`
- **Acceptance Criteria**:
  1. Exports table to CSV.

---

### ITEM-007: feat(web): parcel status summary counter
- **Status**: todo
- **Dependencies**: [ITEM-001]
- **Cost Class**: S
- **Tags**: ui, web
- **Gap Anchor**: `app/web/src/pages/HomePage.tsx#L35`. Count per status.
- **User Value**: Overview of active shipments.
- **Files Touched**:
  - `app/web/src/pages/HomePage.tsx`
- **Acceptance Criteria**:
  1. Displays badge count for each status.
