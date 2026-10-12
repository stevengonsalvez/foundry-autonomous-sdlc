// Whole-page states: loading, error, nothing published, route not found.
// Strictly text nodes only via dom.js (no innerHTML or string sinks).

import { emptyState, ghLink, h } from '../dom.js';
import { icon } from '../icons.js';
import { NEW_TICKET_URL } from '../safe.js';

/**
 * Clean loading skeleton and spinner while awaiting the first ledger snapshot.
 */
export function renderLoading() {
  const column = () => h('div', { class: 'skeleton sk-col' });
  return h(
    'div',
    { class: 'view state-loading', role: 'status', 'aria-label': 'Loading the latest state', 'aria-busy': 'true' },
    h(
      'div',
      { class: 'loading-indicator', 'aria-hidden': 'true' },
      h('span', { class: 'spinner' }),
      h('span', { class: 'loading-text' }, 'Awaiting ledger snapshot...'),
    ),
    h('div', { class: 'skeleton sk-title' }),
    h('div', { class: 'skeleton sk-kpis' }),
    h('div', { class: 'sk-cols' }, column(), column(), column(), column()),
    h('p', { class: 'sr-only' }, 'Loading the latest state from the ledger'),
  );
}

/**
 * Contextual diagnostic hint based on known error patterns.
 */
function errorDiagnosticHint(raw) {
  const text = String(raw || '');
  if (/not valid JSON/i.test(text)) {
    return 'The state file returned by the ledger is malformed and could not be parsed as JSON.';
  }
  if (/unsupported.*version/i.test(text)) {
    return 'The schema version declared in state.json is not supported by this control center.';
  }
  if (/500/i.test(text)) {
    return 'The remote server responded with an HTTP 500 internal server error.';
  }
  if (/failed to fetch|network|unreachable/i.test(text)) {
    return 'A network communication error prevented reading the ledger snapshot.';
  }
  return null;
}

/**
 * Error state view with role="alert", clear alert icon, problem explanation,
 * and an actionable Retry button.
 */
export function renderError(message, onRetry) {
  const msgText = typeof message === 'string' ? message : (message?.message ?? 'Unknown error occurred.');
  const hint = errorDiagnosticHint(msgText);

  const retry = h('button', { type: 'button', class: 'btn btn-primary' }, icon('refresh', { size: 16 }), 'Retry');
  if (typeof onRetry === 'function') {
    retry.addEventListener('click', onRetry);
  }

  const bodyChildren = [h('p', { class: 'empty-body wrap' }, msgText)];
  if (hint && !msgText.includes(hint)) {
    bodyChildren.push(h('p', { class: 'empty-hint muted' }, hint));
  }

  return h(
    'div',
    { class: 'view' },
    h(
      'div',
      { class: 'empty-state empty-error', role: 'alert' },
      h('div', { class: 'empty-icon-wrap', 'aria-hidden': 'true' }, icon('alert', { size: 28, className: 'empty-icon' })),
      h('p', { class: 'empty-title' }, 'The state could not be loaded'),
      ...bodyChildren,
      h('div', { class: 'empty-actions' }, retry),
    ),
  );
}

/**
 * Empty board state when no tickets have been opened yet, with an actionable link
 * to open a new ticket on GitHub.
 */
export function renderEmptyBoard({ ticketUrl = NEW_TICKET_URL } = {}) {
  const openTicket = ghLink(
    ticketUrl,
    ['Open a ticket', icon('external', { size: 12, className: 'icon-ext' })],
    { class: 'btn btn-primary' },
  );

  return h(
    'div',
    { class: 'view view-empty-board' },
    emptyState(
      'No tickets yet',
      'The board fills as soon as the first issue is opened. Creating a ticket on GitHub is the only way to start one.',
      openTicket,
    ),
  );
}

/**
 * Message explaining that the ledger has not published a state file yet.
 */
export function renderNothingPublished(onRetry) {
  const retry = h('button', { type: 'button', class: 'btn btn-secondary' }, icon('refresh', { size: 16 }), 'Check again');
  if (typeof onRetry === 'function') {
    retry.addEventListener('click', onRetry);
  }
  return h(
    'div',
    { class: 'view state-missing-ledger' },
    emptyState(
      'Waiting for the first state',
      'The ledger has not published a state file yet. The page checks again on its own, or you can check now.',
      retry,
    ),
  );
}

/**
 * Route 404 state with a way back to the board.
 */
export function renderNotFound() {
  return h(
    'div',
    { class: 'view' },
    emptyState(
      'Page not found',
      'That address does not match any view.',
      h('a', { class: 'btn btn-secondary', href: '#/' }, icon('back', { size: 16 }), 'Back to the board'),
    ),
  );
}

/**
 * Generic empty view wrapper.
 */
export function renderEmptyView(title, body, ...actions) {
  return h('div', { class: 'view' }, emptyState(title, body, ...actions));
}
