// Pieces shared by several views. Untrusted text goes in as children (text nodes) only; links
// come from the validators in safe.js or from the ticket number.

import { badge, dataTable, ghLink, h, table } from '../dom.js';
import { icon } from '../icons.js';
import { escalationLabel, formatDuration, formatTimestamp, formatUsd, parseTime, shortSha, titleCase } from '../format.js';
import { commitUrl, dataLink, issueUrl, pullUrl, releaseUrl, safeGithubUrl } from '../safe.js';
import { costBand, stageLabel } from '../model.js';

export { dataTable, table };

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

// ------------------------------------------------------------------ KPI / Stat Cards

/**
 * Stat / KPI card: crisp 1px border, 3px left edge accent line (.edge),
 * large monospace metric, tiny uppercase label, optional delta/context.
 */
export function kpiCard(labelOrOptions, maybeValue, maybeOptions) {
  const opts =
    typeof labelOrOptions === 'object' && labelOrOptions !== null && !Array.isArray(labelOrOptions) && !(labelOrOptions instanceof Node) && maybeValue === undefined
      ? labelOrOptions
      : {
          label: labelOrOptions,
          value: maybeValue,
          ...(typeof maybeOptions === 'string' ? { tone: maybeOptions } : (maybeOptions ?? {})),
        };

  const { label, value, tone = '', delta = null, context = null, className = '' } = opts;
  const toneClass = tone ? (tone.startsWith('tone-') || tone.startsWith('kpi-') ? tone : `tone-${tone}`) : '';
  const kpiToneClass = tone && !tone.startsWith('kpi-') ? `kpi-${tone.replace(/^tone-/, '')}` : '';

  const children = [
    h('span', { class: 'edge', 'aria-hidden': 'true' }),
    h('div', { class: 'kpi-label l' }, label),
    h('div', { class: 'kpi-value v metric' }, value),
  ];

  if ((delta !== null && delta !== undefined) || (context !== null && context !== undefined)) {
    const metaChildren = [];
    if (delta !== null && delta !== undefined) metaChildren.push(h('span', { class: 'delta' }, delta));
    if (context !== null && context !== undefined) metaChildren.push(h('span', { class: 'context' }, context));
    children.push(h('div', { class: 'kpi-meta delta-context' }, ...metaChildren));
  }

  return h('div', { class: `kpi-card kpi ${toneClass} ${kpiToneClass} ${className}`.trim() }, ...children);
}

// ------------------------------------------------------------------ Badges & Chips

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

/**
 * Pill-shaped badge with optional 6px dot and semantic tones:
 * tone-good, tone-warn, tone-bad, tone-brand, tone-muted, tone-info, tone-neutral.
 */
export function statusBadge(text, tone = 'neutral', { dot = false, className = '' } = {}) {
  const normalizedTone = tone.startsWith('tone-') ? tone.replace(/^tone-/, '') : tone;
  const dotEl = dot ? h('span', { class: 'badge-dot sdot', 'aria-hidden': 'true' }) : null;
  return h('span', { class: `badge tone-${normalizedTone} ${className}`.trim() }, dotEl, text);
}

/**
 * Interactive or static pill-shaped chip for filters with optional 6px dot.
 */
export function chip(label, { pressed = false, tone = '', dot = false, onClick = null, className = '' } = {}) {
  const toneClass = tone ? (tone.startsWith('tone-') ? tone : `tone-${tone}`) : '';
  const dotEl = dot ? h('span', { class: 'chip-dot sdot', 'aria-hidden': 'true' }) : null;
  const el = h(
    onClick ? 'button' : 'span',
    {
      type: onClick ? 'button' : undefined,
      class: `chip ${toneClass} ${className}`.trim(),
      'aria-pressed': onClick ? String(pressed) : undefined,
    },
    dotEl,
    label,
  );
  if (onClick) {
    el.addEventListener('click', onClick);
  }
  return el;
}

// ------------------------------------------------------------------ Callout Boxes

/**
 * Cockpit callout box with crisp 1px border, alert/status icon, and clear contrast.
 * Tones: danger, warn, good, info, brand, muted.
 */
export function calloutBox({ title = null, message, tone = 'info', iconName = null, actions = null, className = '', role = null } = {}) {
  const normalizedTone = tone.replace(/^callout-/, '');
  const defaultIcon = normalizedTone === 'danger' || normalizedTone === 'warn' ? 'alert' : normalizedTone === 'good' ? 'check' : 'clock';
  const iconToUse = iconName ?? defaultIcon;
  const effectiveRole = role ?? (normalizedTone === 'danger' ? 'alert' : 'status');

  const bodyChildren = [];
  if (title) bodyChildren.push(h('h3', { class: 'callout-title' }, title));
  if (message) {
    if (typeof message === 'string') {
      bodyChildren.push(h('p', { class: 'callout-lead' }, message));
    } else if (Array.isArray(message)) {
      bodyChildren.push(...message);
    } else {
      bodyChildren.push(message);
    }
  }
  if (actions) {
    bodyChildren.push(h('div', { class: 'callout-actions' }, ...(Array.isArray(actions) ? actions : [actions])));
  }

  return h(
    'div',
    { class: `callout callout-${normalizedTone} ${className}`.trim(), role: effectiveRole },
    h('span', { class: 'callout-icon', 'aria-hidden': 'true' }, icon(iconToUse, { size: 18 })),
    h('div', { class: 'callout-body' }, ...bodyChildren),
  );
}

// ------------------------------------------------------------------ Cost Bar

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

// ------------------------------------------------------------------ Headings and Links

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

// ------------------------------------------------------------------ Deploy Events

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
