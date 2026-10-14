// #/environments  Staging and production, what each runs, how it got there, and every rollback.

import { badge, classToken, emptyState, ghLink, h, panel, table, timeEl } from '../dom.js';
import { formatInteger, formatPercent, formatShortTime } from '../format.js';
import { failedGate, flaggedIssue, newestFirst, releaseRows, rollbackRows } from '../model.js';
import { pullUrl } from '../safe.js';
import { externalLabel, hopTitle, issueNumberLink, pageHead, runAnchor, shaLink } from './common.js';

export const ROW_STATUS = Object.freeze({
  live: ['Live', 'good'],
  promoted: ['Promoted to production', 'info'],
  'smoke-passed': ['Smoke passed', 'info'],
  soaking: ['Soaking', 'warn'],
});

export const OUTCOME = Object.freeze({ ok: ['OK', 'good'], failed: ['Failed', 'bad'], skipped: ['Skipped', 'neutral'], pending: ['Pending', 'warn'] });

export const outcomeBadge = (outcome) => {
  const [label, tone] = OUTCOME[outcome] ?? [outcome || 'Unknown', 'neutral'];
  return badge(label, tone);
};

function includesList(includes) {
  if (includes.length === 0) return h('p', { class: 'muted' }, 'No changes recorded for this build.');
  return h(
    'ul',
    { class: 'includes' },
    ...includes.map((i) =>
      h(
        'li',
        null,
        i.pr !== null ? ghLink(pullUrl(i.pr), externalLabel(`PR #${i.pr}`), { class: 'ext' }) : null,
        i.issue !== null ? h('span', null, 'ticket ', issueNumberLink(i.issue)) : h('span', { class: 'muted' }, 'maintenance, no ticket'),
        i.sha ? shaLink(i.sha) : null,
      ),
    ),
  );
}

function gateChips(cleared) {
  return h(
    'ul',
    { class: 'chips-inline', 'aria-label': 'Gates cleared' },
    ...['smoke', 'soak'].map((g) => h('li', null, cleared.includes(g) ? badge(`${g} cleared`, 'good') : badge(`${g} not cleared`, 'neutral'))),
  );
}

function envCard({ row, previous, title, path, siteHref, now }) {
  const [statusLabel, statusTone] = (row && ROW_STATUS[row.status]) || [row?.status ?? '', 'neutral'];
  return h(
    'section',
    { class: `panel env-card env-${title.toLowerCase()}`, 'aria-labelledby': `env-${title.toLowerCase()}` },
    h(
      'div',
      { class: 'panel-head' },
      h('div', { class: 'panel-titles' }, h('h2', { id: `env-${title.toLowerCase()}` }, title), h('p', { class: 'lede' }, 'Served at ', h('a', { href: siteHref }, h('code', null, path)))),
      row?.status ? badge(statusLabel, statusTone) : null,
    ),
    !row
      ? h('p', { class: 'muted' }, 'Nothing deployed here yet.')
      : [
          h('p', { class: 'env-version' }, row.version ?? 'unversioned'),
          h(
            'dl',
            { class: 'stats stats-wide' },
            h('div', { class: 'stat' }, h('dt', null, 'Commit'), h('dd', null, row.sha ? shaLink(row.sha) : '-')),
            h('div', { class: 'stat' }, h('dt', null, title === 'Staging' ? 'Deployed' : 'Promoted'), h('dd', null, row.at ? [timeEl(row.at, now), h('span', { class: 'muted' }, ` (${formatShortTime(row.at)})`)] : '-')),
            h('div', { class: 'stat' }, h('dt', null, 'Run'), h('dd', null, runAnchor(row.run_url, 'Open run') ?? h('span', { class: 'muted' }, 'none'))),
            row.tag ? h('div', { class: 'stat' }, h('dt', null, 'Tag'), h('dd', null, h('code', { class: 'wrap' }, row.tag))) : null,
          ),
          h('h3', null, 'Gates cleared'),
          gateChips(row.gates_cleared),
          h('h3', null, 'Included changes'),
          includesList(row.includes),
          previous ? h('p', { class: 'footnote' }, 'Previous production build: ', h('strong', null, previous.version ?? 'unversioned'), previous.sha ? [' ', shaLink(previous.sha)] : null) : null,
        ],
  );
}

function rollbackPanel(state, now) {
  const rows = rollbackRows(state);
  return panel(
    { id: 'rollbacks', title: 'Rollbacks and failures', lede: `${formatInteger(state.environments.rollbacks)} recorded. Each one means a gate failed after a build reached an environment.` },
    rows.length === 0
      ? h('p', { class: 'muted' }, 'No rollbacks yet.')
      : table({
          caption: 'Rollback and failure history',
          head: ['When', 'Build', 'Gate that failed', 'Ticket flagged', 'Reason', 'Run'],
          rows: rows.map((e) => {
            const issue = flaggedIssue(e);
            return [
              timeEl(e.at, now),
              h('span', { class: 'cell-build' }, e.version ?? 'unversioned', e.sha ? shaLink(e.sha) : null),
              failedGate(e.reason) ?? h('span', { class: 'muted' }, 'not recorded'),
              issue !== null ? issueNumberLink(issue) : e.pr !== null ? ghLink(pullUrl(e.pr), `PR #${e.pr}`, { class: 'ext' }) : h('span', { class: 'muted' }, 'none'),
              h('span', { class: 'clamp-2 wrap' }, e.reason ?? ''),
              runAnchor(e.run_url, 'Run') ?? h('span', { class: 'muted' }, 'none'),
            ];
          }),
        }),
  );
}

function releasesPanel(state, now) {
  const rows = releaseRows(state);
  const cf = state.flow.change_failure;
  return panel(
    {
      id: 'releases',
      title: 'Releases',
      lede: cf.rate === null ? 'One row per build that reached staging.' : `Change failure rate ${formatPercent(cf.rate)}: ${formatInteger(cf.failed)} of ${formatInteger(cf.releases)} finished releases failed.`,
    },
    rows.length === 0
      ? h('p', { class: 'muted' }, 'No releases yet.')
      : table({
          caption: 'Releases and their outcome',
          head: ['Version', 'Commit', 'Built', 'Outcome', 'Tickets', 'Run'],
          rows: rows.map((r) => [
            r.version ?? 'unversioned',
            r.sha ? shaLink(r.sha) : '-',
            r.at ? timeEl(r.at, now) : '-',
            outcomeBadge(r.outcome),
            r.issues.length > 0 ? h('span', { class: 'refs' }, ...r.issues.map((i) => issueNumberLink(i))) : h('span', { class: 'muted' }, 'none'),
            runAnchor(r.run_url, 'Run') ?? h('span', { class: 'muted' }, 'none'),
          ]),
        }),
  );
}

function historyPanel(state, now) {
  const rows = newestFirst(state.environments.history);
  return panel(
    { id: 'history', title: 'Deploy history', lede: 'Every deploy, promotion, skip and rollback, newest first.' },
    rows.length === 0
      ? h('p', { class: 'muted' }, 'No deploys yet.')
      : h(
          'ol',
          { class: 'hops' },
          ...rows.map((e) => {
            const actionCls = classToken(e.action);
            return h(
              'li',
              { class: `hop hop-${actionCls}` },
              h('span', { class: 'hop-dot', 'aria-hidden': 'true' }),
              h(
                'div',
                { class: 'hop-body' },
                h('p', { class: 'hop-title' }, hopTitle(e), e.version ? h('span', { class: 'muted' }, ` ${e.version}`) : null),
                h(
                  'p',
                  { class: 'hop-meta' },
                  timeEl(e.at, now),
                  e.sha ? shaLink(e.sha) : null,
                  flaggedIssue(e) !== null ? h('span', null, 'ticket ', issueNumberLink(flaggedIssue(e))) : null,
                  runAnchor(e.run_url, 'Run'),
                ),
                e.reason ? h('p', { class: 'hop-detail clamp-3 wrap' }, e.reason) : null,
              ),
            );
          }),
        ),
  );
}

function environmentsMatrix(env, now) {
  const rows = [
    { target: 'staging', name: 'Staging', row: env.staging, path: '/staging/', siteHref: '../staging/' },
    { target: 'prod', name: 'Production', row: env.prod, path: '/', siteHref: '../' },
  ];

  return panel(
    { id: 'environments-matrix', title: 'Target environments', lede: 'Target environments and current live deployments.', className: 'panel-wide' },
    table({
      caption: 'Target environments deployment status matrix',
      head: ['Environment', 'Version', 'Commit', 'Deployed', 'Gates cleared', 'Run', 'Included changes'],
      rows: rows.map(({ name, row, path, siteHref }) => {
        if (!row) {
          return [
            h('div', { class: 'env-target-head' }, h('strong', null, name), h('span', { class: 'muted' }, path)),
            h('span', { class: 'muted' }, '-'),
            h('span', { class: 'muted' }, '-'),
            h('span', { class: 'muted' }, '-'),
            h('span', { class: 'muted' }, 'none'),
            h('span', { class: 'muted' }, 'none'),
            h('span', { class: 'muted' }, 'No changes recorded'),
          ];
        }
        const [statusLabel, statusTone] = (row && ROW_STATUS[row.status]) || [row?.status ?? '', 'neutral'];
        return [
          h(
            'div',
            { class: 'env-target-head' },
            h('strong', null, name),
            ' ',
            statusLabel ? badge(statusLabel, statusTone) : null,
            h('a', { class: 'env-path-link', href: siteHref }, h('code', null, path)),
          ),
          h('span', { class: 'env-version mono' }, row.version ?? 'unversioned'),
          row.sha ? shaLink(row.sha) : h('span', { class: 'muted' }, '-'),
          row.at ? timeEl(row.at, now) : h('span', { class: 'muted' }, '-'),
          gateChips(row.gates_cleared || []),
          runAnchor(row.run_url, 'Run') ?? h('span', { class: 'muted' }, 'none'),
          includesList(row.includes || []),
        ];
      }),
    }),
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
      emptyState('CD has not run yet', 'No deploy record exists. Once a merged change goes through the delivery pipeline, staging, production and every rollback show up here.'),
    );
  }
  return h(
    'div',
    { class: 'view view-environments' },
    pageHead({ title: 'Environments', lede: `Staging first, production after smoke and soak. Source: ${env.source}.` }),
    environmentsMatrix(env, now),
    rollbackPanel(state, now),
    releasesPanel(state, now),
    historyPanel(state, now),
  );
}
