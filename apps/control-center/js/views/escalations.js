// #/escalations  Everything the pipeline stopped on and handed to a human, newest first.

import { badge, emptyState, ghLink, h, timeEl } from '../dom.js';
import { escalationLabel, formatInteger, plural } from '../format.js';
import { escalationList } from '../model.js';
import { dataLink } from '../safe.js';
import { envBadgeFor, externalLabel, flagBadges, pageHead, ticketHref, ticketRef, typeBadge } from './common.js';

/** One escalation as a card. Used here and, without the ticket header, on the ticket page. */
export function escalationCard(ticket, nowMs, { header = true } = {}) {
  const esc = ticket.escalation;
  const evidence = dataLink(esc.evidence_url);
  return h(
    'article',
    { class: 'esc-card', 'aria-label': `Escalation: ${escalationLabel(esc.label)}` },
    h(
      'header',
      { class: 'esc-head' },
      header ? h('div', { class: 'esc-ticket' }, ticketRef(ticket, { titleClass: 'clamp-2' })) : null,
      h(
        'div',
        { class: 'esc-tags' },
        badge(escalationLabel(esc.label), 'bad'),
        h('code', { class: 'esc-code' }, esc.label),
        header ? [typeBadge(ticket.type), envBadgeFor(ticket), ...flagBadges(ticket.flags)] : null,
      ),
    ),
    h(
      'dl',
      { class: 'esc-meta' },
      h('div', null, h('dt', null, 'Escalated'), h('dd', null, esc.at ? timeEl(esc.at, nowMs) : '-')),
      h('div', null, h('dt', null, 'Agent attempts'), h('dd', null, formatInteger(esc.attempts))),
      h('div', null, h('dt', null, 'Evidence'), h('dd', null, evidence ? ghLink(evidence, externalLabel('Open evidence'), { class: 'ext' }) : h('span', { class: 'muted' }, 'none recorded'))),
    ),
    h(
      'div',
      { class: 'esc-cols' },
      h(
        'section',
        null,
        h('h3', null, 'Why it stopped'),
        esc.reasons.length > 0 ? h('ul', { class: 'bullets' }, ...esc.reasons.map((r) => h('li', null, h('span', { class: 'clamp-4 wrap' }, r)))) : h('p', { class: 'muted' }, 'No reason recorded.'),
      ),
      h(
        'section',
        null,
        h('h3', null, 'What the agent tried'),
        esc.tried.length > 0 ? h('ol', { class: 'bullets steps' }, ...esc.tried.map((r) => h('li', null, h('span', { class: 'clamp-3 wrap' }, r)))) : h('p', { class: 'muted' }, 'Nothing recorded before it stopped.'),
      ),
    ),
    header ? h('footer', { class: 'esc-foot' }, h('a', { class: 'btn btn-secondary btn-sm', href: ticketHref(ticket.issue) }, 'Open ticket')) : null,
  );
}

export function renderEscalations(ctx) {
  const { state, now } = ctx;
  const list = escalationList(state);
  return h(
    'div',
    { class: 'view' },
    pageHead({
      title: 'Escalations',
      lede: list.length ? `${formatInteger(list.length)} ${plural(list.length, 'ticket')} stopped for a human, newest first.` : 'Tickets the pipeline stopped on and handed to a human.',
    }),
    list.length === 0 ? emptyState('Nothing escalated', 'Every ticket is moving, or has finished. Escalations appear here the moment an agent gives up.') : h('div', { class: 'esc-list' }, ...list.map((t) => escalationCard(t, now))),
  );
}
