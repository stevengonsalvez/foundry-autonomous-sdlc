// #/flow  How work moves: time in stage, lead time, change failure, work in progress, gates, defects
// and cost against the cap. Every chart has a table behind it.

import { barChart, dotStrip, rateChart, releaseStrip, stackedStageChart } from '../charts.js';
import { badge, chartHost, dataTable, emptyState, h, panel, table } from '../dom.js';
import { formatDuration, formatInteger, formatPercent, formatUsd, parseTime, plural } from '../format.js';
import { costBand, costRows, SCENARIO_NOTES, scenarioRows, stageDurations, stageLabel } from '../model.js';
import { issueNumberLink, pageHead, stageFill } from './common.js';
import { outcomeBadge } from './environments.js';

const TOP = 25;
const TERMINAL = new Set(['prod', 'escalated']);

function kpi(label, value, tone = '') {
  return h('div', { class: `kpi ${tone}`.trim() }, h('dt', null, label), h('dd', null, value));
}

function stageSeries(state, now) {
  const perTicket = state.tickets
    .map((t) => {
      const segments = stageDurations(t, now)
        .filter((d) => !TERMINAL.has(d.stage) && (d.seconds > 0 || d.open))
        .map((d) => ({ stage: d.stage, seconds: d.seconds, open: d.open }));
      return { ticket: t, segments, total: segments.reduce((n, s) => n + s.seconds, 0) };
    })
    .filter((r) => r.segments.length > 0)
    .sort((a, b) => (parseTime(b.ticket.updated_at ?? '') ?? 0) - (parseTime(a.ticket.updated_at ?? '') ?? 0));
  const counts = new Map();
  for (const row of perTicket) for (const s of row.segments) if (!s.open) counts.set(s.stage, (counts.get(s.stage) ?? 0) + 1);
  return { perTicket, counts };
}

function cyclePanel(state, now) {
  const medians = state.flow.stage_medians_s;
  const { perTicket, counts } = stageSeries(state, now);
  const stages = state.board_stages.filter((s) => medians[s] !== undefined);
  const shown = perTicket.slice(0, TOP);
  const maxTotal = Math.max(...shown.map((r) => r.total), 1);
  const medianRows = stages.map((s) => ({ label: stageLabel(s), value: medians[s], text: formatDuration(medians[s]), sub: `n=${counts.get(s) ?? 0}`, cls: `${stageFill(s)}` }));
  const present = [...new Set(shown.flatMap((r) => r.segments.map((s) => s.stage)))];
  return panel(
    { id: 'cycle', title: 'Cycle time per stage', lede: 'Median time a ticket spends in each stage, then one bar per ticket. Stages still running are drawn faded and left out of the medians.', className: 'panel-wide' },
    stages.length === 0 ? h('p', { class: 'muted' }, 'No finished stages yet.') : chartHost((width) => barChart(width, medianRows, { label: `Median time per stage: ${medianRows.map((r) => `${r.label} ${r.text}`).join(', ')}`, labelChars: 14 })),
    shown.length === 0
      ? null
      : [
          h('h3', null, `Per ticket${perTicket.length > shown.length ? ` (the ${shown.length} most recently updated of ${perTicket.length})` : ''}`),
          chartHost((width) =>
            stackedStageChart(
              width,
              shown.map((r) => ({ label: `#${r.ticket.issue} ${r.ticket.title}`, segments: r.segments, total: r.total })),
              { label: 'Time per stage for each ticket', maxTotal, stageClass: stageFill },
            ),
          ),
          h('ul', { class: 'legend' }, ...present.map((s) => h('li', null, h('span', { class: `swatch ${stageFill(s).replace('st-fill-', 'st-bg-')}`, 'aria-hidden': 'true' }), stageLabel(s)))),
          dataTable(
            'Show cycle time as a table',
            table({
              caption: 'Time in each stage per ticket',
              head: ['Ticket', ...stages.map(stageLabel), 'Total'],
              numeric: stages.map((_, i) => i + 1).concat(stages.length + 1),
              rows: shown.map((r) => [
                issueNumberLink(r.ticket.issue),
                ...stages.map((s) => {
                  const seg = r.segments.filter((x) => x.stage === s);
                  return seg.length ? formatDuration(seg.reduce((n, x) => n + x.seconds, 0)) : '-';
                }),
                formatDuration(r.total),
              ]),
            }),
          ),
        ],
  );
}

function leadPanel(state) {
  const lead = state.flow.lead_time;
  const points = lead.by_ticket.map((p) => ({ label: `#${p.issue}`, value: p.seconds }));
  return panel(
    { id: 'lead', title: 'Lead time, issue to production', lede: 'From opening the issue to its first successful production deploy.' },
    h('dl', { class: 'kpis kpis-small' }, kpi('Median', lead.median_s === null ? '-' : formatDuration(lead.median_s)), kpi('Tickets in production', formatInteger(points.length))),
    points.length === 0
      ? h('p', { class: 'muted' }, 'Nothing has reached production yet.')
      : [
          chartHost((width) => dotStrip(width, points, { median: lead.median_s, label: `Lead time per ticket, median ${lead.median_s === null ? 'unknown' : formatDuration(lead.median_s)}` })),
          dataTable('Show lead times as a table', table({ caption: 'Lead time per ticket', head: ['Ticket', 'Lead time'], numeric: [1], rows: lead.by_ticket.map((p) => [issueNumberLink(p.issue), formatDuration(p.seconds)]) })),
        ],
  );
}

function changeFailurePanel(state) {
  const cf = state.flow.change_failure;
  const releases = [...cf.per_release].sort((a, b) => (parseTime(a.at ?? '') ?? 0) - (parseTime(b.at ?? '') ?? 0));
  return panel(
    { id: 'change-failure', title: 'Change failure rate', lede: 'Share of finished releases that were rolled back. Skipped and pending builds are not counted.' },
    h('dl', { class: 'kpis kpis-small' }, kpi('Failure rate', cf.rate === null ? 'n/a' : formatPercent(cf.rate), cf.rate > 0 ? 'kpi-bad' : ''), kpi('Failed', `${formatInteger(cf.failed)} of ${formatInteger(cf.releases)}`)),
    releases.length === 0
      ? h('p', { class: 'muted' }, 'No releases yet.')
      : [
          chartHost((width) => releaseStrip(width, releases, { label: `Releases oldest to newest: ${releases.map((r) => `${r.version ?? 'unversioned'} ${r.outcome}`).join(', ')}` })),
          h('ul', { class: 'legend' }, ...['ok', 'failed', 'skipped', 'pending'].map((o) => h('li', null, outcomeBadge(o)))),
          dataTable('Show releases as a table', table({ caption: 'Releases and outcome', head: ['Version', 'Outcome'], rows: releases.map((r) => [r.version ?? 'unversioned', outcomeBadge(r.outcome)]) })),
        ],
  );
}

function wipPanel(state) {
  const counts = state.flow.counts;
  const rows = state.board_stages.map((s) => ({ label: stageLabel(s), value: counts[s] ?? 0, text: formatInteger(counts[s] ?? 0), cls: stageFill(s) }));
  const total = rows.reduce((n, r) => n + r.value, 0);
  return panel(
    { id: 'wip', title: 'Work in progress', lede: `${formatInteger(total)} ${plural(total, 'ticket')} across the board right now.` },
    chartHost((width) => barChart(width, rows, { label: `Tickets per stage: ${rows.map((r) => `${r.label} ${r.text}`).join(', ')}`, labelChars: 12 })),
    dataTable('Show counts as a table', table({ caption: 'Tickets per stage', head: ['Stage', 'Tickets'], numeric: [1], rows: rows.map((r) => [r.label, r.text]) })),
  );
}

function gatesPanel(state) {
  const gates = Object.entries(state.flow.gate_first_pass).map(([gate, g]) => ({ gate, pass: g.pass, total: g.total }));
  return panel(
    { id: 'gates', title: 'Gate pass rate, first attempt', lede: 'How often a change cleared each check the first time it ran.' },
    gates.length === 0
      ? h('p', { class: 'muted' }, 'No gate results yet.')
      : [
          chartHost((width) => rateChart(width, gates, { label: `First attempt pass rate: ${gates.map((g) => `${g.gate} ${g.total ? formatPercent(g.pass / g.total) : 'n/a'}`).join(', ')}` })),
          dataTable('Show pass rates as a table', table({ caption: 'First attempt pass rate per gate', head: ['Gate', 'Passed', 'Runs', 'Rate'], numeric: [1, 2, 3], rows: gates.map((g) => [h('code', null, g.gate), formatInteger(g.pass), formatInteger(g.total), g.total ? formatPercent(g.pass / g.total) : 'n/a']) })),
        ],
  );
}

function defectsPanel(state) {
  const defects = state.flow.defects;
  const owners = new Map();
  for (const d of defects) {
    const key = d.owner ?? 'unassigned';
    const row = owners.get(key) ?? { owner: key, n: 0, times: [] };
    row.n += 1;
    if (d.seconds !== null) row.times.push(d.seconds);
    owners.set(key, row);
  }
  const median = (xs) => {
    if (xs.length === 0) return null;
    const s = [...xs].sort((a, b) => a - b);
    const mid = Math.floor(s.length / 2);
    return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
  };
  return panel(
    { id: 'defects', title: 'Defects: owner and resolution time', lede: 'Bugs only. Resolution time runs from opening the issue to its production deploy; open bugs have none.' },
    defects.length === 0
      ? h('p', { class: 'muted' }, 'No bugs triaged yet.')
      : [
          h('div', { class: 'owner-tiles' }, ...[...owners.values()].map((o) => h('div', { class: 'owner-tile' }, h('span', { class: 'owner-name' }, o.owner), h('span', { class: 'owner-count' }, `${o.n} ${plural(o.n, 'bug')}`), h('span', { class: 'owner-median' }, o.times.length ? `median ${formatDuration(median(o.times))}` : 'none resolved')))),
          table({
            caption: 'Bugs with owner, severity and resolution time',
            head: ['Ticket', 'Owner', 'Severity', 'Resolution'],
            rows: defects.map((d) => [issueNumberLink(d.issue), d.owner ?? '-', d.severity ? badge(d.severity, 'warn') : '-', d.seconds === null ? h('span', { class: 'muted' }, 'open') : formatDuration(d.seconds)]),
          }),
        ],
  );
}

function costPanel(state) {
  const cap = state.cost.caps.issue_usd;
  const rows = costRows(state)
    .sort((a, b) => b.usd - a.usd)
    .slice(0, TOP);
  return panel(
    { id: 'cost-cap', title: 'Cost per issue against the cap', lede: `The line marks the ${formatUsd(cap)} cap for one issue. The ${rows.length} costliest tickets${state.tickets.length > rows.length ? ` of ${state.tickets.length}` : ''}.` },
    rows.length === 0
      ? h('p', { class: 'muted' }, 'No spend yet.')
      : [
          chartHost((width) =>
            barChart(
              width,
              rows.map((r) => ({ label: `#${r.issue} ${r.title}`, value: r.usd, text: formatUsd(r.usd), sub: `${Math.round(r.pct)}%`, cls: `fill-${costBand(r.pct)}` })),
              { label: 'Cost per ticket against the per-issue cap', marker: { value: cap, label: `cap ${formatUsd(cap)}` }, labelChars: 26 },
            ),
          ),
          dataTable('Show costs as a table', table({ caption: 'Cost per ticket', head: ['Ticket', 'Cost', 'Of cap'], numeric: [1, 2], rows: rows.map((r) => [issueNumberLink(r.issue), formatUsd(r.usd), `${Math.round(r.pct)}%`]) })),
        ],
  );
}

function scenariosPanel(state) {
  const rows = scenarioRows(state);
  return panel(
    { id: 'scenarios', title: 'Scenarios and tickets', lede: 'Each ticket exercises one demo scenario, so this shows how every kind of request ended up.', className: 'panel-wide' },
    rows.length === 0
      ? h('p', { class: 'muted' }, 'No tickets yet.')
      : table({
          caption: 'Tickets grouped by scenario',
          head: ['Scenario', 'Tickets', 'In production', 'Escalated', 'In flight', 'Spend', 'Examples'],
          numeric: [1, 2, 3, 4, 5],
          rows: rows.map((r) => [
            h('span', { class: 'cell-scenario' }, h('span', { class: 'scenario' }, r.scenario), SCENARIO_NOTES[r.scenario] ? h('span', { class: 'muted' }, SCENARIO_NOTES[r.scenario]) : null),
            formatInteger(r.tickets.length),
            formatInteger(r.prod),
            formatInteger(r.escalated),
            formatInteger(r.inFlight),
            formatUsd(r.usd),
            h('span', { class: 'refs' }, ...r.tickets.slice(0, 6).map((t) => issueNumberLink(t.issue)), r.tickets.length > 6 ? h('span', { class: 'muted' }, `+${r.tickets.length - 6} more`) : null),
          ]),
        }),
  );
}

export function renderFlow(ctx) {
  const { state, now } = ctx;
  if (state.tickets.length === 0) {
    return h('div', { class: 'view' }, pageHead({ title: 'Flow metrics' }), emptyState('No flow data yet', 'Charts appear once tickets have moved through the board.'));
  }
  return h(
    'div',
    { class: 'view' },
    pageHead({ title: 'Flow metrics', lede: 'How work moves from backlog to production, derived from the ledger. Each chart has its data in a table underneath.' }),
    cyclePanel(state, now),
    h('div', { class: 'grid-2' }, leadPanel(state), changeFailurePanel(state)),
    h('div', { class: 'grid-2' }, wipPanel(state), gatesPanel(state)),
    h('div', { class: 'grid-2' }, defectsPanel(state), costPanel(state)),
    scenariosPanel(state),
  );
}

