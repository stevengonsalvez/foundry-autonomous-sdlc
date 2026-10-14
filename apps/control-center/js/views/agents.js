// #/agents  The agents, what each is doing, what it cost, and whether it is healthy.

import { badge, emptyState, h, panel, table, timeEl } from '../dom.js';
import { formatDuration, formatInteger, formatUsd, parseTime, plural } from '../format.js';
import { pageHead, issueNumberLink } from './common.js';

const STATE = {
  running: ['Running', 'Working on a ticket right now.'],
  idle: ['Idle', 'Healthy and waiting for work.'],
  error: ['Error', 'Its last call failed. See the error below.'],
  stale: ['Stale', 'No tick for more than 10 minutes. The orchestrator may not be running.'],
  unknown: ['Unknown', 'Not enough data yet: it has not been called.'],
};

export const stateLabel = (state) => (STATE[state] ?? STATE.unknown)[0];

function stateChip(state) {
  const [label, hint] = STATE[state] ?? STATE.unknown;
  return h('span', { class: `state state-${state}`, title: hint }, h('span', { class: 'state-dot', 'aria-hidden': 'true' }), label);
}

function stat(label, value, sub) {
  return h('div', { class: 'stat' }, h('dt', null, label), h('dd', null, value, sub ? h('span', { class: 'muted stat-sub' }, ` ${sub}`) : null));
}

function agentRow(agent, now, tickets) {
  const known = (n) => n !== null && tickets.has(n);
  const isError = agent.state === 'error' || Boolean(agent.last_error);

  const stateCell = h('td', null, stateChip(agent.state));

  const nameCell = h(
    'td',
    null,
    h('span', { class: 'agent-name font-mono strong' }, agent.name),
    agent.role ? h('div', { class: 'agent-role muted text-xs clamp-1' }, agent.role) : null,
  );

  const activeCell = h('td', { class: 'num' }, agent.last_active_at ? timeEl(agent.last_active_at, now) : 'never');

  const callsCell = h(
    'td',
    { class: 'num' },
    formatInteger(agent.calls_total),
    agent.calls_last_tick > 0 ? h('span', { class: 'muted text-xs' }, ` (+${agent.calls_last_tick})`) : null,
  );

  const tokensInCell = h('td', { class: 'num' }, formatInteger(agent.tokens_in));
  const tokensOutCell = h('td', { class: 'num' }, formatInteger(agent.tokens_out));
  const spendCell = h('td', { class: 'num' }, formatUsd(agent.usd));

  const errorsCell = h(
    'td',
    null,
    h('span', { class: agent.errors > 0 ? 'tone-bad strong num' : 'num' }, formatInteger(agent.errors)),
    agent.last_error
      ? h(
          'div',
          { class: 'agent-error', role: 'group', 'aria-label': 'Last error' },
          h('span', { class: 'error-detail' }, agent.last_error.detail || 'Error'),
        )
      : null,
  );

  const workingCell = h(
    'td',
    null,
    agent.current_object !== null
      ? known(agent.current_object)
        ? issueNumberLink(agent.current_object)
        : h('span', null, `#${agent.current_object}`)
      : h('span', { class: 'muted' }, '-'),
  );

  return h(
    'tr',
    {
      class: `agent agent-${agent.state}${isError ? ' is-error' : ''}`,
      'aria-label': agent.name,
    },
    stateCell,
    nameCell,
    activeCell,
    callsCell,
    tokensInCell,
    tokensOutCell,
    spendCell,
    errorsCell,
    workingCell,
  );
}

function agentsTable(agents, now, tickets) {
  return h(
    'section',
    { class: 'panel', 'aria-label': 'Fleet agents table' },
    h(
      'div',
      { class: 'table-wrap' },
      h(
        'table',
        { class: 'data' },
        h(
          'thead',
          null,
          h(
            'tr',
            null,
            h('th', null, 'State'),
            h('th', null, 'Agent'),
            h('th', null, 'Last active'),
            h('th', { class: 'num' }, 'Calls'),
            h('th', { class: 'num' }, 'Tokens in'),
            h('th', { class: 'num' }, 'Tokens out'),
            h('th', { class: 'num' }, 'Spend'),
            h('th', null, 'Errors'),
            h('th', null, 'Working on'),
          ),
        ),
        h('tbody', null, ...agents.map((a) => agentRow(a, now, tickets))),
      ),
    ),
  );
}

function tickStrip(state, now) {
  const { ledger } = state;
  const tick = ledger.last_tick;
  const duration = tick?.started_at && tick?.finished_at ? (parseTime(tick.finished_at) - parseTime(tick.started_at)) / 1000 : null;
  return h(
    'section',
    { class: 'panel strip', 'aria-label': 'Orchestrator tick and ledger' },
    h(
      'dl',
      { class: 'stats stats-strip' },
      stat('Last tick', tick?.finished_at ? timeEl(tick.finished_at, now) : 'none yet'),
      stat('Tick took', duration === null ? '-' : formatDuration(duration)),
      stat('Lock', tick?.lock ?? '-'),
      stat('Objects handled', tick ? formatInteger(tick.objects.length) : '-'),
      stat('Model calls', tick ? formatInteger(tick.model_calls) : '-', tick ? formatUsd(tick.usd_this_tick) : ''),
      stat('Ledger mode', badge(ledger.mode === 'hosted' ? 'Hosted' : ledger.mode === 'inline' ? 'Inline' : ledger.mode, 'info')),
      stat('Ledger events', formatInteger(ledger.events), ledger.last_ingest_at ? '' : ''),
      stat('Last ingest', ledger.last_ingest_at ? timeEl(ledger.last_ingest_at, now) : '-'),
    ),
  );
}

export const RESULT_TONE = Object.freeze({ ok: 'good', error: 'bad', deferred: 'warn', capped: 'warn' });

function tickObjects(state) {
  const tick = state.ledger.last_tick;
  if (!tick || tick.objects.length === 0) return null;
  const known = new Set(state.tickets.map((t) => t.issue));
  return panel(
    { id: 'tick-objects', title: 'Last tick', lede: 'What the orchestrator did on its most recent pass.' },
    table({
      caption: 'Objects handled in the last orchestrator tick',
      head: ['Ticket', 'Kind', 'Action', 'Result'],
      rows: tick.objects.map((o) => [o.number === null ? '-' : known.has(o.number) ? issueNumberLink(o.number) : `#${o.number}`, o.kind, h('code', null, o.action), badge(o.result || 'unknown', RESULT_TONE[o.result] ?? 'neutral')]),
    }),
  );
}

function notices(state, now) {
  const list = state.ledger.errors;
  if (list.length === 0) return null;
  return panel(
    { id: 'notices', title: 'Ledger notices', lede: 'Messages the ledger recorded about itself.' },
    h('ul', { class: 'notices' }, ...list.map((e) => h('li', null, e.at ? timeEl(e.at, now) : null, h('span', { class: 'clamp-3 wrap' }, e.message)))),
  );
}

export function renderAgents(ctx) {
  const { state, now } = ctx;
  const agents = state.agents;
  if (agents.length === 0) {
    return h('div', { class: 'view' }, pageHead({ title: 'Agents' }), emptyState('No agent data yet', 'The ledger has not reported on the agents. They appear after the first orchestrator tick.'));
  }
  const counts = {};
  for (const a of agents) counts[a.state] = (counts[a.state] ?? 0) + 1;
  const summary = Object.entries(counts)
    .map(([k, n]) => `${n} ${stateLabel(k).toLowerCase()}`)
    .join(', ');
  const tickets = new Set(state.tickets.map((t) => t.issue));
  return h(
    'div',
    { class: 'view' },
    pageHead({ title: 'Agents', lede: `${agents.length} ${plural(agents.length, 'agent')}: ${summary}. State is always written out, never colour alone.` }),
    tickStrip(state, now),
    agentsTable(agents, now, tickets),
    tickObjects(state),
    notices(state, now),
  );
}
