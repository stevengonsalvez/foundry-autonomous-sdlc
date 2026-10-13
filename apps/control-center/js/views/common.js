// Pieces shared by several views. Untrusted text goes in as children (text nodes) only; links
// come from the validators in safe.js or from the ticket number.

import { badge, classToken, ghLink, h } from '../dom.js';
import { icon } from '../icons.js';
import { escalationLabel, formatDuration, formatTimestamp, formatUsd, parseTime, shortSha, titleCase } from '../format.js';
import { commitUrl, dataLink, issueUrl, pullUrl, releaseUrl, safeGithubUrl } from '../safe.js';
import { costBand, stageLabel } from '../model.js';

export const ticketHref = (issue) => `#/ticket/${issue}`;

export const MODE_TONES = Object.freeze(['auto', 'gate', 'sim', 'manual']);

/** CSS class for a board stage: `st-fill-*` (SVG fill), `st-bg-*` (background), `st-text-*` (text). */
export const stageFill = (stage) => `st-fill-${classToken(stage)}`;

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

// ------------------------------------------------------------------ mission-control helpers

export function modeBadge(mode) {
  const m = String(mode).toUpperCase();
  const tone = m === 'AUTO' ? 'auto' : m === 'GATE' ? 'gate' : m === 'SIM' ? 'sim' : 'manual';
  return h('span', { class: `mode-badge mode-${tone}` }, m);
}

const AGENT_CODES = {
  'sdlc-orchestrator': 'OR',
  'sdlc-coder': 'CO',
  'sdlc-req-gate': 'RG',
  'sdlc-product-owner': 'PO',
  'sdlc-feasibility': 'FE',
  'sdlc-test-designer': 'TD',
  'sdlc-reviewer': 'RV',
  'sdlc-triage': 'TR',
  'sdlc-ci-triage': 'CT',
  'sdlc-release-notes': 'RN',
  'sdlc-ledger': 'LD',
};

export function agentTag(agentName) {
  if (!agentName) return '--';
  return AGENT_CODES[agentName] ?? agentName.slice(0, 2).toUpperCase();
}

export function agentPill(agentName) {
  const tag = agentTag(agentName);
  return h('span', { class: 'agent-tag', title: agentName || 'unassigned' }, tag);
}

export function segmentedControl(items, current, onChange, ariaLabel = '') {
  const attrs = { class: 'segmented-control', role: 'group' };
  if (ariaLabel) attrs['aria-label'] = ariaLabel;
  const group = h('div', attrs);
  for (const item of items) {
    const val = typeof item === 'string' ? item : item.value;
    const label = typeof item === 'string' ? item : item.label;
    const active = val === current;
    const btn = h(
      'button',
      {
        type: 'button',
        class: `segmented-btn${active ? ' is-active' : ''}`,
        'aria-pressed': String(active),
        'data-value': val,
      },
      label,
    );
    btn.addEventListener('click', () => {
      if (val !== current) onChange(val);
    });
    group.append(btn);
  }
  return group;
}

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
  const token = classToken(stage);
  return h('span', { class: `badge badge-stage st-text-${token}` }, h('span', { class: `sdot st-bg-${token}`, 'aria-hidden': 'true' }), stageLabel(stage));
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
export const HOP_ACTIONS = Object.freeze(['stage', 'promote', 'rollback', 'skip', 'fail', 'legacy-publish']);

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

