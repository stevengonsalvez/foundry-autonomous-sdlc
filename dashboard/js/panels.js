// Panel rendering. Takes aggregated data, returns DOM. All text goes through text nodes.

import { h, responsiveSvg } from './dom.js';
import { medianChart, stackedChart, gateChart, stageClass } from './charts.js';
import {
  NO_VALUE,
  formatDuration,
  formatInteger,
  formatPercent,
  formatTimestamp,
  formatUsd,
  plural,
  stageLabel,
} from './format.js';
import {
  COST_CAP_USD,
  HALT_USD,
  ISSUE_COST_LINE_USD,
  costSummary,
  defectSummary,
  gateRates,
  headlineCounts,
  issueLinks,
  stageDurations,
} from './aggregate.js';

// ---------------------------------------------------------------- building blocks

function value(content) {
  if (content === null || content === undefined || content === NO_VALUE) {
    return h('span', { class: 'muted' }, h('span', { 'aria-hidden': 'true' }, NO_VALUE), h('span', { class: 'sr-only' }, 'not recorded'));
  }
  return content;
}

function panel(id, title, lede, ...children) {
  return h(
    'section',
    { class: 'panel', 'aria-labelledby': `${id}-title`, id },
    h('header', { class: 'panel-head' }, h('h2', { id: `${id}-title` }, title), lede ? h('p', { class: 'lede' }, lede) : null),
    ...children,
  );
}

function tableWrap(label, table) {
  return h('div', { class: 'table-wrap', role: 'region', 'aria-label': label, tabindex: '0' }, table);
}

function table(caption, head, body, foot) {
  return h(
    'table',
    { class: 'data' },
    h('caption', { class: 'sr-only' }, caption),
    h('thead', {}, h('tr', {}, head.map((c) => h('th', { scope: 'col', class: c.num ? 'num' : null }, c.label)))),
    h('tbody', {}, body),
    foot ? h('tfoot', {}, foot) : null,
  );
}

function disclosure(summary, ...content) {
  return h('details', { class: 'disclosure' }, h('summary', {}, summary), ...content);
}

function badge(label, tone) {
  return h('span', { class: `badge tone-${tone}` }, label);
}

function outcomeBadge(outcome) {
  const tones = { released: 'good', escalated: 'bad', open: 'info' };
  const labels = { released: 'Released', escalated: 'Escalated', open: 'Open' };
  return badge(labels[outcome] ?? 'Unknown', tones[outcome] ?? 'neutral');
}

function outcomeCell(issue) {
  const reason = issue.outcome === 'escalated' && issue.escalation ? issue.escalation.replace(/[-_]+/g, ' ') : null;
  return h('span', { class: 'outcome' }, outcomeBadge(issue.outcome), reason ? h('span', { class: 'outcome-reason' }, reason) : null);
}

function scenarioLabel(scenario) {
  const [letter, ...rest] = scenario.split('-');
  return h('span', { class: 'scenario' }, letter.toUpperCase(), rest.length ? h('span', { class: 'scenario-note' }, rest.join(' ')) : null);
}

function severityBadge(severity) {
  if (!severity) return value(null);
  const tones = { s1: 'bad', s2: 'warn', s3: 'info', s4: 'neutral' };
  return badge(severity.toUpperCase(), tones[severity]);
}

function chartHost(extraClass) {
  return h('div', { class: `chart-host ${extraClass ?? ''}`.trim() });
}

function legend(items) {
  return h(
    'ul',
    { class: 'legend' },
    items.map((item) => h('li', {}, h('span', { class: `swatch ${item.cls}`, 'aria-hidden': 'true' }), item.label)),
  );
}

const issueRef = (label, title) =>
  h('span', { class: 'issue-ref' }, h('span', { class: 'issue-num' }, label), h('span', { class: 'issue-title' }, title));

function notice(text) {
  return h('p', { class: 'empty' }, text);
}

// ---------------------------------------------------------------- header

export function renderHeader(metrics) {
  const counts = headlineCounts(metrics);
  const cost = costSummary(metrics);
  const repoUrl = metrics.repo ? `https://github.com/${metrics.repo}` : null;

  const tile = (label, content) => h('div', { class: 'kpi' }, h('dt', {}, label), h('dd', {}, content));

  return h(
    'section',
    { class: 'hero', 'aria-labelledby': 'page-title' },
    h(
      'div',
      { class: 'hero-copy' },
      h('p', { class: 'eyebrow' }, 'Autonomous SDLC'),
      h('h1', { id: 'page-title' }, 'Delivery metrics'),
      h(
        'p',
        { class: 'meta' },
        repoUrl ? h('a', { href: repoUrl, rel: 'noopener' }, metrics.repo) : h('span', {}, 'Repository not recorded'),
        h('span', { class: 'sep', 'aria-hidden': 'true' }, '/'),
        metrics.generatedAt
          ? h('span', {}, 'Generated ', h('time', { datetime: metrics.generatedAt }, formatTimestamp(metrics.generatedAt)))
          : h('span', {}, 'Generation time not recorded'),
      ),
    ),
    h(
      'dl',
      { class: 'kpis' },
      tile('Issues', formatInteger(counts.issues)),
      tile('Released', formatInteger(counts.released)),
      tile('Escalated', formatInteger(counts.escalated)),
      tile(`Spend of ${formatUsd(COST_CAP_USD, 2)} cap`, formatUsd(cost.total, 2)),
    ),
  );
}

// ---------------------------------------------------------------- cycle time

export function renderCycle(issues) {
  const data = stageDurations(issues);
  if (data.stages.length === 0) {
    return panel('cycle', 'Cycle time per stage', 'Time each issue spent in every stage.', notice('No stage durations have been recorded yet.'));
  }

  const present = data.stages.map((st) => st.stage);
  const lede = data.medianTotal === null
    ? 'Median time per stage across issues, and each issue split by stage.'
    : `Median end to end ${formatDuration(data.medianTotal)} across ${data.totalCount} ${plural(data.totalCount, 'issue')}.`;

  const medianLabel = `Median time per stage. ${data.stages.map((st) => `${stageLabel(st.stage)} ${formatDuration(st.median)}`).join(', ')}.`;
  const medians = chartHost();
  responsiveSvg(medians, (w) => medianChart(w, data.stages, medianLabel));

  const stackedIssues = data.perIssue;
  const stackedLabel = `Time per stage for each of ${stackedIssues.length} ${plural(stackedIssues.length, 'issue')}. The table below lists every value.`;
  const stacked = chartHost();
  responsiveSvg(stacked, (w) => stackedChart(w, stackedIssues, data.maxTotal, present, stackedLabel));

  const head = [
    { label: 'Issue' },
    ...present.map((stage) => ({ label: stageLabel(stage), num: true })),
    { label: 'Total', num: true },
  ];
  const rows = data.perIssue.map((p) => {
    const bySeconds = new Map(p.segments.map((seg) => [seg.stage, seg.seconds]));
    return h(
      'tr',
      {},
      h('th', { scope: 'row' }, issueRef(p.label, p.title)),
      present.map((stage) => h('td', { class: 'num' }, bySeconds.has(stage) ? formatDuration(bySeconds.get(stage)) : value(null))),
      h('td', { class: 'num strong' }, p.total > 0 ? formatDuration(p.total) : value(null)),
    );
  });
  const foot = h(
    'tr',
    {},
    h('th', { scope: 'row' }, 'Median'),
    data.stages.map((st) => h('td', { class: 'num' }, formatDuration(st.median))),
    h('td', { class: 'num strong' }, formatDuration(data.medianTotal)),
  );

  return panel(
    'cycle',
    'Cycle time per stage',
    lede,
    h('h3', {}, 'Median per stage'),
    medians,
    h('h3', {}, 'Per issue'),
    legend(present.map((stage) => ({ cls: stageClass(stage, present), label: stageLabel(stage) }))),
    stacked,
    data.perIssue.some((p) => p.hasOpen || p.hasUnknown)
      ? h('p', { class: 'footnote' }, 'Faded segments are stages still running, measured up to the time the data was generated. Running stages are left out of the medians and of the end to end figure.')
      : null,
    disclosure('Show data table', tableWrap('Cycle time per issue and stage', table('Time spent in each stage, per issue, with the median per stage', head, rows, foot))),
  );
}

// ---------------------------------------------------------------- gates

export function renderGates(metrics) {
  const gates = gateRates(metrics.issues, metrics.gatePassRates);
  const anyData = gates.some((g) => g.eventual.total > 0 || g.first.total > 0 || g.runs);
  if (!anyData) {
    return panel('gates', 'Gate pass rates', 'Share of issues that passed each CI gate.', notice('No gate results have been recorded yet.'));
  }

  const firstKnown = gates.some((g) => g.first.total > 0);
  const label = `Pass rate per gate. ${gates
    .map((g) => `${g.gate}: first attempt ${formatPercent(g.first.rate)}, eventually ${formatPercent(g.eventual.rate)}`)
    .join('; ')}.`;
  const chart = chartHost();
  responsiveSvg(chart, (w) => gateChart(w, gates, label));

  const frac = (part) => (part.rate === null ? value(null) : `${formatPercent(part.rate)} (${part.pass}/${part.total})`);
  const body = gates.map((g) =>
    h(
      'tr',
      {},
      h('th', { scope: 'row', class: 'mono' }, g.gate),
      h('td', { class: 'num' }, frac(g.first)),
      h('td', { class: 'num' }, frac(g.eventual)),
      h('td', { class: 'num' }, g.runs ? formatInteger(g.runs.pass) : value(null)),
      h('td', { class: 'num' }, g.runs ? formatInteger(g.runs.fail) : value(null)),
    ),
  );
  const head = [
    { label: 'Gate' },
    { label: 'First attempt', num: true },
    { label: 'Eventually', num: true },
    { label: 'Runs passed', num: true },
    { label: 'Runs failed', num: true },
  ];

  return panel(
    'gates',
    'Gate pass rates',
    'Share of issues whose pull request passed each gate on the first attempt, and by the time it merged or stopped.',
    legend([
      { cls: 'bar-first', label: 'First attempt' },
      { cls: 'bar-eventual', label: 'Eventually' },
    ]),
    chart,
    firstKnown ? null : h('p', { class: 'footnote' }, 'First-attempt results are not recorded in this data, so only the eventual rate is shown.'),
    disclosure('Show data table', tableWrap('Gate pass rates', table('Pass rate and counts per gate', head, body))),
  );
}

// ---------------------------------------------------------------- defects

export function renderDefects(issues) {
  const data = defectSummary(issues);
  if (data.bugs.length === 0) {
    return panel('defects', 'Defect owner and resolution time', 'Bugs only: who owned the fix and how long it took.', notice('No bug has gone through the loop yet.'));
  }

  const scale = data.maxResolution > 0 ? data.maxResolution : 1;
  const rows = data.bugs.map((b) =>
    h(
      'tr',
      {},
      h('th', { scope: 'row' }, issueRef(b.label, b.title)),
      h('td', {}, severityBadge(b.severity)),
      h('td', {}, b.owner ? h('span', { class: 'mono' }, b.owner) : value(null)),
      h(
        'td',
        { class: 'num' },
        h(
          'span',
          { class: 'cell-bar' },
          b.resolutionSeconds === null
            ? value(null)
            : [
                h('span', { class: 'mini-bar', 'aria-hidden': 'true' }, h('span', { class: 'mini-fill', style: `width:${Math.max(2, (b.resolutionSeconds / scale) * 100).toFixed(1)}%` })),
                h('span', { class: 'cell-bar-value' }, formatDuration(b.resolutionSeconds)),
              ],
        ),
      ),
    ),
  );
  const head = [
    { label: 'Issue' },
    { label: 'Severity' },
    { label: 'Owner' },
    { label: 'Opened to release', num: true },
  ];

  const owners = h(
    'ul',
    { class: 'owner-tiles' },
    data.byOwner.map((o) =>
      h(
        'li',
        { class: 'owner-tile' },
        h('span', { class: 'mono owner-name' }, o.owner),
        h('span', { class: 'owner-count' }, `${o.count} ${plural(o.count, 'bug')}`),
        h('span', { class: 'owner-median' }, o.medianResolution === null ? 'none resolved' : `median ${formatDuration(o.medianResolution)}`),
      ),
    ),
  );

  return panel(
    'defects',
    'Defect owner and resolution time',
    data.medianResolution === null
      ? 'Bugs only: who owned the fix and how long it took.'
      : `Bugs only. Median time from opened to release is ${formatDuration(data.medianResolution)}.`,
    owners,
    tableWrap('Bugs with owner, severity and resolution time', table('Bugs with owner, severity and time from opened to release', head, rows)),
  );
}

// ---------------------------------------------------------------- cost

export function renderCost(metrics) {
  const cost = costSummary(metrics);
  const pct = Math.round(cost.percentOfCap);
  const valueText = `${formatUsd(cost.total, 2)} of ${formatUsd(cost.cap, 2)}`;

  const bar = h(
    'div',
    {
      class: `meter${cost.haltReached ? ' meter-hot' : ''}`,
      role: 'progressbar',
      'aria-label': `Total spend against the ${formatUsd(cost.cap, 2)} cap`,
      'aria-valuemin': '0',
      'aria-valuemax': String(cost.cap),
      'aria-valuenow': cost.total.toFixed(4),
      'aria-valuetext': `${valueText}, ${pct} percent`,
    },
    h('div', { class: 'meter-fill', style: `width:${(cost.fractionOfCap * 100).toFixed(2)}%` }),
    h('div', { class: 'meter-mark', style: `left:${(HALT_USD / COST_CAP_USD) * 100}%`, 'aria-hidden': 'true' }),
  );

  const summary = h(
    'div',
    { class: 'budget' },
    h('p', { class: 'budget-figure' }, h('strong', {}, formatUsd(cost.total, 2)), h('span', { class: 'budget-of' }, ` of ${formatUsd(cost.cap, 2)} cap`), h('span', { class: 'budget-pct' }, `${pct}%`)),
    bar,
    h(
      'p',
      { class: 'footnote' },
      `${formatUsd(cost.remaining, 2)} remaining. New work stops at ${formatUsd(HALT_USD, 2)}; each issue is capped at ${formatUsd(ISSUE_COST_LINE_USD, 2)}.`,
    ),
  );

  const body = cost.rows.map((r) => {
    const fill = r.usd === null ? 0 : Math.max(r.usd > 0 ? 2 : 0, (r.usd / cost.perIssueScale) * 100);
    return h(
      'tr',
      {},
      h('th', { scope: 'row' }, issueRef(r.label, r.title)),
      h('td', { class: 'num' }, r.model === null ? value(null) : formatUsd(r.model)),
      h('td', { class: 'num' }, r.coder === null ? value(null) : formatUsd(r.coder)),
      h('td', { class: 'num' }, r.calls === null ? value(null) : formatInteger(r.calls)),
      h('td', { class: 'num strong' }, r.usd === null ? value(null) : formatUsd(r.usd)),
      h(
        'td',
        { class: 'line-cell' },
        r.usd === null
          ? null
          : h(
              'span',
              { class: 'line-bar', 'aria-hidden': 'true' },
              h('span', { class: `line-fill${r.overLine ? ' over' : ''}`, style: `width:${fill.toFixed(1)}%` }),
              h('span', { class: 'line-mark', style: `left:${((ISSUE_COST_LINE_USD / cost.perIssueScale) * 100).toFixed(1)}%` }),
            ),
        r.overLine ? badge('Over line', 'bad') : r.usd !== null ? h('span', { class: 'sr-only' }, 'within the per issue line') : null,
      ),
    );
  });
  if (cost.orchestrator > 0) {
    body.push(
      h(
        'tr',
        {},
        h('th', { scope: 'row' }, h('span', { class: 'issue-ref' }, h('span', { class: 'issue-title' }, 'Orchestrator compute'))),
        h('td', { class: 'num' }, value(null)),
        h('td', { class: 'num' }, value(null)),
        h('td', { class: 'num' }, value(null)),
        h('td', { class: 'num strong' }, formatUsd(cost.orchestrator)),
        h('td', {}),
      ),
    );
  }
  const foot = h(
    'tr',
    {},
    h('th', { scope: 'row' }, 'Total'),
    h('td', { class: 'num' }, formatUsd(cost.modelTotal)),
    h('td', { class: 'num' }, formatUsd(cost.coderTotal)),
    h('td', { class: 'num' }, formatInteger(cost.callsTotal)),
    h('td', { class: 'num strong' }, formatUsd(cost.accounted)),
    h('td', {}),
  );
  const head = [
    { label: 'Issue' },
    { label: 'Model', num: true },
    { label: 'Coder', num: true },
    { label: 'Calls', num: true },
    { label: 'Total', num: true },
    { label: `Against ${formatUsd(ISSUE_COST_LINE_USD, 2)} line` },
  ];
  const drift = cost.totalReported && Math.abs(cost.total - cost.accounted) > 0.00005;

  return panel(
    'cost',
    'Cost per issue',
    'Estimated from token counts and list prices: model calls plus coder runtime and orchestrator compute. The Azure invoice is the authority and ran higher, see docs/findings.md.',
    summary,
    tableWrap('Cost per issue', table('Model cost, coder cost, calls and total per issue, with the per issue line', head, body, foot)),
    drift ? h('p', { class: 'footnote' }, `The reported total (${formatUsd(cost.total)}) differs from the sum of the rows above (${formatUsd(cost.accounted)}); it also keeps spend from objects no longer listed.`) : null,
  );
}

// ---------------------------------------------------------------- issues

export function renderIssues(metrics) {
  const rows = [...metrics.issues]
    .sort((a, b) => a.ref - b.ref)
    .map((issue) => {
      const links = issueLinks(metrics.repo, issue);
      const link = (url, text, label) =>
        url ? h('a', { href: url, rel: 'noopener', 'aria-label': label }, text) : null;
      const refs = [
        issue.number === null ? null : link(links.issue, `#${issue.number}`, `#${issue.number}, issue on GitHub`) ?? h('span', {}, `#${issue.number}`),
        issue.pr === null ? null : link(links.pr, `PR #${issue.pr}`, `PR #${issue.pr}, pull request on GitHub`) ?? h('span', {}, `PR #${issue.pr}`),
        issue.release === null ? null : link(links.release, issue.release, `${issue.release}, release on GitHub`) ?? h('span', {}, issue.release),
      ].filter(Boolean);

      return h(
        'tr',
        {},
        h('th', { scope: 'row' }, issueRef(issue.label, issue.title)),
        h('td', {}, issue.scenario ? scenarioLabel(issue.scenario) : value(null)),
        h('td', {}, issue.type ? h('span', { class: 'mono' }, issue.type) : value(null)),
        h('td', {}, outcomeCell(issue)),
        h('td', {}, h('span', { class: 'refs' }, refs)),
      );
    });
  const head = [
    { label: 'Issue' },
    { label: 'Scenario' },
    { label: 'Type' },
    { label: 'Outcome' },
    { label: 'Links' },
  ];
  return panel(
    'issues',
    'Scenarios and issues',
    'Every issue the loop has handled, with its pull request and release.',
    tableWrap('Issues', table('Issues with scenario, type, outcome, pull request and release', head, rows)),
  );
}

// ---------------------------------------------------------------- dashboard

export function renderDashboard(metrics) {
  const frag = document.createDocumentFragment();
  const note = metrics.skipped > 0
    ? h('p', { class: 'footnote page-note' }, `${metrics.skipped} ${plural(metrics.skipped, 'entry', 'entries')} in metrics.json could not be read and ${plural(metrics.skipped, 'was', 'were')} left out.`)
    : null;
  frag.append(
    renderHeader(metrics),
    h('div', { class: 'stack' },
      renderCycle(metrics.issues),
      h('div', { class: 'pair' }, renderGates(metrics), renderDefects(metrics.issues)),
      renderCost(metrics),
      renderIssues(metrics),
    ),
    ...(note ? [note] : []),
  );
  return frag;
}

// ---------------------------------------------------------------- states

export function renderLoading() {
  const block = (cls) => h('div', { class: `skeleton ${cls}`, 'aria-hidden': 'true' });
  return h(
    'div',
    { class: 'state-loading', role: 'status' },
    h('span', { class: 'sr-only' }, 'Loading metrics'),
    block('sk-hero'),
    block('sk-panel'),
    block('sk-panel short'),
  );
}

export function renderEmpty({ generatedAt, repo } = {}) {
  return h(
    'section',
    { class: 'state state-empty', 'aria-labelledby': 'state-title' },
    h('p', { class: 'eyebrow' }, 'Autonomous SDLC'),
    h('h1', { id: 'state-title' }, 'No metrics yet'),
    h(
      'p',
      {},
      'The orchestrator has not published any issue data. Once it processes its first issue it writes ',
      h('code', {}, 'metrics.json'),
      ' and this page fills in.',
    ),
    generatedAt || repo
      ? h('p', { class: 'meta' }, repo ? `${repo}. ` : '', generatedAt ? `Last published ${formatTimestamp(generatedAt)}.` : '')
      : null,
  );
}

export function renderError(message, onRetry) {
  return h(
    'section',
    { class: 'state state-error', role: 'alert', 'aria-labelledby': 'state-title' },
    h('p', { class: 'eyebrow' }, 'Autonomous SDLC'),
    h('h1', { id: 'state-title' }, 'Metrics could not be loaded'),
    h('p', {}, message),
    h('button', { type: 'button', class: 'button', onclick: onRetry }, 'Try again'),
  );
}
