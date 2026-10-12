// #/ Ticket board: delivery matrix showing every ticket in its column with filters.
// The columns are rebuilt in place when a filter changes, preserving search focus.

import { badge, emptyState, ghLink, h } from '../dom.js';
import { formatInteger, formatUsd, plural } from '../format.js';
import { icon } from '../icons.js';
import { boardColumns, boardSummary, emptyFilters, typesPresent, timeInStage } from '../model.js';
import { NEW_BUG_URL, NEW_TICKET_URL, limitText } from '../safe.js';
import { ui } from '../ui.js';
import {
  costBar,
  envBadgeFor,
  escalationBadge,
  externalLabel,
  flagBadges,
  pageHead,
  sinceEl,
  ticketGithubUrl,
  ticketHref,
  typeBadge,
} from './common.js';

const MACRO_PHASES = [
  {
    id: 'inception',
    title: 'Inception & Scoping',
    tag: 'Business',
    stages: ['backlog', 'refining', 'feasible'],
    span: 3,
  },
  {
    id: 'construction',
    title: 'Construction & Verification',
    tag: 'Engineering',
    stages: ['tests', 'building', 'review'],
    span: 3,
  },
  {
    id: 'release',
    title: 'Release & Operations',
    tag: 'Deploy',
    stages: ['staging', 'prod'],
    span: 2,
  },
  {
    id: 'exception',
    title: 'Exception',
    tag: 'Exception',
    stages: ['escalated'],
    span: 1,
  },
];

const STAGE_CATEGORIES = {
  backlog: 'Intake',
  refining: 'Flow',
  feasible: 'Gate',
  tests: 'Flow',
  building: 'Flow',
  review: 'Gate',
  staging: 'Gate',
  prod: 'Terminal',
  escalated: 'Exception',
};

function macroGroup(macro, columns) {
  const stageSet = new Set(macro.stages);
  const matched = columns.filter((c) => stageSet.has(c.stage));
  const total = matched.reduce((sum, c) => sum + c.tickets.length, 0);
  return h(
    'div',
    { class: `macro-group macro-group-${macro.id}` },
    h(
      'div',
      { class: 'macro-head' },
      h(
        'div',
        { class: 'macro-titles' },
        h('span', { class: 'macro-name' }, macro.title),
        h('span', { class: 'macro-meta' }, `${macro.stages.length} stages : ${macro.tag}`),
      ),
      h('span', { class: 'macro-count', title: `${total} shown in ${macro.title}` }, formatInteger(total)),
    ),
  );
}

function card(ticket, nowMs) {
  const inStage = timeInStage(ticket, nowMs);
  const link = ticket.pending
    ? ghLink(ticketGithubUrl(ticket), [ticket.title || 'Untitled', icon('external', { size: 12, className: 'icon-ext' })], { class: 'card-link clamp-2' })
    : h('a', { class: 'card-link clamp-2', href: ticketHref(ticket.issue), 'data-fkey': `t${ticket.issue}` }, ticket.title || 'Untitled');
  const issueNum = ticket.kind === 'pr' ? `PR #${ticket.issue}` : `#${ticket.issue}`;

  return h(
    'article',
    { class: `card${ticket.pending ? ' card-pending' : ''}`, 'data-stage': ticket.stage },
    h(
      'div',
      { class: 'card-top' },
      h('span', { class: 'card-num' }, issueNum),
      typeBadge(ticket.type),
      envBadgeFor(ticket),
    ),
    h('h3', { class: 'card-title' }, link),
    ticket.pending
      ? h('p', { class: 'card-note' }, 'Not in the ledger yet. It appears here with its stage once the next tick picks it up.')
      : h('div', { class: 'card-cost' }, costBar(ticket.cost.usd, ticket.cost.cap_used_pct)),
    h(
      'div',
      { class: 'card-foot' },
      h(
        'span',
        { class: 'in-stage' },
        sinceEl(inStage.since, nowMs),
        ' in ',
        ticket.stage === 'prod' ? 'production' : ticket.stage,
      ),
      escalationBadge(ticket),
      ...flagBadges(ticket.flags),
    ),
  );
}

function column(col, nowMs, filtered) {
  const quiet = col.tickets.length === 0;
  const list = h('ul', { class: 'col-list' });
  for (const t of col.tickets) list.append(h('li', null, card(t, nowMs)));
  const countText = filtered && col.total !== col.tickets.length ? `${col.tickets.length} of ${col.total}` : String(col.tickets.length);
  const category = STAGE_CATEGORIES[col.stage] || 'Flow';

  return h(
    'section',
    { class: `col col-${col.stage}${quiet ? ' col-quiet' : ''}`, 'aria-labelledby': `col-${col.stage}` },
    h(
      'header',
      { class: 'col-head' },
      h(
        'div',
        { class: 'col-head-main' },
        h('h2', { id: `col-${col.stage}` }, col.label),
        h('span', { class: `col-cat col-cat-${category.toLowerCase()}` }, category),
      ),
      h('span', { class: 'col-count', title: `${col.tickets.length} shown, ${col.total} in this stage` }, countText),
    ),
    quiet
      ? h(
          'div',
          { class: 'col-empty' },
          h('span', { class: 'col-empty-text' }, filtered && col.total > 0 ? 'No matches' : 'No tickets'),
          h('p', { class: 'sr-only' }, filtered && col.total > 0 ? 'No matches' : 'No tickets'),
        )
      : list,
  );
}

function kpi(label, value, tone = '', edgeClass = '') {
  return h(
    'div',
    { class: `kpi ${tone}`.trim() },
    h('span', { class: `kpi-edge ${edgeClass}`.trim(), 'aria-hidden': 'true' }),
    h('dt', { class: 'kpi-label' }, label),
    h('dd', { class: 'kpi-value' }, value),
  );
}

function summaryStrip(ctx) {
  const { state, pending } = ctx;
  const sum = boardSummary(state, pending);
  const totals = state.cost.totals;
  const billed = state.cost.billing?.billed_usd ?? null;
  return h(
    'dl',
    { class: 'kpis board-kpis' },
    kpi('Total Tickets', formatInteger(sum.total), '', 'kpi-edge-total'),
    kpi('In flight', formatInteger(sum.inFlight), 'kpi-transit', 'kpi-edge-flight'),
    kpi('In production', formatInteger(sum.prod), 'kpi-good', 'kpi-edge-prod'),
    kpi('Escalated', formatInteger(sum.escalated), sum.escalated > 0 ? 'kpi-bad' : '', 'kpi-edge-escalated'),
    kpi('Ledger estimate', formatUsd(totals.usd), '', 'kpi-edge-ledger'),
    kpi('Azure billed', billed === null ? 'not read yet' : formatUsd(billed), billed !== null && totals.halted ? 'kpi-bad' : '', 'kpi-edge-billed'),
  );
}

function toolbar(ctx, update) {
  const { state, pending } = ctx;
  const filters = ui.board;
  const types = typesPresent(state, pending);

  const chips = types.map((type) => {
    const on = filters.types.has(type);
    const chip = h('button', { type: 'button', class: 'chip', 'aria-pressed': String(on) }, type === 'unclassified' ? 'New' : limitText(type, 24));
    chip.addEventListener('click', () => {
      if (filters.types.has(type)) filters.types.delete(type);
      else filters.types.add(type);
      chip.setAttribute('aria-pressed', String(filters.types.has(type)));
      update();
    });
    return chip;
  });

  const search = h('input', {
    id: 'board-search',
    class: 'input',
    type: 'search',
    placeholder: 'Number or title',
    value: filters.query,
    autocomplete: 'off',
    spellcheck: 'false',
    'data-fkey': 'search',
  });
  search.addEventListener('input', () => {
    filters.query = search.value;
    update();
  });

  const hideOld = h('input', {
    id: 'board-hide-old',
    type: 'checkbox',
    class: 'switch-input',
    checked: filters.hideOld,
  });
  hideOld.addEventListener('change', () => {
    filters.hideOld = hideOld.checked;
    update();
  });

  const clear = h('button', { type: 'button', class: 'btn btn-ghost btn-sm' }, 'Clear filters');
  clear.addEventListener('click', () => {
    Object.assign(filters, emptyFilters());
    ctx.rerender();
  });

  return h(
    'div',
    { class: 'toolbar board-toolbar', role: 'search' },
    h('div', { class: 'chip-group', role: 'group', 'aria-label': 'Filter by type' }, ...chips),
    h(
      'div',
      { class: 'search-field' },
      icon('search', { size: 14 }),
      h('label', { class: 'sr-only', for: 'board-search' }, 'Search by ticket number or title'),
      search,
    ),
    h(
      'label',
      { class: 'switch', for: 'board-hide-old' },
      hideOld,
      h('span', { class: 'switch-track', 'aria-hidden': 'true' }),
      h('span', null, 'Hide finished older than 7 days'),
    ),
    clear,
  );
}

export function renderBoard(ctx) {
  const { state, pending, now } = ctx;
  const filters = ui.board;
  const board = h('div', { class: 'board' });
  const macroBand = h('div', { class: 'macro-band', 'aria-hidden': 'true' });
  const boardCanvas = h('div', { class: 'board-canvas' }, macroBand, board);
  const boardScroll = h(
    'div',
    { class: 'board-scroll', role: 'region', 'aria-label': 'Ticket board, scrolls sideways', tabindex: '0' },
    boardCanvas,
  );
  const result = h('p', { class: 'sr-only', 'aria-live': 'polite', role: 'status' });

  const isFiltered = () => filters.types.size > 0 || filters.query.trim() !== '' || filters.hideOld;
  const update = () => {
    const columns = boardColumns(state, pending, filters, now);
    macroBand.replaceChildren(...MACRO_PHASES.map((m) => macroGroup(m, columns)));
    board.replaceChildren(...columns.map((c) => column(c, now, isFiltered())));
    const shown = columns.reduce((n, c) => n + c.tickets.length, 0);
    result.textContent = `${shown} ${plural(shown, 'ticket')} shown`;
  };
  const bar = toolbar(ctx, update);
  update();

  const actions = [
    ghLink(NEW_TICKET_URL, [icon('plus', { size: 16 }), 'New ticket'], { class: 'btn btn-primary' }),
    ghLink(NEW_BUG_URL, [icon('bug', { size: 16 }), 'Report a bug'], { class: 'btn btn-secondary' }),
  ];

  if (state.tickets.length === 0 && pending.length === 0) {
    return h(
      'div',
      { class: 'view' },
      pageHead({ title: 'Tickets', lede: 'Every ticket from backlog to production.', actions }),
      emptyState(
        'No tickets yet',
        'The board fills as soon as the first issue is opened. Creating a ticket on GitHub is the only way to start one.',
        ghLink(NEW_TICKET_URL, externalLabel('Open a ticket'), { class: 'btn btn-primary' }),
      ),
    );
  }

  return h(
    'div',
    { class: 'view view-board' },
    pageHead({ title: 'Tickets', lede: 'Every ticket from backlog to production. Read only: tickets are created on GitHub, the agents do the rest.', actions }),
    summaryStrip(ctx),
    bar,
    result,
    boardScroll,
    state.dropped > 0 ? h('p', { class: 'footnote' }, badge(`${state.dropped} unreadable`, 'warn'), ' ', `${state.dropped} ${plural(state.dropped, 'entry', 'entries')} in state.json could not be read and were skipped.`) : null,
    state.archived > 0 ? h('p', { class: 'footnote' }, `${state.archived} older ${plural(state.archived, 'ticket')} archived by the ledger are not shown.`) : null,
  );
}
