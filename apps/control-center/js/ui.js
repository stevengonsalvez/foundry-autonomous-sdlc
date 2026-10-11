// View state that should survive a data refresh (filters, sort order) but not a page reload.
import { emptyFilters } from './model.js';

export const ui = {
  board: emptyFilters(),
  cost: { key: 'usd', direction: 'desc' },
  trail: { kind: 'all', issue: null },
};
