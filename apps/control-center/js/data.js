// Fetch strategy. Read-only: every request is a GET, nothing is ever sent but public headers.
//
//   raw      raw.githubusercontent.com/.../state/state.json   every 30 s, no budget, up to 5 min stale
//            (measured: cache-control max-age=300, query strings ignored in the cache key)
//   api      api.github.com/.../contents/state.json?ref=state  every 60 s, conditional (ETag)
//   issues   api.github.com/.../issues?state=open...           every 60 s, conditional (ETag)
//
// api and issues share one unauthenticated budget of 60 requests an hour per IP, and a 304 counts.
// So the budget is read from every response (x-ratelimit-remaining / -reset) and spent in priority
// order: below SCARCE remaining only the issues call (pending intake) keeps going, spread so it
// lasts until the window resets; below RESERVE the API is left alone until reset. raw keeps working
// either way. On 403/429 everything on the API backs off.
//
// The poller does no DOM work: it takes fetch, a clock and a visibility probe, so it is unit tested
// with fakes. Results are handed to callbacks; the store decides which document is newest.

import { normalizeTicket, parseState } from './schema.js';
import { API_ISSUES_URL, API_STATE_URL, OWNER, RAW_STATE_URL, positiveInt } from './safe.js';

export const RAW_INTERVAL_MS = 30_000;
export const API_INTERVAL_MS = 60_000;
// New issues are the thing a viewer waits for, so while the budget is healthy the issue list is asked twice as often.
export const ISSUES_INTERVAL_MS = 30_000;
export const RESERVE = 15;
export const SCARCE = 40;
export const FAILURE_BASE_MS = 30_000;
export const FAILURE_MAX_MS = 10 * 60_000;
export const MIN_FORCE_GAP_MS = 5_000;
const HOUR_MS = 3_600_000;

// ------------------------------------------------------------------ rate budget

/** What GitHub told us about the shared API budget, and when the API may be called again. */
export class RateBudget {
  #remaining = null;
  #resetMs = null;
  #blockedUntil = 0;
  #strikes = 0;

  observe(headers, nowMs) {
    const remaining = Number(headers.get('x-ratelimit-remaining'));
    const reset = Number(headers.get('x-ratelimit-reset'));
    if (headers.get('x-ratelimit-remaining') !== null && Number.isFinite(remaining)) this.#remaining = remaining;
    if (headers.get('x-ratelimit-reset') !== null && Number.isFinite(reset) && reset > 0) this.#resetMs = reset * 1000;
    if (this.#resetMs !== null && nowMs >= this.#resetMs) this.#expire();
  }

  /** A 403 or 429: wait until the window resets, the server's retry-after, or an exponential step. */
  blocked(headers, nowMs) {
    this.observe(headers, nowMs);
    const retryAfter = Number(headers.get('retry-after'));
    let until;
    if (this.#remaining === 0 && this.#resetMs !== null && this.#resetMs > nowMs) until = this.#resetMs + 1000;
    else if (Number.isFinite(retryAfter) && retryAfter > 0) until = nowMs + retryAfter * 1000;
    else until = nowMs + Math.min(HOUR_MS, API_INTERVAL_MS * 2 ** this.#strikes);
    this.#strikes += 1;
    this.#blockedUntil = Math.max(this.#blockedUntil, until);
  }

  succeeded() {
    this.#strikes = 0;
  }

  #expire() {
    this.#remaining = null;
    this.#resetMs = null;
  }

  get remaining() {
    return this.#remaining;
  }

  /** Whether `endpoint` ('state' | 'issues') may use the API now. */
  canCall(endpoint, nowMs) {
    return this.retryAt(endpoint, nowMs) <= nowMs;
  }

  /** Earliest time the API may be used for `endpoint` (nowMs when it may be used right away). */
  retryAt(endpoint, nowMs) {
    if (this.#resetMs !== null && nowMs >= this.#resetMs) this.#expire();
    if (nowMs < this.#blockedUntil) return this.#blockedUntil;
    if (this.#remaining === null) return nowMs;
    if (this.#remaining < RESERVE || (endpoint === 'state' && this.#remaining < SCARCE)) return this.#resetMs ?? nowMs + HOUR_MS;
    return nowMs;
  }

  /** Spacing between calls: the base cadence, stretched once the budget is scarce so it lasts to reset. */
  intervalMs(nowMs) {
    if (this.#remaining === null || this.#resetMs === null || this.#remaining >= SCARCE) return API_INTERVAL_MS;
    const spendable = Math.max(1, this.#remaining - RESERVE);
    return Math.max(API_INTERVAL_MS, (this.#resetMs - nowMs) / spendable);
  }
}

export function failureDelayMs(failures) {
  return Math.min(FAILURE_MAX_MS, FAILURE_BASE_MS * 2 ** Math.max(0, failures - 1));
}

// ------------------------------------------------------------------ pending intake

const TYPE_LABELS = [
  ['bug', 'bug'],
  ['maintenance', 'maintenance'],
  ['chore', 'maintenance'],
  ['feature', 'feature'],
  ['enhancement', 'feature'],
];

function typeFromLabels(labels) {
  const names = (Array.isArray(labels) ? labels : []).map((l) => String(typeof l === 'string' ? l : l?.name ?? '').toLowerCase().replace(/^type:/, ''));
  for (const [label, type] of TYPE_LABELS) if (names.includes(label)) return type;
  return 'unclassified';
}

/**
 * Open issues the owner filed, as backlog tickets flagged "waiting for the ledger".
 * Pull requests (they carry a `pull_request` key) and other authors are ignored.
 */
export function pendingFromIssues(items) {
  if (!Array.isArray(items)) return [];
  const out = [];
  for (const item of items) {
    if (item === null || typeof item !== 'object' || 'pull_request' in item) continue;
    if (String(item.user?.login ?? '').toLowerCase() !== OWNER) continue;
    const issue = positiveInt(item.number);
    if (issue === null || typeof item.title !== 'string') continue;
    const ticket = normalizeTicket({
      issue,
      kind: 'issue',
      title: item.title,
      type: typeFromLabels(item.labels),
      author: OWNER,
      opened_at: item.created_at,
      updated_at: item.updated_at ?? item.created_at,
      stage: 'backlog',
      env: 'none',
      flags: ['waiting-for-ledger'],
    });
    if (ticket !== null) out.push({ ...ticket, pending: true });
  }
  return out;
}

// ------------------------------------------------------------------ poller

const FETCH_BASE = { cache: 'no-store', credentials: 'omit', referrerPolicy: 'no-referrer', method: 'GET' };

export function defaultSources() {
  return {
    state: { url: RAW_STATE_URL, label: 'raw' },
    api: { url: API_STATE_URL },
    issues: { url: API_ISSUES_URL, api: true },
  };
}

/**
 * @param {object} o
 * @param {typeof fetch} o.fetchFn
 * @param {() => number} o.now
 * @param {() => boolean} o.isVisible
 * @param {ReturnType<typeof defaultSources>} o.sources
 * @param {{ onState, onIssues, onOk, onProblem, onNotFound, onRound }} o.handlers
 */
export function createPoller({ fetchFn, now, isVisible, sources, handlers }) {
  const budget = new RateBudget();
  const slots = {
    state: { nextAt: 0, failures: 0, lastAt: -Infinity },
    api: { nextAt: 0, failures: 0, lastAt: -Infinity, etag: null },
    issues: { nextAt: 0, failures: 0, lastAt: -Infinity, etag: null },
  };
  const enabled = { state: true, api: sources.api !== null && sources.api !== undefined, issues: sources.issues !== null && sources.issues !== undefined };
  const usesApi = (name) => name === 'api' || (name === 'issues' && sources.issues?.api === true);
  const budgetKey = (name) => (name === 'api' ? 'state' : name);

  const headersFor = (name) => {
    if (!usesApi(name)) return undefined;
    const headers = { Accept: name === 'api' ? 'application/vnd.github.raw+json' : 'application/vnd.github+json' };
    if (slots[name].etag) headers['If-None-Match'] = slots[name].etag;
    return headers;
  };

  const intervalFor = (name, t) => {
    if (name === 'state') return RAW_INTERVAL_MS;
    if (!usesApi(name)) return RAW_INTERVAL_MS;
    const spaced = budget.intervalMs(t);
    return name === 'issues' && spaced === API_INTERVAL_MS ? ISSUES_INTERVAL_MS : spaced;
  };

  const urlFor = (name) => (name === 'state' ? sources.state.url : sources[name].url);

  async function call(name, onOk) {
    const slot = slots[name];
    const started = now();
    slot.lastAt = started;
    let response;
    try {
      response = await fetchFn(urlFor(name), { ...FETCH_BASE, headers: headersFor(name) });
    } catch {
      fail(name, 'network', `${label(name)} could not be reached.`);
      return;
    }
    const t = now();
    if (usesApi(name)) budget.observe(response.headers, t);
    if (usesApi(name) && (response.status === 403 || response.status === 429)) {
      budget.blocked(response.headers, t);
      slot.nextAt = Math.max(budget.retryAt(budgetKey(name), t), t + intervalFor(name, t));
      handlers.onProblem?.({ source: label(name), kind: 'rate-limit', status: response.status, message: `${label(name)} is rate limited; backing off.` });
      return;
    }
    if (response.status === 304 && slot.etag) {
      succeed(name, t);
      return;
    }
    if (response.status === 404) {
      slot.failures += 1;
      slot.nextAt = t + failureDelayMs(slot.failures);
      handlers.onNotFound?.({ source: label(name) });
      return;
    }
    if (!response.ok) {
      fail(name, 'http', `${label(name)} answered HTTP ${response.status}.`);
      return;
    }
    let body;
    try {
      body = await response.text();
    } catch {
      fail(name, 'network', `${label(name)} was cut off while reading.`);
      return;
    }
    const outcome = onOk(body, response);
    if (outcome === true) {
      if (name !== 'state') slot.etag = response.headers.get('etag') ?? slot.etag;
      succeed(name, t);
    } else {
      fail(name, 'data', outcome);
    }
  }

  function label(name) {
    return name === 'state' ? sources.state.label : name === 'api' ? 'api' : 'issues';
  }

  function succeed(name, t) {
    slots[name].failures = 0;
    slots[name].nextAt = t + intervalFor(name, t);
    if (usesApi(name)) budget.succeeded();
    handlers.onOk?.({ source: label(name) });
  }

  function fail(name, kind, message) {
    const slot = slots[name];
    const t = now();
    slot.failures += 1;
    slot.nextAt = t + failureDelayMs(slot.failures);
    handlers.onProblem?.({ source: label(name), kind, message });
  }

  function parseStateBody(source) {
    return (body) => {
      let json;
      try {
        json = JSON.parse(body);
      } catch {
        return `${source} returned something that is not valid JSON.`;
      }
      const result = parseState(json);
      if (result.status !== 'ok') return `${source}: ${result.message}`;
      handlers.onState?.({ state: result.state, source });
      return true;
    };
  }

  function parseIssuesBody(body) {
    let json;
    try {
      json = JSON.parse(body);
    } catch {
      return 'issues returned something that is not valid JSON.';
    }
    if (!Array.isArray(json)) return 'issues returned an unexpected shape.';
    handlers.onIssues?.(pendingFromIssues(json));
    return true;
  }

  function isDue(name, t, force, burst) {
    if (!enabled[name]) return false;
    if (force) return burst || t - slots[name].lastAt >= MIN_FORCE_GAP_MS;
    return t >= slots[name].nextAt;
  }

  /** Whether the API may be used for `name` now; when not, park its next attempt at the earliest retry. */
  function apiAllowed(name, t) {
    if (!usesApi(name)) return true;
    const retry = budget.retryAt(budgetKey(name), t);
    if (retry <= t) return true;
    slots[name].nextAt = Math.max(slots[name].nextAt, retry);
    return false;
  }

  /**
   * Run every call that is due. `force` (manual refresh, tab shown again) ignores the schedule, not the
   * budget, and not a 5 s gap that stops a double click hammering the APIs. `burst` (retry after an
   * error) skips the gap as well.
   */
  async function tick({ force = false, burst = false } = {}) {
    if (!isVisible() && !force) return;
    const t = now();
    const jobs = [];
    if (isDue('state', t, force, burst)) jobs.push(call('state', parseStateBody(sources.state.label)));
    if (isDue('api', t, force, burst) && apiAllowed('api', t)) jobs.push(call('api', parseStateBody('api')));
    if (isDue('issues', t, force, burst) && apiAllowed('issues', t)) jobs.push(call('issues', parseIssuesBody));
    await Promise.allSettled(jobs);
    handlers.onRound?.();
  }

  /** Milliseconds until something is due again, kept between 1 s and 60 s so a wake is never lost. */
  function nextDelayMs() {
    const t = now();
    const times = Object.keys(slots)
      .filter((name) => enabled[name])
      .map((name) => slots[name].nextAt);
    return Math.min(60_000, Math.max(1000, Math.min(...times) - t));
  }

  return {
    tick,
    nextDelayMs,
    budget,
    snapshot: () => ({ remaining: budget.remaining, etags: { api: slots.api.etag, issues: slots.issues.etag } }),
  };
}
