# Product Roadmap: Parcel Tracker

### ITEM-001: feat(web): base layout
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, web
- **Gap Anchor**: `app/web/src/App.tsx#L50`. Base layout skeleton.
- **User Value**: Render main application container.
- **Files Touched**:
  - `app/web/src/App.tsx`
- **Acceptance Criteria**:
  1. Base layout renders header and main container.

---

### ITEM-002: feat(web): clear search query button
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, web
- **Gap Anchor**: `app/web/src/components/SearchForm.tsx#L25`. Quick clear button.
- **User Value**: Reset search input with one click.
- **Files Touched**:
  - `app/web/src/components/SearchForm.tsx`
- **Acceptance Criteria**:
  1. Clicking clear resets input text cleanly.

---

### ITEM-003: feat(web): filter dropdown component
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: ui, web
- **Gap Anchor**: `app/web/src/pages/HomePage.tsx#L45`. Status filter dropdown component.
- **User Value**: Users can filter parcel list by status.
- **Files Touched**:
  - `app/web/src/pages/HomePage.tsx`
- **Acceptance Criteria**:
  1. Dropdown renders all valid parcel status options.

---

### ITEM-004: feat(web): filter persistence in local storage
- **Status**: todo
- **Dependencies**: []
- **Cost Class**: S
- **Tags**: storage, web
- **Gap Anchor**: `app/web/src/pages/HomePage.tsx#L50`. Save filter preference.
- **User Value**: Remembers selected filter preference across sessions.
- **Files Touched**:
  - `app/web/src/pages/HomePage.tsx`
- **Acceptance Criteria**:
  1. Saves active filter in local storage.
