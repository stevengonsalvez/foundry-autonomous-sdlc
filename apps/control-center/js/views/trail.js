// #/trail  Questions back, reviewer verdicts and CI triage across tickets. The same blocks are used
// inline on the ticket page. All text here came from agents or issue authors: it is shown as text.

import { badge, emptyState, h, timeEl } from '../dom.js';
import { trailGroups, trailIssues } from '../model.js';
import { ui } from '../ui.js';
import { envBadgeFor, pageHead, shaLink, stageBadge, ticketRef, typeBadge } from './common.js';

const SEVERITY_TONE = { critical: 'bad', high: 'bad', medium: 'warn', low: 'info', info: 'neutral' };

export function verdictBadge(verdict) {
  if (verdict === 'approve') return badge('Approved', 'good');
  if (verdict === 'request-changes' || verdict === 'request_changes') return badge('Changes requested', 'warn');
  return badge(verdict || 'No verdict', 'neutral');
}

/** Refinement questions and the answers a simulated product owner gave. */
export function qaBlock(qa) {
  const rounds = [...new Set(qa.map((q) => q.round))].sort((a, b) => a - b);
  return h(
    'div',
    { class: 'trail-block' },
    h('div', { class: 'trail-head' }, h('h3', null, 'Questions back'), badge('Answers by a simulated product owner', 'info')),
    ...rounds.map((round) => {
      const items = qa.filter((q) => q.round === round);
      const score = items.find((q) => q.score !== null)?.score;
      return h(
        'section',
        { class: 'qa-round', 'aria-label': `Refinement round ${round}` },
        h('p', { class: 'qa-round-head' }, `Round ${round}`, score !== undefined ? h('span', { class: 'muted' }, ` · requirement scored ${score}/100 when asked`) : null),
        h(
          'ol',
          { class: 'qa-list' },
          ...items.map((q) =>
            h(
              'li',
              { class: 'qa' },
              h('div', { class: 'bubble bubble-q' }, h('span', { class: 'who' }, 'Refinement agent asked'), h('p', { class: 'clamp-6 wrap' }, q.question || '(empty question)')),
              h(
                'div',
                { class: 'bubble bubble-a' },
                h('span', { class: 'who' }, 'Simulated product owner'),
                q.answer ? h('p', { class: 'clamp-8 wrap' }, q.answer) : h('p', { class: 'muted' }, 'No answer recorded.'),
              ),
            ),
          ),
        ),
      );
    }),
  );
}

export function reviewBlock(review) {
  return h(
    'div',
    { class: 'trail-block' },
    h(
      'div',
      { class: 'trail-head' },
      h('h3', null, 'Reviewer verdict'),
      verdictBadge(review.verdict),
      h('span', { class: 'muted' }, `Round ${review.round}`),
      review.head ? h('span', { class: 'muted' }, 'on ', shaLink(review.head)) : null,
    ),
    review.findings.length === 0
      ? h('p', { class: 'muted' }, 'No findings recorded.')
      : h(
          'ul',
          { class: 'findings' },
          ...review.findings.map((f) =>
            h(
              'li',
              { class: 'finding' },
              h('span', { class: 'finding-tags' }, badge(f.severity, SEVERITY_TONE[f.severity] ?? 'neutral'), f.area ? badge(f.area, 'neutral') : null),
              h('p', { class: 'clamp-5 wrap' }, f.detail),
            ),
          ),
        ),
  );
}

export function ciBlock(ci) {
  return h(
    'div',
    { class: 'trail-block' },
    h('div', { class: 'trail-head' }, h('h3', null, 'CI triage decision'), ci.cause ? badge(ci.cause, 'warn') : null, ci.revise_rounds ? h('span', { class: 'muted' }, `${ci.revise_rounds} repair ${ci.revise_rounds === 1 ? 'round' : 'rounds'}`) : null),
    ci.explanation ? h('p', { class: 'clamp-8 wrap' }, ci.explanation) : h('p', { class: 'muted' }, 'No explanation recorded.'),
    ci.test_files.length > 0
      ? h('div', null, h('p', { class: 'label' }, 'Test files to update'), h('ul', { class: 'file-list' }, ...ci.test_files.map((f) => h('li', null, h('code', { class: 'wrap' }, f)))))
      : null,
  );
}

const KINDS = [
  ['all', 'All'],
  ['qa', 'Questions'],
  ['review', 'Reviews'],
  ['ci', 'CI triage'],
];

function itemBlock(item) {
  if (item.kind === 'qa') return qaBlock(item.data);
  if (item.kind === 'review') return reviewBlock(item.data);
  return ciBlock(item.data);
}

export function renderTrail(ctx) {
  const { state, now } = ctx;
  const filters = ui.trail;
  const feed = h('div', { class: 'trail-feed' });
  const status = h('p', { class: 'sr-only', role: 'status', 'aria-live': 'polite' });
  const known = trailIssues(state);
  if (filters.issue !== null && !known.some((t) => t.issue === filters.issue)) filters.issue = null;

  const update = () => {
    const groups = trailGroups(state, filters);
    status.textContent = `${groups.length} ${groups.length === 1 ? 'ticket' : 'tickets'} shown`;
    if (groups.length === 0) {
      feed.replaceChildren(emptyState('Nothing to show', 'No questions, reviews or CI triage match these filters.'));
      return;
    }
    feed.replaceChildren(
      ...groups.map((g) =>
        h(
          'section',
          { class: 'panel trail-group', 'aria-label': `Trail for ticket ${g.ticket.issue}` },
          h('div', { class: 'trail-group-head' }, ticketRef(g.ticket), typeBadge(g.ticket.type), stageBadge(g.ticket.stage), envBadgeFor(g.ticket)),
          ...g.items.map((item) =>
            h(
              'div',
              { class: 'trail-item' },
              h('p', { class: 'trail-when' }, item.at ? [timeEl(item.at, now), h('span', { class: 'muted' }, ` (${item.atNote})`)] : h('span', { class: 'muted' }, 'time not recorded')),
              itemBlock(item),
            ),
          ),
        ),
      ),
    );
  };

  const kindChips = KINDS.map(([value, label]) => {
    const chip = h('button', { type: 'button', class: 'chip', 'aria-pressed': String(filters.kind === value) }, label);
    chip.addEventListener('click', () => {
      filters.kind = value;
      for (const c of kindChips) c.setAttribute('aria-pressed', String(c === chip));
      update();
    });
    return chip;
  });

  const select = h(
    'select',
    { id: 'trail-ticket', class: 'input' },
    h('option', { value: '' }, 'All tickets'),
    ...known.map((t) => h('option', { value: String(t.issue), selected: filters.issue === t.issue }, `#${t.issue} ${t.title}`.slice(0, 80))),
  );
  select.addEventListener('change', () => {
    filters.issue = select.value === '' ? null : Number(select.value);
    update();
  });

  update();
  return h(
    'div',
    { class: 'view' },
    pageHead({ title: 'Questions and reviews', lede: 'What the agents asked, what came back, and what the reviewer and CI triage decided, grouped per ticket. Times are when the stage the item belongs to began.' }),
    h(
      'div',
      { class: 'toolbar' },
      h('div', { class: 'chip-group', role: 'group', 'aria-label': 'Filter by kind' }, ...kindChips),
      h('div', { class: 'select-field' }, h('label', { for: 'trail-ticket' }, 'Ticket'), select),
    ),
    status,
    feed,
  );
}

