// #/  Delivery flow board: lane by stage matrix, macrobands, mode badges, pill chips, lens and group toggles.

import { badge, emptyState, ghLink, h } from '../dom.js';
import { formatInteger, formatUsd, plural } from '../format.js';
import { icon } from '../icons.js';
import { boardColumns, boardSummary, emptyFilters, typesPresent, timeInStage } from '../model.js';
import { NEW_BUG_URL, NEW_TICKET_URL, limitText } from '../safe.js';
import { ui } from '../ui.js';
import {
  agentTag,
  envBadgeFor,
  externalLabel,
  flagBadges,
  modeBadge,
  pageHead,
  segmentedControl,
  sinceEl,
  ticketGithubUrl,
  ticketHref,
} from './common.js';

// Macrobands grouping stages into lifecycle domains
const MACROBANDS = Object.freeze([
  { id: 'shape', label: 'ALIGN . PRODUCT', span: 3, tone: 'wait' },
  { id: 'build', label: 'IMPLEMENT . CODE', span: 3, tone: 'run' },
  { id: 'release', label: 'DELIVER . OPERATIONS', span: 2, tone: 'done' },
  { id: 'escalated', label: 'EXCEPTIONS', span: 1, tone: 'block' },
]);

/**
 * Pipeline stage execution modes (design-time architecture specification):
 * - AUTO: Autonomous engine loop execution (backlog intake, feasible evaluation, code build, prod publish).
 * - SIM: Simulated human interaction gate (requirements refinement with simulated user/PO).
 * - GATE: Quality and safety verification barrier (test designer gate, code review gate, smoke/staging gate, escalation gate).
 */
const STAGE_MODES = Object.freeze({
  backlog: 'AUTO',
  refining: 'SIM',
  feasible: 'AUTO',
  tests: 'GATE',
  building: 'AUTO',
  review: 'GATE',
  staging: 'GATE',
  prod: 'AUTO',
  escalated: 'GATE',
});

function getTicketAgent(ticket) {
  if (ticket.coder?.job_id) return 'sdlc-coder';
  if (ticket.agent_runs && ticket.agent_runs.length > 0) {
    return ticket.agent_runs.at(-1).agent;
  }
  return null;
}

function ticketChip(ticket, nowMs, lens) {
  const inStage = timeInStage(ticket, nowMs);
  const agentName = getTicketAgent(ticket);
  const tag = agentTag(agentName);

  let stateTone = 'active';
  if (ticket.pending) stateTone = 'pending';
  else if (ticket.stage === 'escalated' || ticket.flags.includes('deploy-failed') || ticket.flags.includes('rolled-back')) stateTone = 'blocked';
  else if (ticket.stage === 'backlog' || ticket.flags.includes('waiting-for-ledger')) stateTone = 'wait';
  else if (ticket.stage === 'prod') stateTone = 'done';

  const link = ticket.pending
    ? ghLink(ticketGithubUrl(ticket), [ticket.title || 'Untitled', icon('external', { size: 12, className: 'icon-ext' })], { class: 'card-link clamp-1' })
    : h('a', { class: 'card-link clamp-1', href: ticketHref(ticket.issue), 'data-fkey': `t${ticket.issue}` }, ticket.title || 'Untitled');

  const stateGlyphs = {
    active: '',
    pending: '◌',
    wait: '·',
    blocked: '!',
    done: '✓',
  };
  const chipNum = h('span', { class: 'chip-num' }, ticket.kind === 'pr' ? `PR #${ticket.issue}` : `#${ticket.issue}`);
  const chipDot = h('span', { class: `chip-dot dot-${stateTone}`, 'aria-hidden': 'true', title: stateTone }, stateGlyphs[stateTone]);
  const chipAgent = h('span', { class: 'chip-agent', title: agentName || 'unassigned' }, tag);

  let lensContent = null;
  if (lens === 'cost') {
    const usdText = formatUsd(ticket.cost?.usd ?? 0);
    const pct = Math.min(100, Math.round(ticket.cost?.cap_used_pct ?? 0));
    lensContent = h(
      'span',
      { class: 'chip-lens chip-cost', title: `${usdText} (${pct}% of cap)` },
      h('span', { class: 'chip-cost-val' }, usdText),
      h('span', { class: 'chip-cost-track', 'aria-hidden': 'true' }, h('span', { class: 'chip-cost-bar', vars: { pct: `${pct}%` } })),
    );
  } else if (lens === 'gates') {
    const gates = ticket.gates || {};
    const passCount = Object.values(gates).filter((v) => v === 'success').length;
    const totalGates = Object.keys(gates).length;
    lensContent = h(
      'span',
      { class: 'chip-lens chip-gates', title: `${passCount}/${totalGates} gates passed` },
      h('span', { class: 'chip-gate-verdict' }, totalGates > 0 ? `${passCount}/${totalGates}` : 'none'),
    );
  } else {
    // Delivery lens: time in stage
    lensContent = h('span', { class: 'chip-lens chip-time' }, sinceEl(inStage.since, nowMs));
  }

  const flags = flagBadges(ticket.flags);
  const envB = envBadgeFor(ticket);
  const extraBadges = envB ? [envB, ...flags] : flags;

  const pill = h(
    'div',
    { class: `chip-pill card-${stateTone}${ticket.pending ? ' card-pending' : ''}` },
    h('div', { class: 'chip-head' }, chipNum, chipDot, chipAgent, lensContent),
    h('div', { class: 'chip-body' }, link),
  );

  return h(
    'article',
    {
      class: 'card',
      'data-stage': ticket.stage,
      title: `#${ticket.issue}: ${ticket.title || 'Untitled'} (${ticket.stage})`,
    },
    pill,
    extraBadges.length > 0 ? h('div', { class: 'chip-tags' }, ...extraBadges) : null,
  );
}

function computeStageCounts(tickets) {
  let inCount = 0;
  let waitCount = 0;
  let blockedCount = 0;
  for (const t of tickets) {
    if (t.stage === 'escalated' || t.flags.includes('deploy-failed')) blockedCount++;
    else if (t.stage === 'backlog' || t.pending || t.flags.includes('waiting-for-ledger')) waitCount++;
    else inCount++;
  }
  return { inCount, waitCount, blockedCount };
}

function getLaneKeys(group, tickets) {
  if (group === 'agent') {
    const set = new Set();
    for (const t of tickets) {
      const a = getTicketAgent(t);
      if (a) set.add(a);
    }
    const lanes = [...set].sort().map((agent) => ({
      key: agent,
      label: agent.replace(/^sdlc-/, '').toUpperCase(),
      sub: agentTag(agent),
      tone: 'agent',
    }));
    // Always include an unassigned lane so unassigned and pending tickets are never dropped
    lanes.push({
      key: 'unassigned',
      label: 'UNASSIGNED',
      sub: 'triage/wait',
      tone: 'wait',
    });
    return lanes;
  }
  if (group === 'outcome') {
    return [
      { key: 'in-flight', label: 'IN FLIGHT', sub: 'active', tone: 'run' },
      { key: 'shipped', label: 'SHIPPED', sub: 'production', tone: 'done' },
      { key: 'escalated', label: 'ESCALATED', sub: 'blocked', tone: 'block' },
    ];
  }
  // Default: Type - includes Other so unclassified tickets are never omitted
  return [
    { key: 'feature', label: 'FEATURE', sub: 'user value', tone: 'info' },
    { key: 'bug', label: 'BUG', sub: 'defect repair', tone: 'block' },
    { key: 'maintenance', label: 'MAINTENANCE', sub: 'platform', tone: 'wait' },
    { key: 'other', label: 'OTHER', sub: 'unclassified', tone: 'agent' },
  ];
}

function ticketMatchesLane(ticket, laneKey, group) {
  if (group === 'agent') {
    const a = getTicketAgent(ticket);
    if (laneKey === 'unassigned') return !a;
    return a === laneKey;
  }
  if (group === 'outcome') {
    if (laneKey === 'shipped') return ticket.stage === 'prod';
    if (laneKey === 'escalated') return ticket.stage === 'escalated';
    return ticket.stage !== 'prod' && ticket.stage !== 'escalated';
  }
  // Group: Type
  if (laneKey === 'other') return ticket.type !== 'feature' && ticket.type !== 'bug' && ticket.type !== 'maintenance';
  return ticket.type === laneKey;
}

function isStageApplicable(stage, laneKey, group) {
  if (group === 'outcome') {
    if (laneKey === 'shipped') return stage === 'prod';
    if (laneKey === 'escalated') return stage === 'escalated';
    return stage !== 'prod' && stage !== 'escalated';
  }
  if (group === 'type') {
    // Maintenance skips requirements refinement and feasibility
    if (laneKey === 'maintenance' && (stage === 'refining' || stage === 'feasible')) return false;
  }
  return true;
}

function matrixCell(stage, lane, tickets, nowMs, lens, group) {
  const laneKey = lane.key;
  const laneTickets = tickets.filter((t) => ticketMatchesLane(t, laneKey, group));
  const applicable = isStageApplicable(stage, laneKey, group);
  // Never swallow real tickets that exist in an out-of-pipeline stage
  if (!applicable && laneTickets.length === 0) {
    return h(
      'div',
      { class: 'matrix-cell cell-hatched', 'data-lane': laneKey, role: 'cell' },
      h('span', { class: 'cell-hatched-label' }, 'bypasses stage'),
    );
  }

  const mobileLaneTag = h('div', { class: 'cell-lane-label', 'aria-hidden': 'true' }, h('span', { class: `lane-dot dot-${lane.tone}` }), lane.label);

  const cell = h(
    'div',
    {
      class: `matrix-cell${laneTickets.length === 0 ? ' cell-empty' : ''}${!applicable ? ' cell-bypass' : ''}`,
      'data-lane': laneKey,
      role: 'cell',
    },
    mobileLaneTag,
    ...laneTickets.map((t) => ticketChip(t, nowMs, lens)),
  );
  return cell;
}

function stageColumn(col, nowMs, filtered, lens, group, lanes) {
  const quiet = col.tickets.length === 0;
  const countText = filtered && col.total !== col.tickets.length ? `${col.tickets.length} of ${col.total}` : String(col.tickets.length);
  const mode = STAGE_MODES[col.stage] ?? 'AUTO';
  const { inCount, waitCount, blockedCount } = computeStageCounts(col.tickets);

  let telemetryText = `${inCount} in . ${waitCount} wait . ${blockedCount} blk`;
  if (lens === 'cost') {
    const stageUsd = col.tickets.reduce((sum, t) => sum + (t.cost?.usd ?? 0), 0);
    telemetryText = formatUsd(stageUsd);
  } else if (lens === 'gates') {
    const totalG = col.tickets.reduce((sum, t) => sum + Object.keys(t.gates || {}).length, 0);
    const passG = col.tickets.reduce((sum, t) => sum + Object.values(t.gates || {}).filter((v) => v === 'success').length, 0);
    const rate = totalG > 0 ? Math.round((passG / totalG) * 100) : 100;
    telemetryText = `${rate}% pass`;
  }

  const cells = lanes.map((lane) => matrixCell(col.stage, lane, col.tickets, nowMs, lens, group));

  return h(
    'section',
    { class: `col col-${col.stage}${quiet ? ' col-quiet' : ''}`, role: 'row', 'data-stage': col.stage },
    h(
      'header',
      { class: 'col-head', role: 'columnheader' },
      h(
        'div',
        { class: 'col-head-top' },
        h(
          'div',
          { class: 'col-title-group' },
          h('h2', { id: `col-${col.stage}`, class: 'col-title' }, col.label),
          modeBadge(mode),
        ),
        h('span', { class: 'col-count', title: `${col.tickets.length} shown, ${col.total} in this stage` }, countText),
      ),
      h('div', { class: 'stage-telemetry', title: telemetryText }, telemetryText),
    ),
    h('div', { class: 'col-cells', role: 'presentation' }, ...cells),
  );
}

function macrobandStrip() {
  return h(
    'div',
    { class: 'band-strip', 'aria-hidden': 'true' },
    h('div', { class: 'band-spacer' }),
    ...MACROBANDS.map((mb) =>
      h(
        'div',
        { class: `band-cell band-${mb.id}`, 'data-band': mb.id },
        h('span', { class: 'band-label' }, mb.label),
      ),
    ),
  );
}

function laneSpine(lanes) {
  return h(
    'div',
    { class: 'matrix-spine', role: 'row' },
    h('div', { class: 'spine-head', role: 'columnheader' }, h('span', { class: 'spine-label' }, 'SWIMLANE')),
    ...lanes.map((l) =>
      h(
        'div',
        { class: 'lane-head', id: `lane-${l.key}`, 'data-lane': l.key, role: 'rowheader' },
        h('span', { class: `lane-dot dot-${l.tone}`, 'aria-hidden': 'true' }),
        h('span', { class: 'lane-name' }, l.label),
        h('span', { class: 'lane-sub' }, l.sub),
      ),
    ),
  );
}

function summaryLine(ctx) {
  const { state, pending } = ctx;
  const sum = boardSummary(state, pending);
  const totals = state.cost.totals;
  const billed = state.cost.billing?.billed_usd ?? null;

  return h(
    'div',
    { class: 'delivery-stat-line' },
    h('span', { class: 'stat-item' }, h('strong', null, formatInteger(sum.total)), ' tickets'),
    h('span', { class: 'stat-sep' }, '.'),
    h('span', { class: 'stat-item' }, h('strong', null, formatInteger(sum.inFlight)), ' in flight'),
    h('span', { class: 'stat-sep' }, '.'),
    h('span', { class: 'stat-item tone-good' }, h('strong', null, formatInteger(sum.prod)), ' in production'),
    h('span', { class: 'stat-sep' }, '.'),
    h('span', { class: `stat-item${sum.escalated > 0 ? ' tone-bad' : ''}` }, h('strong', null, formatInteger(sum.escalated)), ' escalated'),
    h('span', { class: 'stat-sep' }, '.'),
    h('span', { class: 'stat-item' }, formatUsd(totals.usd), ' ledger'),
    h('span', { class: 'stat-sep' }, '.'),
    h('span', { class: `stat-item${billed !== null && totals.halted ? ' tone-bad' : ''}` }, billed === null ? 'bill pending' : `${formatUsd(billed)} azure`),
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

  const hideOld = h('input', { id: 'board-hide-old', type: 'checkbox', class: 'switch-input', checked: filters.hideOld });
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
    { class: 'toolbar', role: 'search' },
    h('div', { class: 'chip-group', role: 'group', 'aria-label': 'Filter by type' }, ...chips),
    h('div', { class: 'search-field' }, icon('search', { size: 14 }), h('label', { class: 'sr-only', for: 'board-search' }, 'Search by ticket number or title'), search),
    h('label', { class: 'switch', for: 'board-hide-old' }, hideOld, h('span', { class: 'switch-track', 'aria-hidden': 'true' }), h('span', null, 'Hide finished older than 7 days')),
    clear,
  );
}

export function renderBoard(ctx) {
  const { state, pending, now } = ctx;
  const filters = ui.board;
  const lens = filters.lens || 'delivery';
  const group = filters.group || 'type';

  const boardShell = h('div', { class: 'board-shell' });
  const boardMatrix = h('div', { class: 'board matrix-grid', role: 'grid', 'aria-label': 'Delivery flow matrix board, scrolls sideways', tabindex: '0' });
  const result = h('p', { class: 'sr-only', 'aria-live': 'polite', role: 'status' });

  const isFiltered = () => filters.types.size > 0 || filters.query.trim() !== '' || filters.hideOld;

  const update = () => {
    const columns = boardColumns(state, pending, filters, now);
    const lanes = getLaneKeys(ui.board.group || 'type', state.tickets);

    const stageCols = columns.map((c) => stageColumn(c, now, isFiltered(), ui.board.lens || 'delivery', ui.board.group || 'type', lanes));

    boardMatrix.replaceChildren(laneSpine(lanes), ...stageCols);

    const shown = columns.reduce((n, c) => n + c.tickets.length, 0);
    result.textContent = `${shown} ${plural(shown, 'ticket')} shown`;
  };

  const lensControl = segmentedControl(
    [
      { value: 'delivery', label: 'Delivery' },
      { value: 'cost', label: 'Cost' },
      { value: 'gates', label: 'Gates' },
    ],
    lens,
    (nextLens) => {
      filters.lens = nextLens;
      ctx.rerender();
    },
    'Lens',
  );

  const groupControl = segmentedControl(
    [
      { value: 'type', label: 'Type' },
      { value: 'agent', label: 'Agent' },
      { value: 'outcome', label: 'Outcome' },
    ],
    group,
    (nextGroup) => {
      filters.group = nextGroup;
      ctx.rerender();
    },
    'Swimlane group',
  );

  const viewControls = h(
    'div',
    { class: 'matrix-controls' },
    h('div', { class: 'ctrl-group' }, h('span', { class: 'ctrl-label' }, 'lens:'), lensControl),
    h('div', { class: 'ctrl-group' }, h('span', { class: 'ctrl-label' }, 'group:'), groupControl),
  );

  const bar = toolbar(ctx, update);
  update();

  const actions = [
    viewControls,
    ghLink(NEW_TICKET_URL, [icon('plus', { size: 16 }), 'New ticket'], { class: 'btn btn-primary' }),
    ghLink(NEW_BUG_URL, [icon('bug', { size: 16 }), 'Report a bug'], { class: 'btn btn-secondary' }),
  ];

  if (state.tickets.length === 0 && pending.length === 0) {
    return h(
      'div',
      { class: 'view' },
      pageHead({ title: 'Delivery flow', lede: 'Every ticket from backlog to production.', actions }),
      emptyState(
        'No tickets yet',
        'The board fills as soon as the first issue is opened. Creating a ticket on GitHub is the only way to start one.',
        ghLink(NEW_TICKET_URL, externalLabel('Open a ticket'), { class: 'btn btn-primary' }),
      ),
    );
  }

  const ticketCount = state.tickets.length + pending.length;
  const agentCount = state.agents?.length ?? 0;
  const subLine = agentCount > 0 ? `${ticketCount} tickets, ${agentCount} agents` : `${ticketCount} tickets`;

  boardShell.replaceChildren(macrobandStrip(), boardMatrix);

  return h(
    'div',
    { class: 'view view-board' },
    pageHead({ title: 'Delivery flow', lede: subLine, actions }),
    summaryLine(ctx),
    bar,
    result,
    boardShell,
    state.dropped > 0 ? h('p', { class: 'footnote' }, badge(`${state.dropped} unreadable`, 'warn'), ' ', `${state.dropped} ${plural(state.dropped, 'entry', 'entries')} in state.json could not be read and were skipped.`) : null,
    state.archived > 0 ? h('p', { class: 'footnote' }, `${state.archived} older ${plural(state.archived, 'ticket')} archived by the ledger are not shown.`) : null,
  );
}
