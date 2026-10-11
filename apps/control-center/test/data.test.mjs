import { test } from 'node:test';
import assert from 'node:assert/strict';

import { API_INTERVAL_MS, RAW_INTERVAL_MS, RESERVE, SCARCE, RateBudget, createPoller, defaultSources, failureDelayMs } from '../js/data.js';
import { createStore } from '../js/store.js';
import { API_ISSUES_URL, API_STATE_URL, RAW_STATE_URL } from '../js/safe.js';
import { rawIssues, rawSample } from './helpers.mjs';

const NOW0 = Date.parse('2026-10-11T20:07:00Z');
const json = (body, headers = {}, status = 200) => new Response(status === 304 ? null : typeof body === 'string' ? body : JSON.stringify(body), { status, headers });
const withLimit = (remaining, resetInS, extra = {}) => ({ 'x-ratelimit-remaining': String(remaining), 'x-ratelimit-reset': String(Math.floor(NOW0 / 1000) + resetInS), ...extra });

/** A poller wired to a scripted fake network and a clock the test moves by hand. */
function rig({ routes, visible = true, sources = defaultSources() }) {
  const clock = { now: NOW0 };
  const calls = [];
  const events = { states: [], issues: [], problems: [], notFound: [], ok: [], rounds: 0 };
  const fetchFn = async (url, init = {}) => {
    calls.push({ url, init, at: clock.now });
    const route = routes[url];
    if (!route) throw new TypeError('network down');
    const next = typeof route === 'function' ? route(init, calls.filter((c) => c.url === url).length) : route;
    return typeof next === 'function' ? next() : next;
  };
  const state = { visible };
  const poller = createPoller({
    fetchFn,
    now: () => clock.now,
    isVisible: () => state.visible,
    sources,
    handlers: {
      onState: (r) => events.states.push(r),
      onIssues: (l) => events.issues.push(l),
      onOk: (i) => events.ok.push(i.source),
      onProblem: (p) => events.problems.push(p),
      onNotFound: (n) => events.notFound.push(n),
      onRound: () => (events.rounds += 1),
    },
  });
  return { poller, clock, calls, events, state, advance: (ms) => (clock.now += ms), callsTo: (url) => calls.filter((c) => c.url === url) };
}

const okRoutes = (limit = withLimit(58, 3000)) => ({
  [RAW_STATE_URL]: () => json(rawSample),
  [API_STATE_URL]: (init) => (init.headers?.['If-None-Match'] === '"v1"' ? json('', { ...limit, etag: '"v1"' }, 304) : json(rawSample, { ...limit, etag: '"v1"' })),
  [API_ISSUES_URL]: (init) => (init.headers?.['If-None-Match'] === '"i1"' ? json('', { ...limit, etag: '"i1"' }, 304) : json(rawIssues, { ...limit, etag: '"i1"' })),
});

test('first tick reads all three sources with GET only, no credentials, no body', async () => {
  const r = rig({ routes: okRoutes() });
  await r.poller.tick();
  assert.equal(r.calls.length, 3);
  for (const c of r.calls) {
    assert.equal(c.init.method, 'GET');
    assert.equal(c.init.body, undefined);
    assert.equal(c.init.credentials, 'omit');
    assert.equal(c.init.cache, 'no-store');
    assert.equal(JSON.stringify(c.init.headers ?? {}).toLowerCase().includes('authorization'), false);
  }
  assert.equal(r.callsTo(RAW_STATE_URL)[0].init.headers, undefined, 'raw is a plain request');
  assert.equal(r.callsTo(API_STATE_URL)[0].init.headers.Accept, 'application/vnd.github.raw+json');
  assert.deepEqual(r.events.states.map((s) => s.source).sort(), ['api', 'raw']);
  assert.equal(r.events.issues.length, 1);
  assert.equal(r.events.issues[0].length, 2, 'owner issues only, no pull requests');
  assert.equal(r.events.rounds, 1);
});

test('schedule: raw and the issue list every 30 s, the API state every 60 s', async () => {
  const r = rig({ routes: okRoutes() });
  await r.poller.tick();
  r.advance(RAW_INTERVAL_MS);
  await r.poller.tick();
  assert.equal(r.callsTo(RAW_STATE_URL).length, 2);
  assert.equal(r.callsTo(API_STATE_URL).length, 1, 'not due yet');
  assert.equal(r.callsTo(API_ISSUES_URL).length, 2, 'new issues are the thing a viewer waits for: asked every 30 s');
  r.advance(API_INTERVAL_MS - RAW_INTERVAL_MS);
  await r.poller.tick();
  assert.equal(r.callsTo(API_STATE_URL).length, 2);
  assert.equal(r.callsTo(API_ISSUES_URL).length, 3);
});

test('ETag: remembered and sent back, and a 304 changes nothing', async () => {
  const r = rig({ routes: okRoutes() });
  await r.poller.tick();
  assert.equal(r.callsTo(API_STATE_URL)[0].init.headers['If-None-Match'], undefined);
  assert.deepEqual(r.poller.snapshot().etags, { api: '"v1"', issues: '"i1"' });
  r.advance(API_INTERVAL_MS);
  const before = r.events.states.length;
  await r.poller.tick();
  assert.equal(r.callsTo(API_STATE_URL)[1].init.headers['If-None-Match'], '"v1"');
  assert.equal(r.callsTo(API_ISSUES_URL)[1].init.headers['If-None-Match'], '"i1"');
  assert.equal(r.events.states.filter((s) => s.source === 'api').length, 1, 'no second api document');
  assert.equal(r.events.states.length, before + 1, 'only raw produced a document this round');
  assert.equal(r.events.issues.length, 1, 'issues unchanged');
  assert.equal(r.events.problems.length, 0, 'a 304 is success');
});

test('rate budget: below the scarce line only the issues call continues, spread out', async () => {
  const r = rig({ routes: okRoutes(withLimit(SCARCE - 1, 2400)) });
  await r.poller.tick();
  r.advance(API_INTERVAL_MS);
  await r.poller.tick();
  assert.equal(r.callsTo(API_STATE_URL).length, 1, 'state accelerator stopped');
  assert.equal(r.callsTo(API_ISSUES_URL).length, 1, 'spread out: 60 s is too soon for 24 spendable calls over 40 minutes');
  r.advance(45_000);
  await r.poller.tick();
  assert.equal(r.callsTo(API_ISSUES_URL).length, 2, 'issues is the priority call and keeps going');
  assert.equal(r.callsTo(API_STATE_URL).length, 1, 'the accelerator does not');
  // stretched so the remaining calls last until reset: (2400 - 60) s / (39 - 15) calls ~ 97 s
  const gap = r.poller.budget.intervalMs(r.clock.now);
  assert.ok(gap > API_INTERVAL_MS, `interval stretched (${gap})`);
});

test('rate budget: below the reserve the API is left alone until reset, raw keeps going', async () => {
  const routes = okRoutes(withLimit(RESERVE - 1, 600));
  const r = rig({ routes });
  await r.poller.tick();
  for (let i = 0; i < 8; i += 1) {
    r.advance(RAW_INTERVAL_MS);
    await r.poller.tick();
  }
  assert.equal(r.callsTo(API_STATE_URL).length, 1);
  assert.equal(r.callsTo(API_ISSUES_URL).length, 1);
  assert.ok(r.callsTo(RAW_STATE_URL).length >= 9);
  r.advance(600_000);
  await r.poller.tick();
  assert.equal(r.callsTo(API_ISSUES_URL).length, 2, 'resumes after the window resets');
  assert.equal(r.poller.budget.remaining === null || r.poller.budget.remaining >= RESERVE, true);
});

test('403 with no quota left blocks the API until reset; 429 honours retry-after', async () => {
  const limited = rig({ routes: { ...okRoutes(), [API_STATE_URL]: () => json('{}', withLimit(0, 1800), 403), [API_ISSUES_URL]: () => json('{}', withLimit(0, 1800), 403) } });
  await limited.poller.tick();
  assert.equal(limited.events.problems.filter((p) => p.kind === 'rate-limit').length, 2);
  limited.advance(RAW_INTERVAL_MS * 10);
  await limited.poller.tick();
  assert.equal(limited.callsTo(API_STATE_URL).length, 1, 'still blocked 5 min later');
  limited.advance(1800_000);
  await limited.poller.tick();
  assert.equal(limited.callsTo(API_STATE_URL).length, 2, 'tried again after the reset');

  const retry = rig({ routes: { ...okRoutes(), [API_STATE_URL]: () => json('{}', { 'retry-after': '120', 'x-ratelimit-remaining': '45', 'x-ratelimit-reset': String(Math.floor(NOW0 / 1000) + 3000) }, 429) } });
  await retry.poller.tick();
  retry.advance(100_000);
  await retry.poller.tick();
  assert.equal(retry.callsTo(API_STATE_URL).length, 1);
  retry.advance(30_000);
  await retry.poller.tick();
  assert.equal(retry.callsTo(API_STATE_URL).length, 2);
});

test('failures back off exponentially and clear on success', async () => {
  assert.deepEqual([1, 2, 3, 4, 9].map(failureDelayMs), [30_000, 60_000, 120_000, 240_000, 600_000]);
  let healthy = false;
  const r = rig({ routes: { ...okRoutes(), [RAW_STATE_URL]: () => (healthy ? json(rawSample) : json('boom', {}, 500)) } });
  await r.poller.tick();
  assert.equal(r.events.problems.find((p) => p.source === 'raw').kind, 'http');
  r.advance(29_000);
  await r.poller.tick();
  assert.equal(r.callsTo(RAW_STATE_URL).length, 1, 'inside the 30 s backoff');
  r.advance(2000);
  await r.poller.tick();
  assert.equal(r.callsTo(RAW_STATE_URL).length, 2);
  r.advance(59_000);
  await r.poller.tick();
  assert.equal(r.callsTo(RAW_STATE_URL).length, 2, 'second failure doubles the wait to 60 s');
  healthy = true;
  r.advance(2000);
  await r.poller.tick();
  assert.equal(r.callsTo(RAW_STATE_URL).length, 3);
  r.advance(RAW_INTERVAL_MS);
  await r.poller.tick();
  assert.equal(r.callsTo(RAW_STATE_URL).length, 4, 'back on the normal 30 s cadence');
});

test('bad bodies are problems, not crashes: invalid JSON, wrong version, 404, network error', async () => {
  const mk = (route) => rig({ routes: { [RAW_STATE_URL]: route }, sources: { ...defaultSources(), api: null, issues: null } });
  const a = mk(() => json('{"version": 1,'));
  await a.poller.tick();
  assert.match(a.events.problems[0].message, /not valid JSON/);
  const b = mk(() => json({ version: 2 }));
  await b.poller.tick();
  assert.match(b.events.problems[0].message, /Unsupported/);
  const c = mk(() => json('nope', {}, 404));
  await c.poller.tick();
  assert.equal(c.events.notFound.length, 1);
  const d = mk(() => {
    throw new TypeError('offline');
  });
  await d.poller.tick();
  assert.equal(d.events.problems[0].kind, 'network');
  assert.equal(a.events.states.length + b.events.states.length + c.events.states.length + d.events.states.length, 0);
});

test('hidden tab: nothing is fetched; a forced refresh (tab shown again) fetches at once', async () => {
  const r = rig({ routes: okRoutes(), visible: false });
  await r.poller.tick();
  assert.equal(r.calls.length, 0);
  r.state.visible = true;
  await r.poller.tick({ force: true });
  assert.equal(r.calls.length, 3);
  await r.poller.tick({ force: true });
  assert.equal(r.calls.length, 3, 'a second click within 5 s does not hammer the APIs');
  r.advance(6000);
  await r.poller.tick({ force: true });
  assert.equal(r.calls.length, 6);
});

test('?data= mode: one file, no GitHub request, no budget; issues only with &issues=', async () => {
  const fileUrl = 'http://127.0.0.1:1/state.json';
  const issuesUrl = 'http://127.0.0.1:1/issues.json';
  const r = rig({ routes: { [fileUrl]: () => json(rawSample), [issuesUrl]: () => json(rawIssues) }, sources: { state: { url: fileUrl, label: 'file' }, api: null, issues: { url: issuesUrl, api: false } } });
  await r.poller.tick();
  assert.deepEqual(r.calls.map((c) => c.url).sort(), [fileUrl, issuesUrl].sort());
  assert.ok(r.calls.every((c) => c.init.headers === undefined), 'plain requests, no GitHub headers');
  assert.equal(r.events.states[0].source, 'file');
  const solo = rig({ routes: { [fileUrl]: () => json(rawSample) }, sources: { state: { url: fileUrl, label: 'file' }, api: null, issues: null } });
  await solo.poller.tick();
  assert.equal(solo.calls.length, 1);
});

test('RateBudget reads headers and expires at reset', () => {
  const b = new RateBudget();
  const h = (o) => new Headers(o);
  assert.equal(b.canCall('issues', NOW0), true, 'unknown budget: go');
  b.observe(h(withLimit(50, 100)), NOW0);
  assert.equal(b.remaining, 50);
  b.observe(h(withLimit(14, 100)), NOW0);
  assert.equal(b.canCall('issues', NOW0), false);
  assert.equal(b.canCall('issues', NOW0 + 101_000), true, 'window reset');
});

test('store: newest generated_at wins and says where it came from', async () => {
  const store = createStore(() => NOW0);
  const doc = (generated_at, seq = 1) => ({ generated_at, seq, tickets: [], board_stages: [] });
  assert.equal(store.snapshot().phase, 'loading');
  assert.equal(store.acceptState({ state: doc('2026-10-11T20:05:00Z'), source: 'raw' }), true);
  assert.equal(store.snapshot().source, 'raw');
  assert.equal(store.acceptState({ state: doc('2026-10-11T20:06:00Z'), source: 'api' }), true);
  assert.equal(store.snapshot().source, 'api');
  assert.equal(store.acceptState({ state: doc('2026-10-11T20:05:30Z'), source: 'raw' }), false, 'older raw (up to 5 min stale) does not win');
  assert.equal(store.snapshot().source, 'api');
  assert.equal(store.acceptState({ state: doc('2026-10-11T20:09:00Z'), source: 'raw' }), true);
  assert.equal(store.snapshot().source, 'raw');
});

test('store: first-round outcomes, problems clear on success, pending replaced', () => {
  const nothing = createStore(() => NOW0);
  nothing.notFound({ source: 'raw' });
  nothing.endRound();
  assert.equal(nothing.snapshot().phase, 'empty');

  const failed = createStore(() => NOW0);
  failed.problem({ source: 'raw', message: 'raw answered HTTP 500.' });
  failed.endRound();
  assert.equal(failed.snapshot().phase, 'error');
  assert.match(failed.snapshot().message, /HTTP 500/);

  const live = createStore(() => NOW0);
  live.problem({ source: 'api', message: 'rate limited' });
  live.acceptState({ state: { generated_at: '2026-10-11T20:05:00Z', seq: 1, tickets: [] }, source: 'raw' });
  live.endRound();
  assert.equal(live.snapshot().phase, 'ok', 'an API problem alone never hides good data');
  assert.deepEqual(Object.keys(live.snapshot().problems), ['api']);
  live.ok({ source: 'api' });
  assert.deepEqual(Object.keys(live.snapshot().problems), []);
  assert.equal(live.acceptPending([{ issue: 5, title: 'a' }]), true);
  assert.equal(live.acceptPending([{ issue: 5, title: 'a' }]), false);
  assert.equal(live.acceptPending([]), true);
});
