// #/ticket/<n>  One ticket end to end: where it is, what it cost, which gates it cleared, where it
// ran, what the agents asked and decided, and why it stopped if it did.

import { stepper, NODE_STATES } from '../charts.js';
import { badge, chartHost, classToken, dataTable, emptyState, ghLink, h, panel, table, timeEl } from '../dom.js';
import { formatDuration, formatInteger, formatShortTime, formatUsd, titleCase } from '../format.js';
import { icon } from '../icons.js';
import { GATES, GATE_STATUSES, gateStatus, pipelineChain, stageDurations, stageLabel, tddOrder } from '../model.js';
import { dataLink } from '../safe.js';
import { escalationCard } from './escalations.js';
import {
  costBar,
  envBadgeFor,
  externalLabel,
  flagBadges,
  hopTitle,
  prUrl,
  releaseLink,
  runAnchor,
  shaLink,
  stageBadge,
  stageFill,
  ticketGithubUrl,
  typeBadge,
} from './common.js';
import { ciBlock, qaBlock, reviewBlock } from './trail.js';

export const GATE_LABELS = Object.freeze({
  test: 'Tests',
  coverage: 'Coverage',
  e2e: 'End to end',
  gitleaks: 'Secret scan',
  'tdd-order': 'Tests first',
  'agent-scope': 'Agent scope',
  review: 'Review',
  smoke: 'Smoke',
  soak: 'Soak',
});

export { GATE_STATUSES };
export const CHAIN_STATUSES = Object.freeze(['pass', 'fail', 'running', 'skipped', 'none']);
const GATE_TEXT = { pass: 'Passed', fail: 'Failed', running: 'In progress', skipped: 'Skipped', none: 'Not run' };
const GATE_ICON = { pass: 'check', fail: 'cross', running: 'clock', skipped: 'dash', none: 'dash' };

// ------------------------------------------------------------------ pieces

function notFound(issue, pendingMatch) {
  const back = h('a', { class: 'btn btn-secondary', href: '#/' }, icon('back', { size: 16 }), 'Back to the board');
  if (pendingMatch) {
    return h(
      'div',
      { class: 'view' },
      emptyState('Waiting for the ledger', `Issue #${issue} was opened but the ledger has not recorded it yet. It will get a full page after the next tick.`, back, ghLink(ticketGithubUrl(pendingMatch), externalLabel('Open on GitHub'), { class: 'btn btn-secondary' })),
    );
  }
  return h('div', { class: 'view' }, emptyState('Ticket not found', `There is no ticket #${issue} in the ledger. It may be archived, or the number may be wrong.`, back));
}

function latestRun(ticket) {
  const hop = [...ticket.hops].reverse().find((x) => dataLink(x.run_url));
  return hop?.run_url ?? ticket.escalation?.evidence_url ?? null;
}

function header(ticket, now) {
  const issueUrl = ticketGithubUrl(ticket);
  const pr = ticket.pr ? prUrl(ticket.pr) : null;
  const release = ticket.release ? releaseLink(ticket.release) : null;
  const run = runAnchor(latestRun(ticket), 'Latest run');
  return h(
    'header',
    { class: 'ticket-head' },
    h('a', { class: 'back-link', href: '#/' }, icon('back', { size: 14 }), 'All tickets'),
    h(
      'div',
      { class: 'ticket-title-row' },
      h('span', { class: 'ticket-num' }, ticket.kind === 'pr' ? `PR #${ticket.issue}` : `#${ticket.issue}`),
      h('h1', { class: 'ticket-title wrap' }, ticket.title || 'Untitled'),
    ),
    h(
      'div',
      { class: 'badge-row' },
      typeBadge(ticket.type),
      ticket.scenario ? badge(`Scenario ${ticket.scenario}`, 'neutral') : null,
      stageBadge(ticket.stage),
      envBadgeFor(ticket),
      ...flagBadges(ticket.flags),
    ),
    h(
      'p',
      { class: 'link-row' },
      ghLink(issueUrl, externalLabel(ticket.kind === 'pr' ? `PR #${ticket.issue}` : `Issue #${ticket.issue}`), { class: 'ext' }),
      pr && ticket.kind !== 'pr' ? ghLink(pr, externalLabel(`PR #${ticket.pr.number}`), { class: 'ext' }) : null,
      release ? ghLink(release, externalLabel(`Release ${ticket.release.tag}`), { class: 'ext' }) : null,
      run,
      ticket.opened_at ? h('span', { class: 'muted' }, 'Opened ', timeEl(ticket.opened_at, now)) : null,
      ticket.author ? h('span', { class: 'muted' }, 'by ', h('span', { class: 'wrap' }, ticket.author)) : null,
    ),
    ticket.summary ? h('p', { class: 'summary clamp-4 wrap' }, ticket.summary) : null,
  );
}

function stepperSteps(ticket, stages, now) {
  const found = new Map(stageDurations(ticket, now).map((d) => [d.stage, d]));
  return stages.map((stage) => {
    const d = found.get(stage);
    const terminal = stage === 'prod' || stage === 'escalated';
    let state = d ? NODE_STATES[1] : NODE_STATES[0];
    if (stage === ticket.stage) state = stage === 'escalated' ? NODE_STATES[3] : stage === 'prod' ? NODE_STATES[1] : NODE_STATES[2];
    else if (stage === 'escalated' && d) state = NODE_STATES[3];
    return { stage, label: stageLabel(stage), state, terminal, at: d?.at ?? null, seconds: d?.seconds ?? null, visits: d?.visits ?? 0, open: d?.open ?? false };
  });
}

function timelinePanel(ticket, stages, now) {
  const steps = stepperSteps(ticket, stages, now);
  const reached = steps.filter((s) => s.state !== 'todo');
  const summary = `Stage timeline for ticket ${ticket.issue}. ${reached.map((s) => `${s.label}${s.seconds !== null ? ` ${formatDuration(s.seconds)}` : ''}`).join(', ')}. Currently ${stageLabel(ticket.stage)}.`;
  return panel(
    { id: 'timeline', title: 'Stage timeline', lede: 'Time spent in each board column. A loop back (for example a second build attempt) counts as another visit.', className: 'panel-wide' },
    chartHost((width) => stepper(width, steps, { label: summary, stageClass: stageFill })),
    dataTable(
      'Show stage timing as a table',
      table({
        caption: `Stage timing for ticket ${ticket.issue}`,
        head: ['Stage', 'First entered', 'Time in stage', 'Visits'],
        numeric: [3],
        rows: reached.map((s) => [stageLabel(s.stage), s.at ? formatShortTime(s.at) : '-', s.seconds === null ? '-' : `${formatDuration(s.seconds)}${s.open && !s.terminal ? ' so far' : ''}`, String(s.visits)]),
      }),
    ),
  );
}

function gatesPanel(ticket) {
  const items = GATES.map((gate) => gateStatus(ticket, gate));
  return panel(
    { id: 'gates', title: 'Gates', lede: 'Checks the change had to clear. Review shows the reviewer verdict when no check was recorded.' },
    h(
      'ul',
      { class: 'gate-grid' },
      ...items.map((g) =>
        h(
          'li',
          { class: `gate gate-${g.status}`, title: `${g.gate}${g.derived ? ' (from the reviewer verdict)' : ''}` },
          h('span', { class: 'gate-icon' }, icon(GATE_ICON[g.status], { size: 14 })),
          h(
            'span',
            { class: 'gate-text' },
            h('span', { class: 'gate-name' }, GATE_LABELS[g.gate] ?? titleCase(g.gate)),
            ' ',
            h('span', { class: 'gate-state' }, GATE_TEXT[g.status], g.status === 'pass' && g.firstPass ? ' first try' : ''),
            g.attempts > 1 ? [' ', h('span', { class: 'gate-note' }, `${g.attempts} attempts`)] : g.derived ? [' ', h('span', { class: 'gate-note' }, 'from verdict')] : null,
          ),
        ),
      ),
    ),
  );
}

export const SPLIT = Object.freeze([
  ['model_usd', 'Model calls', 'split-model'],
  ['coder_usd', 'Coder runtime', 'split-coder'],
  ['coder_model_usd', 'Coder model', 'split-coder-model'],
  ['ledger_usd', 'Ledger compute', 'split-ledger'],
]);

function costPanel(ticket) {
  const c = ticket.cost;
  const parts = SPLIT.map(([key, label, cls]) => ({ label, cls, usd: c[key] }));
  const attributed = parts.reduce((n, p) => n + p.usd, 0);
  if (c.usd - attributed > 0.000001) parts.push({ label: 'Not itemised', cls: 'split-other', usd: c.usd - attributed });
  const total = Math.max(c.usd, attributed, Number.MIN_VALUE);
  return panel(
    { id: 'cost', title: 'Cost', lede: `Against the ${formatUsd(c.cap_usd)} cap for one issue.` },
    h(
      'div',
      { class: 'cost-total' },
      h('strong', { class: 'cost-amount' }, formatUsd(c.usd)),
      h('span', { class: 'cost-pct muted' }, `${Math.round(c.cap_used_pct)}% of the cap`),
    ),
    costBar(c.usd, c.cap_used_pct, { label: false }),
    h(
      'div',
      { class: 'split', role: 'img', 'aria-label': `Cost split: ${parts.map((p) => `${p.label} ${formatUsd(p.usd)}`).join(', ')}` },
      ...parts.filter((p) => p.usd > 0).map((p) => h('span', { class: `split-seg ${p.cls}`, vars: { w: `${(p.usd / total) * 100}%` }, title: `${p.label}: ${formatUsd(p.usd)}` })),
    ),
    h('ul', { class: 'legend' }, ...parts.map((p) => h('li', null, h('span', { class: `swatch ${p.cls}`, 'aria-hidden': 'true' }), `${p.label} `, h('span', { class: 'num' }, formatUsd(p.usd))))),
    h(
      'dl',
      { class: 'stats stats-mono cost-table' },
      h('div', { class: 'stat' }, h('dt', null, 'Calls'), h('dd', null, formatInteger(c.calls))),
      h('div', { class: 'stat' }, h('dt', null, 'Tokens in'), h('dd', null, formatInteger(c.tokens_in))),
      h('div', { class: 'stat' }, h('dt', null, 'Tokens out'), h('dd', null, formatInteger(c.tokens_out))),
      h('div', { class: 'stat' }, h('dt', null, 'Coder time'), h('dd', null, formatDuration(c.coder_seconds))),
    ),
    c.by_agent.length > 0
      ? table({
          caption: `Cost per agent for ticket ${ticket.issue}`,
          head: ['Agent', 'Calls', 'Tokens in', 'Tokens out', 'Spend'],
          numeric: [1, 2, 3, 4],
          rows: c.by_agent.map((a) => [h('code', null, a.agent), formatInteger(a.calls), formatInteger(a.in), formatInteger(a.out), formatUsd(a.usd)]),
        })
      : null,
  );
}

export const HOP_STATUS = Object.freeze({ success: ['Succeeded', 'good'], skipped: ['Skipped', 'neutral'], rolled_back: ['Rolled back', 'bad'], failed: ['Failed', 'bad'], in_progress: ['In progress', 'warn'] });
function hopsPanel(ticket, now) {
  const chain = pipelineChain(ticket);
  const legacy = ticket.hops.some((x) => x.action === 'legacy-publish');
  return panel(
    { id: 'hops', title: 'Environments', lede: 'Staging first, then smoke and soak, then production. Every hop and rollback in order.', className: 'panel-wide' },
    h(
      'ol',
      { class: 'chain', 'aria-label': 'Delivery path' },
      ...chain.map((node) =>
        h(
          'li',
          { class: `chain-node chain-${node.status}` },
          h('span', { class: 'chain-mark' }, icon(GATE_ICON[node.status] ?? 'dash', { size: 14 })),
          h('span', { class: 'chain-text' }, h('span', { class: 'chain-label' }, node.label), h('span', { class: 'chain-state' }, node.key === 'staging' || node.key === 'prod' ? { pass: 'Reached', fail: 'Failed', skipped: 'Skipped', running: 'In progress', none: 'Not reached' }[node.status] : GATE_TEXT[node.status], node.note ? ` (${node.note})` : '')),
        ),
      ),
    ),
    legacy ? h('p', { class: 'note' }, 'Legacy publish: this change went live before the CD pipeline existed, straight from main by the old Pages workflow. It has no staging, smoke or soak record.') : null,
    ticket.hops.length === 0
      ? h('p', { class: 'muted' }, 'No environment hops yet. The change has not been merged.')
      : h(
          'ol',
          { class: 'hops' },
          ...ticket.hops.map((hop) => {
            const status = HOP_STATUS[hop.status] ?? [titleCase(hop.status || 'Unknown'), 'neutral'];
            return h(
              'li',
              { class: `hop hop-${classToken(hop.status)}` },
              h('span', { class: 'hop-dot', 'aria-hidden': 'true' }),
              h(
                'div',
                { class: 'hop-body' },
                h('p', { class: 'hop-title' }, hopTitle(hop), ' ', badge(status[0], status[1])),
                h('p', { class: 'hop-meta' }, hop.at ? timeEl(hop.at, now) : null, hop.version ? h('span', null, hop.version) : null, hop.sha ? shaLink(hop.sha) : null, runAnchor(hop.run_url, 'Run')),
                hop.detail ? h('p', { class: 'hop-detail clamp-3 wrap' }, hop.detail) : null,
              ),
            );
          }),
        ),
  );
}

function commitsPanel(ticket) {
  const order = tddOrder(ticket.commits);
  const tdd = gateStatus(ticket, 'tdd-order');
  const verdict =
    order.status === 'tests-first'
      ? badge('Tests first', 'good')
      : order.status === 'impl-first'
        ? badge('Implementation before tests', 'bad')
        : tdd.status === 'pass'
          ? badge('Tests first (tdd-order check)', 'good')
          : tdd.status === 'fail'
            ? badge('tdd-order check failed', 'bad')
            : badge('Order not recorded', 'neutral');
  return panel(
    { id: 'pr', title: 'Pull request and commits', lede: 'The rule: a test: commit lands before the feat: or fix: commit that makes it pass.', actions: verdict },
    ticket.pr
      ? h(
          'dl',
          { class: 'stats stats-wide' },
          h('div', { class: 'stat' }, h('dt', null, 'Pull request'), h('dd', null, ghLink(prUrl(ticket.pr), externalLabel(`#${ticket.pr.number}`), { class: 'ext' }))),
          ticket.pr.branch ? h('div', { class: 'stat' }, h('dt', null, 'Branch'), h('dd', null, h('code', { class: 'wrap' }, ticket.pr.branch))) : null,
          ticket.pr.head ? h('div', { class: 'stat' }, h('dt', null, 'Head'), h('dd', null, shaLink(ticket.pr.head))) : null,
          ticket.pr.merge_sha ? h('div', { class: 'stat' }, h('dt', null, 'Merged as'), h('dd', null, shaLink(ticket.pr.merge_sha))) : null,
        )
      : h('p', { class: 'muted' }, 'No pull request yet.'),
    ticket.commits.length === 0
      ? h('p', { class: 'muted' }, 'The commit list was not recorded for this ticket.')
      : h(
          'ol',
          { class: 'commits' },
          ...ticket.commits.map((c, i) =>
            h(
              'li',
              { class: `commit${i === order.testIndex || i === order.implIndex ? ' commit-key' : ''}` },
              h('span', { class: 'commit-order' }, String(i + 1)),
              badge(c.kind, c.kind === 'test' ? 'good' : c.kind === 'feat' || c.kind === 'fix' ? 'info' : 'neutral'),
              h('span', { class: 'commit-msg clamp-2 wrap' }, c.message),
              c.sha ? shaLink(c.sha) : null,
              c.files > 0 ? h('span', { class: 'muted' }, `${c.files} ${c.files === 1 ? 'file' : 'files'}`) : null,
            ),
          ),
        ),
  );
}

function optStat(label, value) {
  return value === null || value === undefined ? null : h('div', { class: 'stat' }, h('dt', null, label), h('dd', null, value));
}

function workPanel(ticket) {
  const { coder, quality, feasibility, triage } = ticket;
  const nothing = !coder && !quality && !feasibility && !triage;
  return panel(
    { id: 'work', title: 'Refinement, feasibility and coder' },
    nothing ? h('p', { class: 'muted' }, 'Nothing recorded yet.') : null,
    quality
      ? h(
          'section',
          { class: 'sub' },
          h('h3', null, 'Requirement quality'),
          h('dl', { class: 'stats' }, optStat('Score', quality.score === null ? '-' : `${quality.score}/100`), optStat('Refinement rounds', formatInteger(quality.rounds))),
          quality.summary ? h('p', { class: 'clamp-4 wrap' }, quality.summary) : null,
        )
      : null,
    feasibility
      ? h(
          'section',
          { class: 'sub' },
          h('h3', null, 'Feasibility'),
          h('p', null, badge(feasibility.suitable ? 'Suitable for the coding agent' : 'Not suitable for an agent', feasibility.suitable ? 'good' : 'bad'), feasibility.risk ? [' ', badge(`Risk ${feasibility.risk}`, feasibility.risk === 'low' ? 'good' : feasibility.risk === 'high' ? 'bad' : 'warn')] : null),
          feasibility.reasons.length ? h('ul', { class: 'bullets' }, ...feasibility.reasons.map((r) => h('li', null, h('span', { class: 'clamp-3 wrap' }, r)))) : null,
        )
      : null,
    triage
      ? h('section', { class: 'sub' }, h('h3', null, 'Bug triage'), h('dl', { class: 'stats' }, optStat('Severity', triage.severity), optStat('Owner', triage.owner)), triage.summary ? h('p', { class: 'clamp-3 wrap' }, triage.summary) : null)
      : null,
    coder
      ? h(
          'section',
          { class: 'sub' },
          h('h3', null, 'Coder job'),
          h(
            'dl',
            { class: 'stats' },
            optStat('Status', coder.status),
            optStat('Engine', coder.engine),
            optStat('Mode', coder.mode),
            optStat('Attempts', formatInteger(coder.attempts)),
            optStat('Iterations', formatInteger(coder.iterations)),
            optStat('Elapsed', formatDuration(coder.elapsed_s)),
            coder.job_id ? optStat('Job', h('code', { class: 'wrap' }, coder.job_id)) : null,
          ),
        )
      : null,
  );
}

function runsPanel(ticket) {
  return panel(
    { id: 'runs', title: 'Agent runs', lede: 'Every model call made for this ticket, in order.' },
    ticket.agent_runs.length === 0
      ? h('p', { class: 'muted' }, 'No model calls recorded.')
      : table({
          caption: `Agent runs for ticket ${ticket.issue}`,
          head: ['#', 'Agent', 'Tokens in', 'Tokens out', 'Cost'],
          numeric: [2, 3, 4],
          rows: ticket.agent_runs.map((r, i) => [String(i + 1), h('code', null, r.agent), formatInteger(r.in), formatInteger(r.out), formatUsd(r.usd)]),
        }),
  );
}

function trailPanel(ticket) {
  const blocks = [];
  if (ticket.qa.length > 0) blocks.push(qaBlock(ticket.qa));
  for (const r of ticket.reviews) blocks.push(reviewBlock(r));
  if (ticket.ci_triage) blocks.push(ciBlock(ticket.ci_triage));
  return panel(
    { id: 'trail', title: 'Questions, reviews and CI triage', className: 'panel-wide' },
    blocks.length === 0 ? h('p', { class: 'muted' }, 'No questions were asked, no review has run and CI has not needed triage.') : h('div', { class: 'trail-stack' }, ...blocks),
  );
}

// ------------------------------------------------------------------ view

export function renderTicket(ctx, issue) {
  const { state, pending, now } = ctx;
  const ticket = state.tickets.find((t) => t.issue === issue);
  if (!ticket) return notFound(issue, pending.find((p) => p.issue === issue) ?? null);
  return h(
    'div',
    { class: 'view view-ticket' },
    header(ticket, now),
    ticket.escalation ? escalationCard(ticket, now, { header: false }) : null,
    timelinePanel(ticket, state.board_stages, now),
    h('div', { class: 'grid-2' }, gatesPanel(ticket), costPanel(ticket)),
    hopsPanel(ticket, now),
    h('div', { class: 'grid-2' }, commitsPanel(ticket), workPanel(ticket)),
    trailPanel(ticket),
    runsPanel(ticket),
  );
}

