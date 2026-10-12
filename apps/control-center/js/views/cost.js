// #/cost  Money, honestly: what the ledger estimates, what Azure actually billed, and the gap.

import { barChart, billingChart } from '../charts.js';
import { badge, chartHost, dataTable, h, panel, table, timeEl } from '../dom.js';
import { formatDuration, formatInteger, formatPercent, formatTimestamp, formatUsd, formatUsdWords } from '../format.js';
import { icon } from '../icons.js';
import { billingSummary, costRows, sortRows } from '../model.js';
import { ui } from '../ui.js';
import { costBar, issueNumberLink, pageHead, typeBadge } from './common.js';

function banner(summary, state, now) {
  const { caps } = state.cost;
  const tone = summary.tone === 'danger' ? 'danger' : 'info';
  const lines = [];
  if (summary.read && summary.overCap) {
    lines.push(`Billed spend is at or over the ${formatUsdWords(caps.total_usd)} cap.`);
  } else if (summary.read && summary.overHalt) {
    lines.push(`Billed spend is over the ${formatUsdWords(caps.halt_usd)} halt line.`);
  }
  if (summary.halted) {
    lines.push('The loop is halted: no new work starts until spend is back under the line.');
  }
  const ratioNote =
    summary.read && summary.billed > summary.estimate && summary.ratio !== null
      ? `The gap between the two is ${formatUsdWords(summary.gap)}.`
      : null;

  return h(
    'section',
    {
      class: `callout callout-${tone} cost-banner`,
      role: tone === 'danger' ? 'alert' : 'status',
      'aria-labelledby': 'cost-banner-title',
    },
    h('span', { class: 'callout-icon' }, icon(tone === 'danger' ? 'alert' : 'clock', { size: 20 })),
    h(
      'div',
      { class: 'callout-body' },
      h(
        'h2',
        { id: 'cost-banner-title' },
        summary.read
          ? tone === 'danger'
            ? 'Spend is over the line'
            : 'Billed spend'
          : 'Billed spend not read yet',
      ),
      h('p', { class: 'callout-lead', id: 'cost-sentence' }, summary.sentence),
      ...lines.map((l) => h('p', null, l)),
      ratioNote ? h('p', { class: 'muted' }, ratioNote) : null,
      summary.asOf
        ? h(
            'p',
            { class: 'muted' },
            'Billing read as of ',
            timeEl(summary.asOf, now),
            ` (${formatTimestamp(summary.asOf)}). `,
            state.cost.gap?.note ?? 'Azure billing lags by hours.',
          )
        : h(
            'p',
            { class: 'muted' },
            'The ledger reads the Azure bill on a schedule. Until it has, nothing is shown for billed spend.',
          ),
    ),
  );
}

function kpis(summary, state) {
  const { totals, caps } = state.cost;
  const tile = (label, value, tone = '', sub = '') =>
    h(
      'div',
      { class: `kpi ${tone}`.trim() },
      h('dt', null, label),
      h('dd', null, value, sub ? h('span', { class: 'kpi-sub' }, sub) : null),
    );

  const billedTone = summary.overHalt ? 'kpi-bad' : summary.read ? 'kpi-billed' : 'kpi-muted';

  return h(
    'dl',
    { class: 'kpis cost-kpis' },
    tile('Ledger estimate', formatUsd(summary.estimate), 'kpi-estimate', 'List price models'),
    tile(
      'Azure billed',
      summary.billed === null ? 'not read yet' : formatUsd(summary.billed),
      billedTone,
      summary.billed === null ? 'Awaiting sync' : 'Actual telemetry',
    ),
    tile('Halt line', formatUsd(caps.halt_usd), 'kpi-halt', 'Safety threshold'),
    tile('Total cap', formatUsd(caps.total_usd), 'kpi-cap', 'Hard budget cap'),
    tile('Tickets', formatUsd(totals.issues_usd), 'kpi-tickets', `${state.tickets.length} tickets`),
    tile('Orchestrator', formatUsd(totals.orchestrator_usd), 'kpi-orch', 'Platform overhead'),
  );
}

function estimateVsBilledPanel(summary, state) {
  const ledgerEstimate = summary.estimate;
  const haltUsd = state.cost.caps.halt_usd;
  const capUsd = state.cost.caps.total_usd;
  const billedUsd = summary.billed;

  const pills = [];
  if (billedUsd !== null) {
    const haltHeadroom = Math.max(0, haltUsd - billedUsd);
    const capHeadroom = Math.max(0, capUsd - billedUsd);
    pills.push(
      h(
        'div',
        { class: 'telemetry-pill pill-halt' },
        h('span', { class: 'pill-label' }, 'Halt Headroom:'),
        h('strong', { class: 'pill-value' }, formatUsd(haltHeadroom)),
      ),
      h(
        'div',
        { class: 'telemetry-pill pill-cap' },
        h('span', { class: 'pill-label' }, 'Cap Headroom:'),
        h('strong', { class: 'pill-value' }, formatUsd(capHeadroom)),
      ),
    );
    if (summary.ratio !== null && billedUsd > ledgerEstimate) {
      pills.push(
        h(
          'div',
          { class: 'telemetry-pill pill-gap' },
          h('span', { class: 'pill-label' }, 'Telemetry Gap:'),
          h('strong', { class: 'pill-value' }, `+${formatUsd(summary.gap)}`),
        ),
      );
    }
  }

  return panel(
    {
      id: 'estimate-vs-billed',
      title: 'Estimate versus billed',
      lede: `Against the ${formatUsdWords(haltUsd)} halt line and the ${formatUsdWords(capUsd)} cap.`,
      className: 'panel-wide',
      actions: pills.length ? h('div', { class: 'telemetry-pills' }, ...pills) : null,
    },
    chartHost((width) =>
      billingChart(width, {
        estimate: ledgerEstimate,
        billed: billedUsd,
        halt: haltUsd,
        cap: capUsd,
      }),
    ),
    dataTable(
      'Show as a table',
      table({
        caption: 'Ledger estimate versus Azure billed',
        head: ['Measure', 'Amount'],
        numeric: [1],
        rows: [
          ['Ledger estimate', formatUsd(ledgerEstimate)],
          ['Azure billed', billedUsd === null ? 'not read yet' : formatUsd(billedUsd)],
          ['Halt line', formatUsd(haltUsd)],
          ['Total cap', formatUsd(capUsd)],
        ],
      }),
    ),
  );
}

function meterPanel(state) {
  const billing = state.cost.billing;
  if (!billing) {
    return panel(
      { id: 'meters', title: 'Where the bill comes from' },
      h('p', { class: 'muted' }, 'Billed spend not read yet, so there is no meter breakdown.'),
    );
  }
  const meters = [...billing.by_meter].sort((a, b) => b.usd - a.usd);
  const total = meters.reduce((n, m) => n + m.usd, 0) || billing.billed_usd;
  const rows = meters.map((m) => ({
    label: m.name,
    value: m.usd,
    text: formatUsd(m.usd),
    sub: total > 0 ? formatPercent(m.usd / total) : '',
    cls: 'fill-info',
  }));
  return panel(
    {
      id: 'meters',
      title: 'Where the bill comes from',
      lede: billing.scope ? `Azure cost meters for ${billing.scope}.` : 'Azure cost meters.',
    },
    meters.length === 0
      ? h('p', { class: 'muted' }, 'The bill has no meter breakdown.')
      : chartHost((width) => barChart(width, rows, { label: 'Azure billed spend by meter', labelChars: 22 })),
    meters.length === 0
      ? null
      : dataTable(
          'Show meters as a table',
          table({
            caption: 'Azure billed spend by meter',
            head: ['Meter', 'Billed', 'Share'],
            numeric: [1, 2],
            rows: meters.map((m) => [
              m.name,
              formatUsd(m.usd),
              total > 0 ? formatPercent(m.usd / total) : '-',
            ]),
          }),
        ),
  );
}

function ledgerPanel(state, now) {
  const led = state.cost.ledger;
  return panel(
    {
      id: 'ledger-compute',
      title: "The ledger's own compute",
      lede: 'Counts toward the caps, because the ledger runs on the same Azure subscription.',
    },
    h(
      'dl',
      { class: 'stats' },
      h('div', { class: 'stat' }, h('dt', null, 'Invocations'), h('dd', null, formatInteger(led.invocations))),
      h('div', { class: 'stat' }, h('dt', null, 'Compute time'), h('dd', null, formatDuration(led.seconds))),
      h('div', { class: 'stat' }, h('dt', null, 'Estimated cost'), h('dd', null, formatUsd(led.usd))),
      h('div', { class: 'stat' }, h('dt', null, 'Last run'), h('dd', null, led.last_at ? timeEl(led.last_at, now) : '-')),
    ),
    h(
      'p',
      { class: 'footnote' },
      `${formatInteger(led.invocations)} ${led.invocations === 1 ? 'invocation' : 'invocations'}, ${formatDuration(led.seconds)}, ${formatUsd(led.usd)}.`,
    ),
  );
}

const COLUMNS = [
  ['issue', 'Ticket', false],
  ['usd', 'Total', true],
  ['pct', 'Of cap', true],
  ['model', 'Model', true],
  ['coder', 'Coder', true],
  ['ledger', 'Ledger', true],
];

function ticketTable(state) {
  const wrap = h('div', { class: 'table-slot' });
  const draw = () => {
    const { key, direction } = ui.cost;
    const rows = sortRows(costRows(state), key, direction);
    const over = rows.filter((r) => r.over).length;
    const head = COLUMNS.map(([k, label, numeric]) => {
      const active = key === k;
      const button = h(
        'button',
        {
          type: 'button',
          class: `sort${active ? ' sort-active' : ''}`,
          'aria-label': `Sort by ${label}${active ? `, currently ${direction === 'desc' ? 'descending' : 'ascending'}` : ''}`,
        },
        label,
        h('span', { class: 'sort-arrow', 'aria-hidden': 'true' }, active ? (direction === 'desc' ? ' ▾' : ' ▴') : ''),
      );
      button.addEventListener('click', () => {
        ui.cost = { key: k, direction: active && direction === 'desc' ? 'asc' : 'desc' };
        draw();
      });
      return h(
        'th',
        {
          scope: 'col',
          class: numeric ? 'num' : undefined,
          'aria-sort': active ? (direction === 'desc' ? 'descending' : 'ascending') : 'none',
        },
        button,
      );
    });
    wrap.replaceChildren(
      h(
        'div',
        { class: 'table-wrap', tabindex: '0', role: 'region', 'aria-label': 'Cost per ticket' },
        h(
          'table',
          { class: 'data cost-data' },
          h('caption', { class: 'sr-only' }, 'Cost per ticket, sortable'),
          h('thead', null, h('tr', null, ...head)),
          h(
            'tbody',
            null,
            ...rows.map((r) =>
              h(
                'tr',
                { class: r.over ? 'row-bad' : undefined },
                h(
                  'th',
                  { scope: 'row' },
                  h(
                    'span',
                    { class: 'cell-ticket' },
                    issueNumberLink(r.issue),
                    h('span', { class: 'clamp-1 wrap' }, r.title || 'Untitled'),
                    typeBadge(r.type),
                    r.over ? badge('Over cap', 'bad') : null,
                  ),
                ),
                h('td', { class: 'num strong' }, formatUsd(r.usd)),
                h(
                  'td',
                  { class: 'num cell-cap' },
                  costBar(r.usd, r.pct, { label: false }),
                  h('span', { class: 'pct-text' }, `${Math.round(r.pct)}%`),
                ),
                h('td', { class: 'num' }, formatUsd(r.model)),
                h('td', { class: 'num' }, formatUsd(r.coder)),
                h('td', { class: 'num' }, formatUsd(r.ledger)),
              ),
            ),
          ),
          h(
            'tfoot',
            null,
            h(
              'tr',
              null,
              h(
                'th',
                { scope: 'row' },
                over > 0 ? `${over} over the ${formatUsd(state.cost.caps.issue_usd)} cap` : 'Tickets',
              ),
              h('td', { class: 'num strong' }, formatUsd(state.cost.totals.issues_usd)),
              h('td', null),
              h('td', null),
              h('td', null),
              h('td', null),
            ),
          ),
        ),
      ),
    );
  };
  draw();
  return wrap;
}

export function renderCost(ctx) {
  const { state, now } = ctx;
  const summary = billingSummary(state.cost);
  return h(
    'div',
    { class: 'view cost-view' },
    pageHead({
      title: 'Cost',
      lede: 'The ledger estimates from list prices. Azure bills what actually ran. Both are shown, and the gap is not hidden.',
    }),
    banner(summary, state, now),
    kpis(summary, state),
    estimateVsBilledPanel(summary, state),
    h('div', { class: 'grid-2 cost-grid' }, meterPanel(state), ledgerPanel(state, now)),
    panel(
      {
        id: 'per-ticket',
        title: 'Cost per ticket',
        lede: `Sorted by total. The per-issue cap is ${formatUsd(state.cost.caps.issue_usd)}; "Model" and "Coder" are what the agents spent, "Ledger" is the ticket's share of the ledger's compute.`,
        className: 'panel-wide',
      },
      ticketTable(state),
    ),
  );
}
