// Whole-page states: loading, error, nothing published, route not found.

import { emptyState, h } from '../dom.js';
import { icon } from '../icons.js';

export function renderLoading() {
  const column = () => h('div', { class: 'skeleton sk-col' });
  return h(
    'div',
    { class: 'view state-loading', role: 'status', 'aria-label': 'Loading the latest state' },
    h('div', { class: 'skeleton sk-title' }),
    h('div', { class: 'skeleton sk-kpis' }),
    h('div', { class: 'sk-cols' }, column(), column(), column(), column()),
    h('p', { class: 'sr-only' }, 'Loading the latest state from the ledger'),
  );
}

export function renderError(message, onRetry) {
  const retry = h('button', { type: 'button', class: 'btn btn-primary' }, icon('refresh', { size: 16 }), 'Retry');
  retry.addEventListener('click', onRetry);
  return h(
    'div',
    { class: 'view' },
    h(
      'div',
      { class: 'empty-state empty-error', role: 'alert' },
      h('p', { class: 'empty-title' }, 'The state could not be loaded'),
      h('p', { class: 'empty-body wrap' }, message),
      h('div', { class: 'empty-actions' }, retry),
    ),
  );
}

export function renderNothingPublished(onRetry) {
  const retry = h('button', { type: 'button', class: 'btn btn-secondary' }, icon('refresh', { size: 16 }), 'Check again');
  retry.addEventListener('click', onRetry);
  return h('div', { class: 'view' }, emptyState('Waiting for the first state', 'The ledger has not published a state file yet. The page checks again on its own, or you can check now.', retry));
}

export function renderNotFound() {
  return h('div', { class: 'view' }, emptyState('Page not found', 'That address does not match any view.', h('a', { class: 'btn btn-secondary', href: '#/' }, icon('back', { size: 16 }), 'Back to the board')));
}
