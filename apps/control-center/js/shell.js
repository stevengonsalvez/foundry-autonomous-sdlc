// The page frame: navigation, the freshness readout, the controls and the spend banner.
// The markup skeleton is in index.html; this fills in what changes.

import { h, timeEl } from './dom.js';
import { formatInteger, formatTimestamp, formatUsdWords } from './format.js';
import { icon } from './icons.js';
import { freshness, STALE_AFTER_S } from './model.js';
import { NAV } from './router.js';

const staleMinutes = STALE_AFTER_S / 60;

export function mountShell({ onRefresh }) {
  const navEl = document.getElementById('nav');
  const toolsEl = document.getElementById('tools');
  const bannerEl = document.getElementById('banner');
  const repoEl = document.getElementById('repo-name');

  // ---- refresh
  const refreshButton = h('button', { type: 'button', class: 'icon-btn', id: 'refresh', 'aria-label': 'Refresh now', title: 'Refresh now' }, icon('refresh', { size: 16 }), h('span', { class: 'icon-btn-text' }, 'Refresh'));
  refreshButton.addEventListener('click', onRefresh);

  const fresh = h('div', { class: 'fresh', id: 'freshness' });
  toolsEl.replaceChildren(fresh, refreshButton);

  // ---- navigation
  const links = new Map();
  for (const item of NAV) {
    const count = h('span', { class: 'nav-count', hidden: true });
    const a = h('a', { class: 'nav-link', href: item.hash }, item.label, count);
    links.set(item.name, { a, count });
  }
  navEl.replaceChildren(...[...links.values()].map((l) => l.a));

  return {
    setRoute(route) {
      const active = route.name === 'ticket' ? 'board' : route.name;
      for (const [name, { a }] of links) {
        if (name === active) a.setAttribute('aria-current', route.name === 'ticket' ? 'true' : 'page');
        else a.removeAttribute('aria-current');
      }
    },

    setEscalations(count) {
      const { count: el } = links.get('escalations');
      el.textContent = formatInteger(count);
      el.hidden = count === 0;
    },

    setBusy(busy) {
      refreshButton.setAttribute('aria-busy', String(busy));
      refreshButton.classList.toggle('is-busy', busy);
    },

    /** Repaint the freshness readout and the banner. Cheap enough to run on a timer. */
    paint(snap, nowMs, routeName = '') {
      const { state } = snap;
      repoEl.textContent = state?.repo ? state.repo : '';
      const parts = [];
      if (state) {
        const f = freshness(state, nowMs);
        const updated = state.updated_at ?? state.generated_at;
        parts.push(
          h(
            'span',
            { class: `fresh-text${f.stale ? ' is-stale' : ''}`, title: `Last ledger event: ${updated ? formatTimestamp(updated) : 'unknown'}. Snapshot generated: ${state.generated_at ? formatTimestamp(state.generated_at) : 'unknown'}.` },
            h('span', { class: `fresh-dot${f.stale ? ' is-stale' : ''}`, 'aria-hidden': 'true' }),
            'Updated ',
            updated ? timeEl(updated, nowMs) : '-',
          ),
        );
        if (f.stale) {
          parts.push(
            h(
              'span',
              { class: 'badge tone-bad stale-badge', tabindex: '0', title: `The snapshot is more than ${staleMinutes} minutes old: the orchestrator is not ticking or the ledger is down. What you see may be out of date.` },
              'STALE',
              h('span', { class: 'sr-only' }, `: the snapshot is more than ${staleMinutes} minutes old. The orchestrator is not ticking or the ledger is down.`),
            ),
          );
        }
        parts.push(h('span', { class: 'source', title: 'Where the data on screen came from' }, 'source: ', h('strong', null, snap.source ?? '-')));
      } else {
        parts.push(h('span', { class: 'fresh-text' }, snap.phase === 'loading' ? 'Loading' : 'No data'));
      }
      const problems = Object.entries(snap.problems);
      if (problems.length > 0) {
        parts.push(h('span', { class: 'badge tone-warn', tabindex: '0', title: problems.map(([source, message]) => `${source}: ${message}`).join('\n') }, `${problems.length} source ${problems.length === 1 ? 'problem' : 'problems'}`));
      }
      fresh.replaceChildren(...parts);

      // The banner repeats the ledger's own verdict on spend; it never computes one.
      const totals = state?.cost?.totals;
      if (totals && (totals.halted || totals.over_cap) && routeName !== 'cost') {
        const billed = state.cost.billing?.billed_usd ?? null;
        bannerEl.replaceChildren(
          h(
            'div',
            { class: 'container' },
            h(
              'a',
              { class: 'spend-banner', href: '#/cost' },
              h('span', { class: 'spend-dot', 'aria-hidden': 'true' }),
              h('span', { class: 'spend-text' }, totals.over_cap ? 'Spend is over the cap' : 'Spend is over the halt line', billed !== null ? `: Azure billed ${formatUsdWords(billed)}.` : '.', totals.halted ? ' The loop is halted.' : '', ' See the cost view.'),
            ),
          ),
        );
      } else {
        bannerEl.replaceChildren();
      }
    },
  };
}
