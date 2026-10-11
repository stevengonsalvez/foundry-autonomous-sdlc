// Everything that decides whether a string from the data may become a link, a path or visible text.
// The data is attacker-influenced (issue titles, model output), so this is the single place where
// the rules live. Pure and DOM-free so it can be unit tested.

export const OWNER = 'stevengonsalvez';
export const REPO = `${OWNER}/foundry-autonomous-sdlc`;
export const REPO_URL = `https://github.com/${REPO}`;
const PREFIX = `${REPO_URL}/`;

export const RAW_STATE_URL = `https://raw.githubusercontent.com/${REPO}/state/state.json`;
export const API_STATE_URL = `https://api.github.com/repos/${REPO}/contents/state.json?ref=state`;
export const API_ISSUES_URL = `https://api.github.com/repos/${REPO}/issues?state=open&sort=created&direction=desc&per_page=30`;

export const NEW_TICKET_URL = `${PREFIX}issues/new?template=feature_request.yml`;
export const NEW_BUG_URL = `${PREFIX}issues/new?template=bug_report.yml`;

/** Same-site relative links the page itself owns (never built from data). */
export const SITE_LINKS = Object.freeze(['../', '../staging/']);

const UNSAFE_CHARS = /[\u0000- \u007f\\]/;
const MAX_URL = 2048;

/** A positive integer, or null. Accepts numeric strings so "24" from a JSON map key works. */
export function positiveInt(value) {
  const n = typeof value === 'string' && /^\d{1,9}$/.test(value) ? Number(value) : value;
  return Number.isInteger(n) && n > 0 ? n : null;
}

/** A github.com URL inside this repository, normalised, or null. */
export function safeGithubUrl(value) {
  if (typeof value !== 'string' || value.length === 0 || value.length > MAX_URL || UNSAFE_CHARS.test(value)) return null;
  let url;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  if (url.protocol !== 'https:' || url.host !== 'github.com' || url.username || url.password) return null;
  return url.pathname.startsWith(`/${REPO}/`) ? url.href : null;
}

export function isSafeHref(href) {
  if (typeof href !== 'string') return false;
  if (href.startsWith('#') && !UNSAFE_CHARS.test(href)) return true;
  if (SITE_LINKS.includes(href)) return true;
  return safeGithubUrl(href) !== null;
}

export function issueUrl(number) {
  const n = positiveInt(number);
  return n === null ? null : `${PREFIX}issues/${n}`;
}

export function pullUrl(number) {
  const n = positiveInt(number);
  return n === null ? null : `${PREFIX}pull/${n}`;
}

/** Short or full hex sha, lower-cased, or null. */
export function cleanSha(value) {
  return typeof value === 'string' && /^[0-9a-f]{7,40}$/i.test(value) ? value.toLowerCase() : null;
}

export function commitUrl(sha) {
  const clean = cleanSha(sha);
  return clean === null ? null : `${PREFIX}commit/${clean}`;
}

export function releaseUrl(tag) {
  const valid = typeof tag === 'string' && tag.length <= 100 && /^[\w.+-]+(\/[\w.+-]+)*$/.test(tag);
  return valid && !tag.split('/').some((part) => /^\.+$/.test(part)) ? `${PREFIX}releases/tag/${tag}` : null;
}

/** Link from the data (a run, an evidence comment) kept only when it points into this repository. */
export const dataLink = safeGithubUrl;

/**
 * Resolve the `?data=` / `&issues=` override. Only a same-origin relative path to a .json file is
 * accepted: no scheme, no leading slash (that would allow `//host/x.json`), no `..`.
 */
export function resolveDataParam(value, base) {
  if (typeof value !== 'string' || value.length > 200) return null;
  if (!/^[\w./-]+\.json$/.test(value) || value.includes('..') || value.startsWith('/') || value.includes('//')) return null;
  try {
    const baseUrl = new URL(base);
    const url = new URL(value, baseUrl);
    return url.origin === baseUrl.origin ? url.href : null;
  } catch {
    return null;
  }
}

/** Hard length cap for places CSS cannot clamp (document title, SVG tooltips, aria labels). */
export function limitText(value, max = 160) {
  const text = typeof value === 'string' ? value : value == null ? '' : String(value);
  const flat = text.replace(/[\u0000-\u001f\u007f]+/g, ' ').trim();
  return flat.length <= max ? flat : `${flat.slice(0, Math.max(0, max - 1)).trimEnd()}…`;
}
