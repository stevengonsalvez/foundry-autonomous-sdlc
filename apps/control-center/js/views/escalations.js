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
  const resolved = esc.resolved;
  return h(
    'article',
    { class: resolved ? 'esc-card esc-card-resolved' : 'esc-card', 'aria-label': `Escalation: ${escalationLabel(esc.label)}` },
    h(
      'header',
      { class: 'esc-head' },
      header ? h('div', { class: 'esc-ticket' }, ticketRef(ticket, { titleClass: 'clamp-2' })) : null,
      h(
        'div',
        { class: 'esc-tags' },
        badge(escalationLabel(esc.label), resolved ? 'neutral' : 'bad'),
        resolved ? badge(`Resolved: ${resolved.how}`, 'good') : null,
        h('code', { class: 'esc-code' }, esc.label),
        header ? [typeBadge(ticket.type), envBadgeFor(ticket), ...flagBadges(ticket.flags)] : null,
      ),
    ),
    h(
      'dl',
      { class: 'esc-meta' },
      h('div', null, h('dt', null, 'Escalated'), h('dd', null, esc.at ? timeEl(esc.at, nowMs) : '-')),
      resolved
        ? h(
            'div',
            null,
            h('dt', null, 'Resolved'),
            h(
              'dd',
              null,
              badge(`Resolved: ${resolved.how}`, 'good'),
              ' ',
              h('span', { class: 'muted' }, `by ${resolved.by}`),
              resolved.at ? [' ', timeEl(resolved.at, nowMs)] : null,
            ),
          )
        : null,
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
  const open = list.filter((t) => !t.escalation?.resolved);
  const resolved = list.filter((t) => Boolean(t.escalation?.resolved));
  return h(
    'div',
    { class: 'view' },
    pageHead({
      title: 'Escalations',
      lede: open.length
        ? `${formatInteger(open.length)} ${plural(open.length, 'ticket')} stopped for a human, newest first.`
        : 'Tickets the pipeline stopped on and handed to a human.',
    }),
    open.length === 0 && resolved.length === 0
      ? emptyState('Nothing escalated', 'Every ticket is moving, or has finished. Escalations appear here the moment an agent gives up.')
      : [
          open.length === 0
            ? emptyState('No open escalations', 'All escalations have been resolved.')
            : h('div', { class: 'esc-list' }, ...open.map((t) => escalationCard(t, now))),
          resolved.length > 0
            ? h(
                'details',
                { class: 'disclosure esc-resolved-disclosure' },
                h('summary', null, `Resolved (${formatInteger(resolved.length)})`),
                h('div', { class: 'esc-list esc-resolved-list' }, ...resolved.map((t) => escalationCard(t, now))),
              )
            : null,
        ],
  );
}
