import { parseMetrics } from './aggregate.js';
import { renderDashboard, renderEmpty, renderError, renderLoading } from './panels.js';

const METRICS_URL = './metrics.json';
const app = document.getElementById('app');

function show(node) {
  app.replaceChildren(node);
  app.setAttribute('aria-busy', 'false');
}

async function fetchMetrics() {
  let response;
  try {
    response = await fetch(METRICS_URL, { cache: 'no-store' });
  } catch {
    return { status: 'error', message: 'The metrics file could not be fetched. Check your connection, or open this page through a web server rather than from disk.' };
  }
  if (response.status === 404) return { status: 'empty' };
  if (!response.ok) {
    return { status: 'error', message: `The metrics file request failed with HTTP ${response.status}.` };
  }
  const body = await response.text();
  if (body.trim() === '') return { status: 'empty' };
  let json;
  try {
    json = JSON.parse(body);
  } catch {
    return { status: 'error', message: 'metrics.json is not valid JSON.' };
  }
  return parseMetrics(json);
}

async function load() {
  app.setAttribute('aria-busy', 'true');
  app.replaceChildren(renderLoading());
  const result = await fetchMetrics();
  if (result.status === 'ok') {
    show(renderDashboard(result.metrics));
    document.title = `Delivery metrics, ${result.metrics.repo ?? 'Autonomous SDLC'}`;
  } else if (result.status === 'empty') {
    show(renderEmpty(result.metrics ?? {}));
  } else {
    show(renderError(result.message, load));
  }
}

load();
