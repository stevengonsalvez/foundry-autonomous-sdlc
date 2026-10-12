// #/escalations  Everything the pipeline stopped on and handed to a human, newest first.

import { badge, emptyState, ghLink, h, timeEl } from '../dom.js';
import { escalationLabel, formatInteger, formatUsd, plural, titleCase } from '../format.js';
import { escalationList } from '../model.js';
import { dataLink } from '../safe.js';
import { envBadgeFor, externalLabel, flagBadges, pageHead, ticketRef } from './common.js';

const TYPE_TONE = { feature: 'info', bug: 'bad', maintenance: 'neutral', unclassified: 'neutral' };

function agentTriedSteps(ticket) {
  const esc = ticket.escalation;
  const tried = esc?.tried ?? [];
  if (tried.length > 0) return tried;

  const fallback = [];
  if (ticket.coder) {
    const c = ticket.coder;
    const engine = c.engine ?? 'n/a';
    const iters = c.iterations ?? 0;
    const attempts = c.attempts ?? 1;
    const status = c.status ?? 'unknown';
    const jobId = c.job_id ?? 'unknown';
    fallback.push(`Coder job ${jobId}: ${status}, engine ${engine}, ${iters} iteration(s), attempt ${attempts}.`);
  }
  if (ticket.reviews && ticket.reviews.length > 0) {
    for (const r of ticket.reviews) {
      fallback.push(`Reviewer verdict: ${r.verdict}.`);
    }
  }
  if (ticket.hops && ticket.hops.length > 0) {
    for (const hop of ticket.hops) {
      const action = titleCase(hop.action);
      const status = hop.status ?? 'unknown';
      const detail = hop.detail ? ` (${hop.detail})` : '';
      fallback.push(`${action} on ${hop.env}: ${status}${detail}.`);
    }
  }
  return fallback;
}

/** One escalation as a card. Used here and, without the ticket header, on the ticket page. */
export function escalationCard(ticket, nowMs, { header = true } = {}) {
  const esc = ticket.escalation;
  if (!esc) return null;

  const ticketNum = ticket.number ?? ticket.issue;
  const evidence = dataLink(esc.evidence_url);
  const isRolledBack = ticket.env === 'rolled-back' || (ticket.flags && ticket.flags.includes('rolled-back'));
  const typeName = ticket.type === 'unclassified' ? 'New' : titleCase(ticket.type);

  const tags = [
    badge(escalationLabel(esc.label), 'bad', 'badge-esc-kind'),
    h('code', { class: 'esc-code' }, esc.label),
  ];

  if (header) {
    tags.push(badge(typeName, TYPE_TONE[ticket.type] ?? 'neutral', 'badge-type'));
    if (isRolledBack) {
      tags.push(badge('Rolled back', 'bad', 'badge-rollback'));
    } else {
      const envBadge = envBadgeFor(ticket);
      if (envBadge) tags.push(envBadge);
    }
    const otherFlags = (ticket.flags || []).filter((f) => f !== 'rolled-back');
    tags.push(...flagBadges(otherFlags));
  } else if (isRolledBack) {
    tags.push(badge('Rolled back', 'bad', 'badge-rollback'));
  }

  const reasons = esc.reasons ?? [];
  const triedItems = agentTriedSteps(ticket);

  return h(
    'article',
    {
      class: 'esc-card',
      'aria-label': `Escalation: #${ticketNum} ${escalationLabel(esc.label)}`,
      'data-stage': 'escalated',
    },
    h(
      'header',
      { class: 'esc-head' },
      header ? h('div', { class: 'esc-ticket' }, ticketRef(ticket, { titleClass: 'clamp-2' })) : null,
      h('div', { class: 'esc-tags' }, ...tags),
    ),
    h(
      'dl',
      { class: 'esc-meta' },
      h('div', { class: 'esc-meta-item' }, h('dt', null, 'Escalated'), h('dd', null, esc.at ? timeEl(esc.at, nowMs) : '-')),
      h('div', { class: 'esc-meta-item' }, h('dt', null, 'Agent attempts'), h('dd', null, formatInteger(esc.attempts))),
      h(
        'div',
        { class: 'esc-meta-item' },
        h('dt', null, 'Evidence'),
        h('dd', null, evidence ? ghLink(evidence, externalLabel('Open evidence'), { class: 'ext' }) : h('span', { class: 'muted' }, 'none recorded')),
      ),
      ticket.cost
        ? h('div', { class: 'esc-meta-item' }, h('dt', null, 'Spend so far'), h('dd', null, formatUsd(ticket.cost.usd)))
        : null,
    ),
    h(
      'div',
      { class: 'esc-cols' },
      h(
        'section',
        { class: 'esc-section esc-section-stopped', 'aria-label': 'Why it stopped' },
        h('h3', { class: 'esc-section-title' }, 'Why it stopped'),
        reasons.length > 0
          ? h('ul', { class: 'bullets esc-reasons-list' }, ...reasons.map((r) => h('li', null, h('span', { class: 'clamp-4 wrap' }, r))))
          : h('p', { class: 'muted' }, 'No reason recorded.'),
      ),
      h(
        'section',
        { class: 'esc-section esc-section-tried', 'aria-label': 'What the agent tried' },
        h('h3', { class: 'esc-section-title' }, 'What the agent tried'),
        triedItems.length > 0
          ? h('ol', { class: 'bullets steps esc-tried-list' }, ...triedItems.map((item) => h('li', null, h('span', { class: 'clamp-3 wrap' }, item))))
          : h('p', { class: 'muted' }, 'Nothing recorded before it stopped.'),
      ),
    ),
    header
      ? h(
          'footer',
          { class: 'esc-foot' },
          h('a', { class: 'btn btn-secondary btn-sm', href: `#/ticket/${ticketNum}` }, 'Open ticket'),
        )
      : null,
  );
}

function escalationKpis(list) {
  let buildFailed = 0;
  let deployFailed = 0;
  let notSuitable = 0;
  let rolledBack = 0;

  for (const t of list) {
    const label = t.escalation?.label ?? '';
    if (label.includes('build-failed')) buildFailed++;
    else if (label.includes('deploy-failed')) deployFailed++;
    else if (label.includes('not-agent-suitable')) notSuitable++;

    if (t.env === 'rolled-back' || (t.flags && t.flags.includes('rolled-back'))) {
      rolledBack++;
    }
  }

  const kpiTile = (label, count, tone = '') =>
    h('div', { class: `kpi ${tone}`.trim() }, h('dt', null, label), h('dd', null, formatInteger(count)));

  return h(
    'dl',
    { class: 'kpis esc-kpis', 'aria-label': 'Escalation summary metrics' },
    kpiTile('Total escalated', list.length, 'kpi-bad'),
    kpiTile('Build failed', buildFailed),
    kpiTile('Deploy failed', deployFailed),
    kpiTile('Not agent suitable', notSuitable),
    rolledBack > 0 ? kpiTile('Rolled back', rolledBack, 'kpi-bad') : null,
  );
}

export function renderEscalations(ctx) {
  const { state, now } = ctx;
  const list = escalationList(state);
  const count = list.length;
  const lede = count > 0
    ? `${formatInteger(count)} ${plural(count, 'ticket')} stopped for a human, newest first.`
    : 'Tickets the pipeline stopped on and handed to a human.';

  return h(
    'div',
    { class: 'view view-escalations' },
    pageHead({
      eyebrow: 'Pipeline exceptions',
      title: 'Escalations',
      lede,
    }),
    count > 0 ? escalationKpis(list) : null,
    count === 0
      ? emptyState(
          'Nothing escalated',
          'Every ticket is moving, or has finished. Escalations appear here the moment an agent gives up.',
        )
      : h('div', { class: 'esc-list' }, ...list.map((t) => escalationCard(t, now))),
  );
}
