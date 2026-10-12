// #/trail: Questions back, reviewer verdicts and CI triage across tickets.
// The same blocks are used inline on the ticket page.
// All text here came from agents or issue authors: it is shown strictly as text.

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

/** Format text that may contain code blocks or inline backticks safely into DOM nodes. */
export function formatMessageBody(text, paragraphClass = 'wrap') {
  if (!text) return [h('p', { class: paragraphClass }, '')];
  const codeBlockRegex = /```(?:[a-z0-9_-]+)?\n?([\s\S]*?)```/g;
  const blocks = [];
  let lastIndex = 0;
  let match;

  while ((match = codeBlockRegex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      blocks.push(...formatParagraphs(text.slice(lastIndex, match.index), paragraphClass));
    }
    const codeText = match[1].replace(/\n$/, '');
    blocks.push(h('pre', { class: 'trail-code-block' }, h('code', null, codeText)));
    lastIndex = codeBlockRegex.lastIndex;
  }

  if (lastIndex < text.length) {
    blocks.push(...formatParagraphs(text.slice(lastIndex), paragraphClass));
  }

  return blocks.length > 0 ? blocks : [h('p', { class: paragraphClass }, text)];
}

function formatParagraphs(text, paragraphClass) {
  const rawParagraphs = text.split(/\n{2,}/);
  const results = [];
  for (const raw of rawParagraphs) {
    const trimmed = raw.trim();
    if (!trimmed) continue;
    const parts = trimmed.split(/`([^`]+)`/g);
    const children = parts.map((part, index) => {
      if (index % 2 === 1) {
        return h('code', { class: 'trail-code-inline' }, part);
      }
      return part;
    });
    results.push(h('p', { class: paragraphClass }, ...children));
  }
  return results;
}

/** Refinement questions and the answers a simulated product owner gave. */
export function qaBlock(qa, meta = {}) {
  const rounds = [...new Set(qa.map((q) => q.round))].sort((a, b) => a - b);
  return h(
    'div',
    { class: 'trail-block trail-qa' },
    h(
      'div',
      { class: 'trail-head' },
      h(
        'div',
        { class: 'trail-speaker-group' },
        h('h3', { class: 'trail-head-title' }, 'Questions back'),
        badge('Answers by a simulated product owner', 'info', 'speaker-badge'),
      ),
      meta.at && meta.now ? timeEl(meta.at, meta.now) : null,
    ),
    ...rounds.map((round) => {
      const items = qa.filter((q) => q.round === round);
      const score = items.find((q) => q.score !== null)?.score;
      return h(
        'section',
        { class: 'qa-round', 'aria-label': `Refinement round ${round}` },
        h(
          'p',
          { class: 'qa-round-head' },
          `Round ${round}`,
          score !== undefined ? h('span', { class: 'muted' }, ` · requirement scored ${score}/100 when asked`) : null,
        ),
        h(
          'ol',
          { class: 'qa-list' },
          ...items.map((q) =>
            h(
              'li',
              { class: 'qa' },
              h(
                'div',
                { class: 'bubble bubble-q' },
                h(
                  'div',
                  { class: 'bubble-speaker' },
                  h('span', { class: 'who speaker-badge' }, 'Refinement agent asked'),
                ),
                h('div', { class: 'bubble-body' }, ...formatMessageBody(q.question || '(empty question)', 'clamp-6 wrap')),
              ),
              h(
                'div',
                { class: 'bubble bubble-a' },
                h(
                  'div',
                  { class: 'bubble-speaker' },
                  h('span', { class: 'who speaker-badge' }, 'Simulated product owner'),
                  h('span', { class: 'speaker-sub' }, 'Product owner answered'),
                ),
                h(
                  'div',
                  { class: 'bubble-body' },
                  q.answer
                    ? formatMessageBody(q.answer, 'clamp-8 wrap')
                    : [h('p', { class: 'muted' }, 'No answer recorded.')],
                ),
              ),
            ),
          ),
        ),
      );
    }),
  );
}

export function reviewBlock(review, meta = {}) {
  return h(
    'div',
    { class: 'trail-block trail-review' },
    h(
      'div',
      { class: 'trail-head' },
      h(
        'div',
        { class: 'trail-speaker-group' },
        h('h3', { class: 'trail-head-title' }, 'Reviewer verdict'),
        verdictBadge(review.verdict),
        h('span', { class: 'muted trail-meta-pill' }, `Round ${review.round}`),
        review.head ? h('span', { class: 'muted trail-meta-pill' }, 'on ', shaLink(review.head)) : null,
      ),
      meta.at && meta.now ? timeEl(meta.at, meta.now) : null,
    ),
    review.findings.length === 0
      ? h('p', { class: 'muted' }, 'No findings recorded.')
      : h(
          'ul',
          { class: 'findings trail-findings' },
          ...review.findings.map((f) =>
            h(
              'li',
              { class: 'finding trail-finding-item' },
              h(
                'span',
                { class: 'finding-tags' },
                badge(f.severity, SEVERITY_TONE[f.severity] ?? 'neutral'),
                f.area ? badge(f.area, 'neutral') : null,
              ),
              h('div', { class: 'finding-body' }, ...formatMessageBody(f.detail, 'clamp-5 wrap')),
            ),
          ),
        ),
  );
}

export function ciBlock(ci, meta = {}) {
  return h(
    'div',
    { class: 'trail-block trail-ci' },
    h(
      'div',
      { class: 'trail-head' },
      h(
        'div',
        { class: 'trail-speaker-group' },
        h('h3', { class: 'trail-head-title' }, 'CI triage decision'),
        ci.cause ? badge(ci.cause, 'warn') : null,
        ci.revise_rounds
          ? h('span', { class: 'muted trail-meta-pill' }, `${ci.revise_rounds} repair ${ci.revise_rounds === 1 ? 'round' : 'rounds'}`)
          : null,
      ),
      meta.at && meta.now ? timeEl(meta.at, meta.now) : null,
    ),
    ci.explanation
      ? h('div', { class: 'trail-explanation' }, ...formatMessageBody(ci.explanation, 'clamp-8 wrap'))
      : h('p', { class: 'muted' }, 'No explanation recorded.'),
    ci.test_files && ci.test_files.length > 0
      ? h(
          'div',
          { class: 'trail-test-files' },
          h('p', { class: 'label trail-files-label' }, 'Test files to update'),
          h(
            'ul',
            { class: 'file-list trail-file-list' },
            ...ci.test_files.map((f) =>
              h('li', { class: 'trail-file-item' }, h('code', { class: 'trail-code-file wrap' }, f)),
            ),
          ),
        )
      : null,
  );
}

const KINDS = [
  ['all', 'All'],
  ['qa', 'Questions'],
  ['review', 'Reviews'],
  ['ci', 'CI triage'],
];

function itemBlock(item, meta = {}) {
  if (item.kind === 'qa') return qaBlock(item.data, meta);
  if (item.kind === 'review') return reviewBlock(item.data, meta);
  return ciBlock(item.data, meta);
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
          h(
            'div',
            { class: 'trail-group-head' },
            h('div', { class: 'trail-group-title' }, ticketRef(g.ticket)),
            h(
              'div',
              { class: 'trail-group-badges' },
              typeBadge(g.ticket.type),
              stageBadge(g.ticket.stage),
              envBadgeFor(g.ticket),
            ),
          ),
          ...g.items.map((item) =>
            h(
              'article',
              { class: 'trail-item' },
              h(
                'div',
                { class: 'trail-when' },
                item.at
                  ? [timeEl(item.at, now), h('span', { class: 'muted trail-at-note' }, ` (${item.atNote})`)]
                  : h('span', { class: 'muted' }, 'time not recorded'),
              ),
              itemBlock(item, { at: item.at, now, atNote: item.atNote }),
            ),
          ),
        ),
      ),
    );
  };

  const kindChips = KINDS.map(([value, label]) => {
    const chip = h('button', { type: 'button', class: 'chip trail-chip', 'aria-pressed': String(filters.kind === value) }, label);
    chip.addEventListener('click', () => {
      filters.kind = value;
      for (const c of kindChips) c.setAttribute('aria-pressed', String(c === chip));
      update();
    });
    return chip;
  });

  const select = h(
    'select',
    { id: 'trail-ticket', class: 'input trail-select' },
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
    { class: 'view view-trail' },
    pageHead({
      title: 'Questions and reviews',
      lede: 'What the agents asked, what came back, and what the reviewer and CI triage decided, grouped per ticket. Times are when the stage the item belongs to began.',
    }),
    h(
      'div',
      { class: 'toolbar trail-toolbar' },
      h('div', { class: 'chip-group trail-chip-group', role: 'group', 'aria-label': 'Filter by kind' }, ...kindChips),
      h('div', { class: 'select-field trail-select-field' }, h('label', { for: 'trail-ticket' }, 'Ticket'), select),
    ),
    status,
    feed,
  );
}
