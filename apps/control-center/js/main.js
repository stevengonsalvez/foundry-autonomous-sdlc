// Wires the page: poller -> store -> view. Read only: the only network calls are the GETs in data.js.

import { createPoller, defaultSources } from './data.js';
import { tickRelativeTimes } from './dom.js';
import { formatInteger, plural } from './format.js';
import { limitText, resolveDataParam } from './safe.js';
import { isOpenEscalation } from './model.js';
import { parseRoute, routeTitle } from './router.js';
import { mountShell } from './shell.js';
import { createStore } from './store.js';
import { renderAgents } from './views/agents.js';
import { renderBoard } from './views/board.js';
import { renderCost } from './views/cost.js';
import { renderEnvironments } from './views/environments.js';
import { renderEscalations } from './views/escalations.js';
import { renderFlow } from './views/flow.js';
import { renderLoading, renderError, renderNotFound, renderNothingPublished } from './views/states.js';
import { renderTicket } from './views/ticket.js';
import { renderTrail } from './views/trail.js';

const TICK_UI_MS = 15_000;
const app = document.getElementById('app');
const live = document.getElementById('live');

// ------------------------------------------------------------------ sources

function chooseSources() {
  const params = new URLSearchParams(location.search);
  const data = params.get('data');
  if (data === null) return { sources: defaultSources(), error: null };
  const url = resolveDataParam(data, location.href);
  if (url === null) {
    return { sources: null, error: 'The ?data= parameter must be a relative path to a .json file on this site, for example ?data=state.json.' };
  }
  const issues = params.get('issues');
  const issuesUrl = issues === null ? null : resolveDataParam(issues, location.href);
  return { sources: { state: { url, label: 'file' }, api: null, issues: issuesUrl ? { url: issuesUrl, api: false } : null }, error: null };
}

// ------------------------------------------------------------------ state

const store = createStore(() => Date.now());
const { sources, error: sourceError } = chooseSources();
let shell;
let poller = null;
let lastView = { route: null, key: null, pendingKey: null };
let timer = null;
let busy = false;

const visible = () => document.visibilityState !== 'hidden';

function dataKey(snap) {
  const s = snap.state;
  return `${s.seq}|${s.updated_at}|${s.tickets.length}`;
}

function pendingKey(snap) {
  return snap.pending.map((p) => p.issue).join(',');
}

// ------------------------------------------------------------------ rendering

function viewFor(route, ctx) {
  switch (route.name) {
    case 'board':
      return renderBoard(ctx);
    case 'ticket':
      return renderTicket(ctx, route.issue);
    case 'cost':
      return renderCost(ctx);
    case 'environments':
      return renderEnvironments(ctx);
    case 'agents':
      return renderAgents(ctx);
    case 'escalations':
      return renderEscalations(ctx);
    case 'flow':
      return renderFlow(ctx);
    case 'trail':
      return renderTrail(ctx);
    default:
      return renderNotFound();
  }
}

function show(node) {
  app.replaceChildren(node);
  app.setAttribute('aria-busy', 'false');
}

/** Remember scroll and focus so a background refresh does not throw the reader off their place. */
function captureViewport() {
  const board = app.querySelector('.board');
  return { x: window.scrollX, y: window.scrollY, boardX: board?.scrollLeft ?? 0, focus: document.activeElement?.getAttribute?.('data-fkey') ?? null };
}

function restoreViewport(saved) {
  window.scrollTo(saved.x, saved.y);
  const board = app.querySelector('.board');
  if (board) board.scrollLeft = saved.boardX;
  if (saved.focus) app.querySelector(`[data-fkey="${CSS.escape(saved.focus)}"]`)?.focus({ preventScroll: true });
}

function renderPage({ navigated }) {
  const snap = store.snapshot();
  const route = parseRoute(location.hash);
  shell.setRoute(route);
  shell.paint(snap, Date.now(), route.name);
  document.title = `${routeTitle(route)} | Control Center`;

  if (snap.phase === 'loading') return show(renderLoading());
  if (snap.phase === 'error') return show(renderError(limitText(snap.message ?? 'Unknown error', 400), refresh));
  if (snap.phase === 'empty') return show(renderNothingPublished(refresh));

  const saved = navigated ? null : captureViewport();
  const ctx = { state: snap.state, pending: snap.pending, now: Date.now(), rerender: () => renderPage({ navigated: false }) };
  shell.setEscalations(snap.state.tickets.filter(isOpenEscalation).length);
  show(viewFor(route, ctx));
  lastView = { route: location.hash, key: dataKey(snap), pendingKey: pendingKey(snap) };
  if (navigated) {
    window.scrollTo(0, 0);
    document.getElementById('main').focus({ preventScroll: true });
  } else if (saved) {
    restoreViewport(saved);
  }
}

function announce(snap) {
  const { tickets } = snap.state;
  const escalated = tickets.filter(isOpenEscalation).length;
  live.textContent = `Data updated: ${formatInteger(tickets.length)} ${plural(tickets.length, 'ticket')}, ${formatInteger(escalated)} escalated.`;
}

function onStoreChange(snap, change) {
  if (snap.phase !== 'ok') return renderPage({ navigated: false });
  shell.paint(snap, Date.now(), parseRoute(location.hash).name);
  const changedView = lastView.key !== dataKey(snap) || lastView.pendingKey !== pendingKey(snap) || lastView.route === null;
  if (change === 'state' || change === 'pending') {
    if (changedView) {
      const first = lastView.route === null;
      renderPage({ navigated: false });
      if (!first) announce(snap);
    }
  }
}

// ------------------------------------------------------------------ polling

async function refresh() {
  if (poller === null) return;
  const recovering = store.snapshot().phase !== 'ok';
  if (recovering) store.reset();
  setBusy(true);
  try {
    await poller.tick({ force: true, burst: recovering });
  } finally {
    setBusy(false);
  }
}

function setBusy(value) {
  busy = value;
  shell.setBusy(value);
}

function schedule() {
  clearTimeout(timer);
  if (!visible() || poller === null) return;
  timer = setTimeout(async () => {
    if (!busy) await poller.tick();
    schedule();
  }, poller.nextDelayMs());
}

function start() {
  poller = createPoller({
    fetchFn: (...args) => fetch(...args),
    now: () => Date.now(),
    isVisible: visible,
    sources,
    handlers: {
      onState: (result) => store.acceptState(result),
      onIssues: (list) => store.acceptPending(list),
      onOk: (info) => store.ok(info),
      onProblem: (info) => store.problem(info),
      onNotFound: (info) => store.notFound(info),
      onRound: () => store.endRound(),
    },
  });
  store.subscribe(onStoreChange);
  refresh().then(schedule);
  document.addEventListener('visibilitychange', () => {
    if (visible()) refresh().then(schedule);
    else clearTimeout(timer);
  });
}

// ------------------------------------------------------------------ boot

shell = mountShell({ onRefresh: () => refresh().then(schedule) });
app.replaceChildren(renderLoading());
window.addEventListener('hashchange', () => renderPage({ navigated: true }));
setInterval(() => {
  const now = Date.now();
  tickRelativeTimes(document, now);
  shell.paint(store.snapshot(), now, parseRoute(location.hash).name);
}, TICK_UI_MS);

if (sourceError !== null) {
  show(renderError(sourceError, () => location.assign(location.pathname)));
  shell.paint(store.snapshot(), Date.now());
} else {
  shell.paint(store.snapshot(), Date.now());
  start();
}

