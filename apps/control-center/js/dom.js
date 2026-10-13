// Element builders. Data only ever becomes a text node or a validated attribute, never markup:
// there is no innerHTML anywhere, and this file is the only place elements get attributes.

import { formatDuration, formatRelative, formatShortTime, formatTimestamp, parseTime } from './format.js';
import { isSafeHref, limitText, safeGithubUrl } from './safe.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const CSS_LENGTH = /^-?\d+(\.\d+)?(%|px|rem|em|deg)?$/;

/** Sanitize an arbitrary data string into a safe, bounded CSS class token. */
export function classToken(val) {
  return String(val ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 32);
}

function setAttribute(el, key, value) {
  if (value === undefined || value === null || value === false) return;
  if (key === 'style' || key === 'srcdoc' || /^on/i.test(key)) {
    throw new Error(`dom: attribute "${key}" is not allowed (use vars/on)`);
  }
  if (key === 'href' && !isSafeHref(String(value))) {
    throw new Error('dom: href must be a fragment, a site link or a link into this repository');
  }
  if (key === 'src' || key === 'action' || key === 'formaction' || key === 'xlink:href') {
    throw new Error(`dom: attribute "${key}" is not allowed`);
  }
  el.setAttribute(key, value === true ? '' : String(value));
}

function applyAttrs(el, attrs) {
  for (const [key, value] of Object.entries(attrs ?? {})) {
    if (key === 'on') {
      for (const [type, handler] of Object.entries(value ?? {})) el.addEventListener(type, handler);
    } else if (key === 'vars') {
      for (const [name, v] of Object.entries(value ?? {})) {
        const text = String(v);
        if (!CSS_LENGTH.test(text) || !/^[a-z][\w-]*$/.test(name)) throw new Error(`dom: bad CSS variable ${name}`);
        el.style.setProperty(`--${name}`, text);
      }
    } else {
      setAttribute(el, key, value);
    }
  }
}

function appendChildren(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  applyAttrs(el, attrs);
  appendChildren(el, children);
  return el;
}

export function s(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  applyAttrs(el, attrs);
  appendChildren(el, children);
  return el;
}

/**
 * Keep an SVG chart in step with its container width. `draw(width)` returns an SVG element and
 * must be a pure function of its argument, so a resize simply redraws.
 */
export function responsiveSvg(host, draw) {
  let drawn = 0;
  const render = () => {
    const width = Math.floor(host.clientWidth);
    if (width <= 0 || width === drawn) return;
    drawn = width;
    host.replaceChildren(draw(width));
  };
  new ResizeObserver(render).observe(host);
  render();
  return host;
}

export function chartHost(draw, className = '') {
  return responsiveSvg(h('div', { class: `chart-host ${className}`.trim() }), draw);
}

// ----------------------------------------------------------------- small components

export const BADGE_TONES = Object.freeze(['good', 'bad', 'warn', 'info', 'neutral']);

export function badge(text, tone = 'neutral', className = '') {
  // Badges hold short labels; the text can come from the data, so it is capped.
  return h('span', { class: `badge tone-${tone} ${className}`.trim() }, limitText(text, 48));
}

/** An external link into this repository, or plain text when the URL is not acceptable. */
export function ghLink(url, children, attrs = {}) {
  const safe = safeGithubUrl(url);
  const content = Array.isArray(children) ? children : [children];
  if (safe === null) return h('span', { class: attrs.class ?? '' }, ...content);
  return h('a', { ...attrs, href: safe, target: '_blank', rel: 'noopener noreferrer' }, ...content);
}

/**
 * A <time> with the other form in its title. `mode` picks the visible text: 'rel' (default,
 * absolute UTC in the title) or 'abs' (short UTC time, relative in the title). Relative ones are
 * refreshed in place by tickRelativeTimes().
 */
export function timeEl(iso, nowMs, mode = 'rel') {
  const ms = parseTime(iso);
  if (ms === null) return h('span', { class: 'muted' }, '-');
  if (mode === 'abs') return h('time', { datetime: iso, title: formatRelative(iso, nowMs) }, formatShortTime(iso));
  return h('time', { datetime: iso, title: formatTimestamp(iso), 'data-rel': iso }, formatRelative(iso, nowMs));
}

/** Update every relative time and running duration under `root` in place (a timer calls this, so keep it cheap). */
export function tickRelativeTimes(root, nowMs) {
  for (const el of root.querySelectorAll('time[data-rel]')) {
    const text = formatRelative(el.getAttribute('data-rel'), nowMs);
    if (el.textContent !== text) el.textContent = text;
  }
  for (const el of root.querySelectorAll('time[data-since]')) {
    const since = parseTime(el.getAttribute('data-since'));
    if (since === null) continue;
    const text = formatDuration(Math.max(0, nowMs - since) / 1000);
    if (el.textContent !== text) el.textContent = text;
  }
}

export function emptyState(title, body, ...actions) {
  return h(
    'div',
    { class: 'empty-state' },
    h('p', { class: 'empty-title' }, title),
    body ? h('p', { class: 'empty-body' }, body) : null,
    actions.length ? h('div', { class: 'empty-actions' }, ...actions) : null,
  );
}

export function panel({ id, title, lede, actions, className = '' }, ...body) {
  const heading = title ? h('h2', { id: id ? `${id}-title` : undefined }, title) : null;
  return h(
    'section',
    { class: `panel ${className}`.trim(), id, 'aria-labelledby': id && title ? `${id}-title` : undefined },
    title || lede || actions
      ? h('div', { class: 'panel-head' }, h('div', { class: 'panel-titles' }, heading, lede ? h('p', { class: 'lede' }, lede) : null), actions ?? null)
      : null,
    ...body,
  );
}

/** Collapsed data table behind a chart (the chart's accessible twin). */
export function dataTable(summary, table) {
  return h('details', { class: 'disclosure' }, h('summary', null, summary), table);
}

export function table({ caption, head, rows, className = '', numeric = [] }) {
  const isNum = (i) => numeric.includes(i);
  return h(
    'div',
    { class: 'table-wrap', tabindex: '0', role: 'region', 'aria-label': caption },
    h(
      'table',
      { class: `data ${className}`.trim() },
      h('caption', { class: 'sr-only' }, caption),
      h('thead', null, h('tr', null, ...head.map((label, i) => h('th', { scope: 'col', class: isNum(i) ? 'num' : undefined }, label)))),
      h(
        'tbody',
        null,
        ...rows.map((cells) =>
          h('tr', null, ...cells.map((cell, i) => h(i === 0 ? 'th' : 'td', { scope: i === 0 ? 'row' : undefined, class: isNum(i) ? 'num' : undefined }, cell))),
        ),
      ),
    ),
  );
}
