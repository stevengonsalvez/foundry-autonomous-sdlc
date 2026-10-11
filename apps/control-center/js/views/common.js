// Pieces shared by several views. Untrusted text goes in as children (text nodes) only; links
// come from the validators in safe.js or from the ticket number.

import { badge, ghLink, h } from '../dom.js';
import { icon } from '../icons.js';
import { escalationLabel, formatDuration, formatTimestamp, formatUsd, parseTime, shortSha, titleCase } from '../format.js';
import { commitUrl, dataLink, issueUrl, pullUrl, releaseUrl, safeGithubUrl } from '../safe.js';
import { costBand, stageLabel } from '../model.js';

export const ticketHref = (issue) => `#/ticket/${issue}`;

/** CSS class for a board stage: `st-fill-*` (SVG fill), `st-bg-*` (background), `st-text-*` (text). */
export const stageFill = (stage) => `st-fill-${stage}`;

/** GitHub URL of a ticket: the one in the data when it points into this repo, else built from its number. */
export function ticketGithubUrl(ticket) {
  return safeGithubUrl(ticket.url) ?? (ticket.kind === 'pr' ? pullUrl(ticket.issue) : issueUrl(ticket.issue));
}

export function prUrl(pr) {
  return safeGithubUrl(pr?.url) ?? pullUrl(pr?.number);
}

export function releaseLink(release) {
  return safeGithubUrl(release?.url) ?? releaseUrl(release?.tag);
}

export const runLink = (url) => dataLink(url);

// ------------------------------------------------------------------ badges

const TYPE_TONE = { feature: 'info', bug: 'bad', maintenance: 'neutral', unclassified: 'neutral' };

export function typeBadge(type) {
  return badge(type === 'unclassified' ? 'New' : type, TYPE_TONE[type] ?? 'neutral', 'badge-type');
}

const ENV_BADGE = { staging: ['Staging', 'info'], prod: ['In production', 'good'], 'rolled-back': ['Rolled back', 'bad'] };

export function envBadge(env) {
  const entry = ENV_BADGE[env];
  return entry ? badge(entry[0], entry[1]) : null;
}

/** The environment badge, unless a flag already says the same thing. */
export function envBadgeFor(ticket) {
  if (ticket.stage === ticket.env) return null;
  if (ticket.env === 'rolled-back' && ticket.flags.includes('rolled-back')) return null;
  return envBadge(ticket.env);
}

export function stageBadge(stage) {
  return h('span', { class: `badge badge-stage st-text-${stage}` }, h('span', { class: `sdot st-bg-${stage}`, 'aria-hidden': 'true' }), stageLabel(stage));
}

const FLAGS = {
  'rolled-back': ['Rolled back', 'bad'],
  'deploy-failed': ['Deploy failed', 'bad'],
  'over-cap': ['Over cap', 'bad'],
  'waiting-for-ledger': ['Waiting for ledger', 'warn'],
  'unknown-stage': ['Unknown stage', 'warn'],
};

export function flagBadges(flags) {
  return flags.map((flag) => {
    const known = FLAGS[flag];
    return known ? badge(known[0], known[1]) : badge(flag, 'neutral');
  });
}

export function escalationBadge(ticket) {
  return ticket.escalation ? badge(escalationLabel(ticket.escalation.label), 'bad') : null;
}

// ------------------------------------------------------------------ cost bar

/** A thin bar for spend against the per-issue cap; text says the same thing as the colour. */
export function costBar(usd, pct, { label = true } = {}) {
  const clamped = Math.max(0, Math.min(100, Number.isFinite(pct) ? pct : 0));
  const band = costBand(pct);
  return h(
    'span',
    { class: `cbar-wrap band-${band}`, title: `${formatUsd(usd)} of the per-issue cap (${Math.round(pct)}%)` },
    h('span', { class: 'cbar', 'aria-hidden': 'true' }, h('span', { class: 'cbar-fill', vars: { pct: `${clamped}%` } })),
    label ? h('span', { class: 'cbar-text' }, formatUsd(usd)) : null,
  );
}

// ------------------------------------------------------------------ headings and links

export function pageHead({ title, lede, actions, eyebrow }) {
  return h(
    'div',
    { class: 'page-head' },
    h('div', { class: 'page-titles' }, eyebrow ? h('p', { class: 'eyebrow' }, eyebrow) : null, h('h1', null, title), lede ? h('p', { class: 'lede' }, lede) : null),
    actions ? h('div', { class: 'page-actions' }, actions) : null,
  );
}

export function ticketRef(ticket, { titleClass = 'clamp-1' } = {}) {
  return h(
    'a',
    { class: 'ticket-ref', href: ticketHref(ticket.issue) },
    h('span', { class: 'num' }, `#${ticket.issue}`),
    h('span', { class: titleClass }, ticket.title || 'Untitled'),
  );
}

export function issueNumberLink(issue) {
  return issue === null ? h('span', { class: 'muted' }, '-') : h('a', { class: 'num-link', href: ticketHref(issue) }, `#${issue}`);
}

export function externalLabel(text) {
  return [text, icon('external', { size: 12, className: 'icon-ext' })];
}

export function shaLink(sha) {
  const short = shortSha(sha);
  const url = commitUrl(sha);
  return url ? ghLink(url, h('code', null, short), { class: 'sha' }) : h('code', null, short);
}

export function runAnchor(url, text = 'Run') {
  const safe = runLink(url);
  return safe ? ghLink(safe, externalLabel(text), { class: 'ext' }) : null;
}

export function seconds(iso, nowMs) {
  const ms = parseTime(iso);
  return ms === null ? null : Math.max(0, (nowMs - ms) / 1000);
}

/** A running duration since `iso`, kept current by the page ticker. */
export function sinceEl(iso, nowMs) {
  const s = seconds(iso, nowMs);
  if (s === null) return h('span', { class: 'muted' }, '-');
  return h('time', { datetime: iso, title: `since ${formatTimestamp(iso)}`, 'data-since': iso }, formatDuration(s));
}

// ------------------------------------------------------------------ deploy events

const ENV_LABEL = { staging: 'staging', prod: 'production' };

export function hopTitle(hop) {
  const where = ENV_LABEL[hop.env] ?? hop.env;
  switch (hop.action) {
    case 'stage':
      return `Deployed to ${where}`;
    case 'promote':
      return `Promoted to ${where}`;
    case 'rollback':
      return `Rolled back on ${where}`;
    case 'skip':
      return `Skipped on ${where}`;
    case 'fail':
      return `Failed on ${where}`;
    case 'legacy-publish':
      return 'Published straight from main';
    default:
      return `${titleCase(hop.action || 'Event')} on ${where}`;
  }
}

