// #/environments: Staging and production environments, verification gates, rollbacks, and deploy history.

import { badge, emptyState, ghLink, h, panel, table, timeEl } from '../dom.js';
import { formatInteger, formatPercent, formatShortTime } from '../format.js';
import { failedGate, flaggedIssue, newestFirst, releaseRows, rollbackRows } from '../model.js';
import { pullUrl } from '../safe.js';
import { externalLabel, hopTitle, issueNumberLink, pageHead, runAnchor, shaLink } from './common.js';

const ROW_STATUS = {
  live: ['Live', 'good'],
  promoted: ['Promoted to production', 'info'],
  'smoke-passed': ['Smoke passed', 'info'],
  soaking: ['Soaking', 'warn'],
};

const OUTCOME = {
  ok: ['OK', 'good'],
  failed: ['Failed', 'bad'],
  skipped: ['Skipped', 'neutral'],
  pending: ['Pending', 'warn'],
};

const ACTION_TONE = {
  promote: 'good',
  stage: 'info',
  skip: 'neutral',
  rollback: 'bad',
  fail: 'bad',
  'legacy-publish': 'info',
};

const actionTone = (action) => ACTION_TONE[action] ?? 'neutral';

export const outcomeBadge = (outcome) => {
  const [label, tone] = OUTCOME[outcome] ?? [outcome || 'Unknown', 'neutral'];
  return badge(label, tone, 'outcome-badge');
};

function includesList(includes) {
  if (includes.length === 0) return h('p', { class: 'muted includes-empty' }, 'No changes recorded for this build.');
  return h(
    'ul',
    { class: 'includes' },
    ...includes.map((i) =>
      h(
        'li',
        { class: 'include-item' },
        i.pr !== null ? ghLink(pullUrl(i.pr), externalLabel(`PR #${i.pr}`), { class: 'ext pr-badge' }) : null,
        i.issue !== null ? h('span', { class: 'ticket-ref-inline' }, 'ticket ', issueNumberLink(i.issue)) : h('span', { class: 'muted no-ticket-note' }, 'maintenance, no ticket'),
        i.sha ? shaLink(i.sha) : null,
      ),
    ),
  );
}

function gateChips(cleared = []) {
  const standardGates = ['smoke', 'soak'];
  const otherCleared = cleared.filter((g) => !standardGates.includes(g));
  const chips = [
    ...standardGates.map((g) => {
      const isCleared = cleared.includes(g);
      return h(
        'li',
        null,
        badge(
          isCleared ? `${g} cleared` : `${g} not cleared`,
          isCleared ? 'good' : 'neutral',
          isCleared ? 'gate-cleared' : 'gate-not-cleared',
        ),
      );
    }),
    ...otherCleared.map((g) =>
      h('li', null, badge(`${g} cleared`, 'good', 'gate-cleared')),
    ),
  ];

  return h('ul', { class: 'chips-inline gates-list', 'aria-label': 'Gates cleared' }, ...chips);
}

function envCard({ row, previous, title, path, siteHref, now }) {
  const isProd = title === 'Production';
  const envClass = isProd ? 'env-prod' : 'env-staging';
  const [statusLabel, statusTone] = (row && ROW_STATUS[row.status]) || [row?.status ?? '', 'neutral'];

  return h(
    'section',
    { class: `panel env-card ${envClass}`, 'aria-labelledby': `env-${title.toLowerCase()}` },
    h(
      'div',
      { class: 'panel-head env-card-head' },
      h(
        'div',
        { class: 'panel-titles' },
        h(
          'div',
          { class: 'env-title-row' },
          h('span', { class: `env-beacon ${isProd ? 'beacon-prod' : 'beacon-staging'}`, 'aria-hidden': 'true' }),
          h('h2', { id: `env-${title.toLowerCase()}` }, title),
          row?.status ? badge(statusLabel, statusTone, 'env-status-badge') : null,
        ),
        h(
          'p',
          { class: 'lede env-endpoint' },
          'Served at ',
          h('a', { href: siteHref, class: 'env-url-link' }, h('code', null, path)),
        ),
      ),
    ),
    !row
      ? h('p', { class: 'muted env-empty-notice' }, 'Nothing deployed here yet.')
      : [
          h(
            'div',
            { class: 'env-version-banner' },
            h(
              'div',
              { class: 'env-version-block' },
              h('span', { class: 'env-eyebrow' }, 'Active build'),
              h('p', { class: 'env-version' }, row.version ?? 'unversioned'),
            ),
            row.tag
              ? h(
                  'div',
                  { class: 'env-tag-block' },
                  h('span', { class: 'env-tag-label' }, 'Release tag'),
                  h('code', { class: 'env-tag-code' }, row.tag),
                )
              : null,
          ),
          h(
            'dl',
            { class: 'stats stats-wide env-meta-stats' },
            h('div', { class: 'stat' }, h('dt', null, 'Commit'), h('dd', null, row.sha ? shaLink(row.sha) : '-')),
            h(
              'div',
              { class: 'stat' },
              h('dt', null, isProd ? 'Promoted' : 'Deployed'),
              h(
                'dd',
                null,
                row.at
                  ? [timeEl(row.at, now), h('span', { class: 'muted time-utc' }, ` (${formatShortTime(row.at)})`)]
                  : '-',
              ),
            ),
            h(
              'div',
              { class: 'stat' },
              h('dt', null, 'Run'),
              h('dd', null, runAnchor(row.run_url, 'Workflow run') ?? h('span', { class: 'muted' }, 'none')),
            ),
            row.tag && !row.version
              ? h('div', { class: 'stat' }, h('dt', null, 'Tag'), h('dd', null, h('code', { class: 'wrap' }, row.tag)))
              : null,
          ),
          h(
            'div',
            { class: 'env-sub-section' },
            h('h3', { class: 'env-sub-heading' }, 'Gates cleared'),
            gateChips(row.gates_cleared),
          ),
          h(
            'div',
            { class: 'env-sub-section' },
            h(
              'div',
              { class: 'env-includes-header' },
              h('h3', { class: 'env-sub-heading' }, 'Included changes'),
              h('span', { class: 'badge tone-neutral count-badge' }, `${row.includes.length} recorded`),
            ),
            includesList(row.includes),
          ),
          previous
            ? h(
                'div',
                { class: 'env-previous-build' },
                h('span', { class: 'prev-label' }, 'Previous production build: '),
                h('strong', null, previous.version ?? 'unversioned'),
                previous.sha ? [' ', shaLink(previous.sha)] : null,
              )
            : null,
        ],
  );
}

function kpiCockpit(state, cf) {
  const env = state.environments;
  const rollbacks = env.rollbacks;
  const historyLen = env.history.length;
  const cfRate = cf?.rate;

  const tile = (label, value, sub, tone = '') =>
    h(
      'div',
      { class: `kpi ${tone}`.trim() },
      h('div', { class: 'kpi-label l' }, label),
      h('div', { class: 'kpi-value v metric' }, value),
      sub ? h('span', { class: 'kpi-sub muted' }, sub) : null,
    );

  const prodVersion = env.prod?.version ?? 'None';
  const stagingVersion = env.staging?.version ?? 'None';
  const cfrText = cfRate === null ? 'N/A' : formatPercent(cfRate);
  const cfrSub = cfRate === null ? 'No data' : `${formatInteger(cf.failed)} of ${formatInteger(cf.releases)} failed`;
  const cfrTone = cfRate !== null && cfRate > 0.3 ? 'kpi-bad' : cfRate !== null && cfRate > 0 ? 'kpi-warn' : 'kpi-good';
  const rbTone = rollbacks > 0 ? 'kpi-bad' : 'kpi-good';

  return h(
    'div',
    { class: 'kpis env-kpis', 'aria-label': 'Environment key metrics' },
    tile('Production', prodVersion, env.prod?.status ? `Status: ${env.prod.status}` : 'No active build', env.prod ? 'kpi-good' : ''),
    tile('Staging', stagingVersion, env.staging?.status ? `Status: ${env.staging.status}` : 'No active build', env.staging ? 'kpi-info' : ''),
    tile('Change failure rate', cfrText, cfrSub, cfrTone),
    tile('Rollbacks', formatInteger(rollbacks), rollbacks === 1 ? '1 failure recorded' : `${formatInteger(rollbacks)} failures recorded`, rbTone),
    tile('Deploy events', formatInteger(historyLen), 'Total lifecycle events', ''),
  );
}

function rollbackPanel(state, now) {
  const rows = rollbackRows(state);
  const count = state.environments.rollbacks;
  return panel(
    {
      id: 'rollbacks',
      title: 'Rollbacks and failures',
      lede: `${formatInteger(count)} recorded. Each one means a gate failed after a build reached an environment.`,
      actions: count > 0 ? badge(`${formatInteger(count)} failure`, 'bad') : badge('Zero failures', 'good'),
    },
    rows.length === 0
      ? h('p', { class: 'muted empty-notice' }, 'No rollbacks recorded. All releases met verification gates.')
      : table({
          caption: 'Rollback and failure history',
          head: ['When', 'Build', 'Gate that failed', 'Ticket flagged', 'Reason', 'Run'],
          rows: rows.map((e) => {
            const issue = flaggedIssue(e);
            const gate = failedGate(e.reason);
            return [
              timeEl(e.at, now),
              h('span', { class: 'cell-build' }, e.version ?? 'unversioned', e.sha ? shaLink(e.sha) : null),
              gate ? badge(gate, 'bad', 'gate-fail-pill') : h('span', { class: 'muted' }, 'not recorded'),
              issue !== null
                ? issueNumberLink(issue)
                : e.pr !== null
                  ? ghLink(pullUrl(e.pr), externalLabel(`PR #${e.pr}`), { class: 'ext' })
                  : h('span', { class: 'muted' }, 'none'),
              h('span', { class: 'clamp-2 wrap rb-reason' }, e.reason ?? ''),
              runAnchor(e.run_url, 'Run') ?? h('span', { class: 'muted' }, 'none'),
            ];
          }),
        }),
  );
}

function releasesPanel(state, now) {
  const rows = releaseRows(state);
  const cf = state.flow.change_failure;
  const ledeText =
    cf.rate === null
      ? 'One row per build that reached staging.'
      : `Change failure rate ${formatPercent(cf.rate)}: ${formatInteger(cf.failed)} of ${formatInteger(cf.releases)} finished releases failed.`;

  return panel(
    {
      id: 'releases',
      title: 'Releases',
      lede: ledeText,
      actions:
        cf.rate !== null
          ? badge(`CFR ${formatPercent(cf.rate)}`, cf.rate > 0.3 ? 'bad' : cf.rate > 0 ? 'warn' : 'good')
          : null,
    },
    h(
      'div',
      { class: 'cfr-summary-card' },
      h(
        'div',
        { class: 'cfr-stat-left' },
        h('span', { class: 'cfr-label' }, 'Change failure rate'),
        h(
          'span',
          {
            class: `cfr-rate-value ${cf.rate !== null && cf.rate > 0.3 ? 'cfr-bad' : cf.rate !== null && cf.rate > 0 ? 'cfr-warn' : 'cfr-good'}`,
          },
          cf.rate === null ? 'N/A' : formatPercent(cf.rate),
        ),
      ),
      h(
        'div',
        { class: 'cfr-stat-right' },
        h(
          'p',
          { class: 'cfr-stat-detail' },
          cf.rate === null
            ? 'No finished releases recorded yet.'
            : `${formatInteger(cf.failed)} of ${formatInteger(cf.releases)} finished releases failed.`,
        ),
        h(
          'p',
          { class: 'muted cfr-desc' },
          'Measures stability of changes arriving in staging and progressing to production. Target is under 15%.',
        ),
      ),
    ),
    rows.length === 0
      ? h('p', { class: 'muted empty-notice' }, 'No releases recorded yet.')
      : table({
          caption: 'Releases and their outcome',
          head: ['Version', 'Commit', 'Built', 'Outcome', 'Tickets', 'Run'],
          rows: rows.map((r) => [
            h('span', { class: 'release-version' }, r.version ?? 'unversioned'),
            r.sha ? shaLink(r.sha) : h('span', { class: 'muted' }, '-'),
            r.at ? timeEl(r.at, now) : h('span', { class: 'muted' }, '-'),
            outcomeBadge(r.outcome),
            r.issues.length > 0
              ? h('span', { class: 'refs' }, ...r.issues.map((i) => issueNumberLink(i)))
              : h('span', { class: 'muted' }, 'none'),
            runAnchor(r.run_url, 'Run') ?? h('span', { class: 'muted' }, 'none'),
          ]),
        }),
  );
}

function historyPanel(state, now) {
  const rows = newestFirst(state.environments.history);
  return panel(
    {
      id: 'history',
      title: 'Deploy history',
      lede: 'Chronological event timeline: every deploy, promotion, skip and rollback, newest first.',
      actions: badge(`${formatInteger(rows.length)} events`, 'neutral'),
    },
    rows.length === 0
      ? h('p', { class: 'muted empty-notice' }, 'No deploys yet.')
      : h(
          'ol',
          { class: 'hops deploy-timeline' },
          ...rows.map((e) => {
            const issue = flaggedIssue(e);
            return h(
              'li',
              { class: `hop hop-${e.action}` },
              h('span', { class: `hop-dot hop-dot-${e.action}`, 'aria-hidden': 'true' }),
              h(
                'div',
                { class: 'hop-body' },
                h(
                  'div',
                  { class: 'hop-header' },
                  h('p', { class: 'hop-title' }, hopTitle(e)),
                  e.version ? h('span', { class: 'badge tone-neutral hop-ver' }, e.version) : null,
                  badge(e.action, actionTone(e.action), 'hop-pill'),
                ),
                h(
                  'div',
                  { class: 'hop-meta' },
                  timeEl(e.at, now),
                  e.sha ? shaLink(e.sha) : null,
                  issue !== null ? h('span', { class: 'hop-ticket' }, 'ticket ', issueNumberLink(issue)) : null,
                  runAnchor(e.run_url, 'Run'),
                ),
                e.reason ? h('p', { class: 'hop-detail clamp-3 wrap hop-reason' }, e.reason) : null,
              ),
            );
          }),
        ),
  );
}

export function renderEnvironments(ctx) {
  const { state, now } = ctx;
  const env = state.environments;
  if (env.source === 'none') {
    return h(
      'div',
      { class: 'view' },
      pageHead({ title: 'Environments', lede: 'Staging and production, and how changes move between them.' }),
      emptyState(
        'CD has not run yet',
        'No deploy record exists. Once a merged change goes through the delivery pipeline, staging, production and every rollback show up here.',
      ),
    );
  }
  return h(
    'div',
    { class: 'view environments-view' },
    pageHead({ title: 'Environments', lede: `Staging first, production after smoke and soak. Source: ${env.source}.` }),
    kpiCockpit(state, state.flow.change_failure),
    h(
      'div',
      { class: 'grid-2 env-grid' },
      envCard({ row: env.staging, previous: null, title: 'Staging', path: '/staging/', siteHref: '../staging/', now }),
      envCard({ row: env.prod, previous: env.previous_prod, title: 'Production', path: '/', siteHref: '../', now }),
    ),
    rollbackPanel(state, now),
    releasesPanel(state, now),
    historyPanel(state, now),
  );
}
