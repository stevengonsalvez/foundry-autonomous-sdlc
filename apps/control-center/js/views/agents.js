// #/agents  The agents, what each is doing, what it cost, and whether it is healthy.

import { badge, emptyState, h, panel, table, timeEl } from '../dom.js';
import { formatDuration, formatInteger, formatUsd, parseTime, plural } from '../format.js';
import { icon } from '../icons.js';
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
  return h(
    'span',
    { class: `state state-${state}`, title: hint },
    h('span', { class: 'state-dot', 'aria-hidden': 'true' }),
    label,
  );
}

function stat(label, value, sub, tone = '') {
  return h(
    'div',
    { class: `stat ${tone}`.trim() },
    h('dt', null, label),
    h('dd', null, value, sub ? h('span', { class: 'muted stat-sub' }, ` ${sub}`) : null),
  );
}

function agentCard(agent, now, tickets) {
  const known = (n) => n !== null && tickets.has(n);
  return h(
    'article',
    { class: `agent agent-${agent.state}`, 'aria-label': agent.name },
    h(
      'header',
      { class: 'agent-head' },
      h(
        'div',
        { class: 'agent-identity' },
        h('h3', { class: 'agent-name' }, h('code', null, agent.name)),
        agent.kind ? h('span', { class: 'agent-kind' }, agent.kind) : null,
      ),
      stateChip(agent.state),
    ),
    h('p', { class: 'agent-role clamp-2' }, agent.role || 'No description recorded.'),
    h(
      'dl',
      { class: 'stats stats-agent' },
      stat('Last active', agent.last_active_at ? timeEl(agent.last_active_at, now) : 'never'),
      stat('Calls', formatInteger(agent.calls_total), agent.calls_last_tick > 0 ? `${agent.calls_last_tick} last tick` : ''),
      stat('Tokens in', formatInteger(agent.tokens_in)),
      stat('Tokens out', formatInteger(agent.tokens_out)),
      stat('Spend', formatUsd(agent.usd)),
      stat('Errors', formatInteger(agent.errors), `${formatInteger(agent.retries)} ${agent.retries === 1 ? 'retry' : 'retries'}`),
    ),
    h(
      'div',
      { class: 'agent-line agent-task' },
      h('span', { class: 'label' }, 'Working on'),
      agent.current_object !== null
        ? (known(agent.current_object) ? issueNumberLink(agent.current_object) : h('span', null, `#${agent.current_object}`))
        : h('span', { class: 'muted' }, 'nothing'),
    ),
    agent.lock_holder
      ? h('div', { class: 'agent-line agent-lock' }, h('span', { class: 'label' }, 'Lock'), h('span', { class: 'clamp-1 wrap' }, agent.lock_holder))
      : null,
    agent.last_error
      ? h(
          'div',
          { class: 'agent-error', role: 'group', 'aria-label': 'Last error' },
          h(
            'div',
            { class: 'agent-error-meta' },
            h('span', { class: 'agent-error-icon' }, icon('alert', { size: 13 })),
            h(
              'p',
              { class: 'label' },
              'Last error',
              agent.last_error.at ? [' ', timeEl(agent.last_error.at, now)] : null,
              agent.last_error.result ? [' ', badge(agent.last_error.result, 'warn')] : null,
              agent.last_error.object !== null ? [' on ', issueNumberLink(agent.last_error.object)] : null,
            ),
          ),
          h('p', { class: 'agent-error-detail clamp-3 wrap' }, agent.last_error.detail || 'No detail recorded.'),
        )
      : null,
  );
}

function tickStrip(state, now) {
  const { ledger } = state;
  const tick = ledger.last_tick;
  const duration = tick?.started_at && tick?.finished_at ? (parseTime(tick.finished_at) - parseTime(tick.started_at)) / 1000 : null;
  return h(
    'section',
    { class: 'panel strip agent-strip', 'aria-label': 'Orchestrator heartbeat and ledger summary' },
    h(
      'dl',
      { class: 'stats stats-strip' },
      stat('Last tick', tick?.finished_at ? timeEl(tick.finished_at, now) : 'none yet'),
      stat('Tick took', duration === null ? '-' : formatDuration(duration)),
      stat('Lock status', tick?.lock ?? '-'),
      stat('Objects handled', tick ? formatInteger(tick.objects.length) : '-'),
      stat('Model calls', tick ? formatInteger(tick.model_calls) : '-', tick && tick.usd_this_tick > 0 ? formatUsd(tick.usd_this_tick) : ''),
      stat('Ledger mode', badge(ledger.mode === 'hosted' ? 'Hosted' : ledger.mode === 'inline' ? 'Inline' : ledger.mode, 'info')),
      stat('Ledger events', formatInteger(ledger.events)),
      stat('Last ingest', ledger.last_ingest_at ? timeEl(ledger.last_ingest_at, now) : '-'),
    ),
  );
}

const RESULT_TONE = { ok: 'good', error: 'bad', deferred: 'warn', capped: 'warn' };

function tickObjects(state) {
  const tick = state.ledger.last_tick;
  if (!tick || tick.objects.length === 0) return null;
  const known = new Set(state.tickets.map((t) => t.issue));
  return panel(
    { id: 'tick-objects', title: 'Last tick activity', lede: 'What the orchestrator did on its most recent pass.' },
    table({
      caption: 'Objects handled in the last orchestrator tick',
      head: ['Ticket', 'Kind', 'Action', 'Result'],
      rows: tick.objects.map((o) => [
        o.number === null ? '-' : known.has(o.number) ? issueNumberLink(o.number) : `#${o.number}`,
        h('span', { class: `kind-chip kind-${o.kind}` }, o.kind),
        h('code', null, o.action),
        badge(o.result || 'unknown', RESULT_TONE[o.result] ?? 'neutral'),
      ]),
    }),
  );
}

function notices(state, now) {
  const list = state.ledger.errors;
  if (list.length === 0) return null;
  return panel(
    { id: 'notices', title: 'Ledger notices', lede: 'Messages the ledger recorded about itself.' },
    h(
      'ul',
      { class: 'notices' },
      ...list.map((e) =>
        h(
          'li',
          { class: 'notice-item' },
          e.at ? timeEl(e.at, now) : null,
          h('span', { class: 'notice-text clamp-3 wrap' }, e.message),
        ),
      ),
    ),
  );
}

export function renderAgents(ctx) {
  const { state, now } = ctx;
  const agents = state.agents;
  if (agents.length === 0) {
    return h(
      'div',
      { class: 'view' },
      pageHead({ title: 'Agents' }),
      emptyState(
        'No agent data yet',
        'The ledger has not reported on the agents. They appear after the first orchestrator tick.',
      ),
    );
  }
  const counts = {};
  for (const a of agents) counts[a.state] = (counts[a.state] ?? 0) + 1;
  const summary = Object.entries(counts)
    .map(([k, n]) => `${n} ${stateLabel(k).toLowerCase()}`)
    .join(', ');
  const tickets = new Set(state.tickets.map((t) => t.issue));
  return h(
    'div',
    { class: 'view view-agents' },
    pageHead({
      title: 'Agents',
      lede: `${agents.length} ${plural(agents.length, 'agent')}: ${summary}. State is always written out, never colour alone.`,
    }),
    tickStrip(state, now),
    h('div', { class: 'agent-grid' }, ...agents.map((a) => agentCard(a, now, tickets))),
    tickObjects(state),
    notices(state, now),
  );
}
