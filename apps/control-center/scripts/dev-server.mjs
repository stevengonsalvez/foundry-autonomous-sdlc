// Local development server for the control center. Serves the app (index.html, css/, js/), answers
// /state.json and /issues.json from the test fixtures, and serves the fixtures under /fixtures/.
// Not part of the published site.
//
//   node scripts/dev-server.mjs [--port 8090] [--state normal|empty|missing|bad-version|invalid-json|http-500|hostile|stale] [--fixed]
//
// Open http://127.0.0.1:8090/?data=state.json (add &issues=issues.json for pending intake).
// Unless --fixed, every timestamp in the fixture is shifted so the document looks two minutes old
// (35 minutes for --state stale), which keeps the page's relative times and stale badge meaningful.

import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { makeHostile } from '../test/hostile.mjs';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const fixtures = join(root, 'test', 'fixtures');
const PUBLISHED = ['index.html', 'css', 'js'];
const STATES = ['normal', 'empty', 'missing', 'bad-version', 'invalid-json', 'http-500', 'hostile', 'stale'];
const TYPES = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml' };
const ISO = /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z/g;

const readJson = async (name) => JSON.parse(await readFile(join(fixtures, name), 'utf8'));

/** Move every ISO timestamp in the document by `deltaMs`. */
export function shiftTimes(text, deltaMs) {
  const whole = Math.round(deltaMs / 1000) * 1000;
  return text.replace(ISO, (iso) => new Date(Date.parse(iso) + whole).toISOString().replace('.000Z', 'Z'));
}

function emptyDoc(sample, now) {
  const at = new Date(now).toISOString().replace('.000Z', 'Z');
  return {
    version: 1,
    repo: sample.repo,
    generated_at: at,
    updated_at: at,
    seq: 0,
    board_stages: sample.board_stages,
    tickets: [],
    environments: { staging: null, prod: null, history: [], source: 'none' },
    agents: [],
    cost: { totals: {}, caps: sample.cost.caps, billing: null, metrics: null, ledger: { invocations: 0, seconds: 0, usd: 0 } },
    flow: {},
    archived: 0,
    ledger: { events: 0, last_ingest_at: null, mode: 'hosted', last_tick: null, errors: [] },
  };
}

async function stateBody(state, { fixed, now }) {
  if (state === 'empty') return { status: 200, body: JSON.stringify(emptyDoc(await readJson('state.sample.json'), now)) };
  if (state === 'missing') return { status: 404, body: 'not found' };
  if (state === 'http-500') return { status: 500, body: 'boom' };
  if (state === 'invalid-json') return { status: 200, body: '{"version": 1,' };
  if (state === 'bad-version') return { status: 200, body: JSON.stringify({ version: 2, tickets: [] }) };
  const sample = await readJson('state.sample.json');
  const doc = state === 'hostile' ? makeHostile(sample) : sample;
  const text = JSON.stringify(doc);
  if (fixed) return { status: 200, body: text };
  const ageMs = (state === 'stale' ? 35 : 2) * 60_000;
  return { status: 200, body: shiftTimes(text, now - ageMs - Date.parse(doc.generated_at)) };
}

async function issuesBody({ fixed, now }) {
  const text = JSON.stringify(await readJson('issues.sample.json'));
  const sample = await readJson('state.sample.json');
  return fixed ? text : shiftTimes(text, now - 2 * 60_000 - Date.parse(sample.generated_at));
}

export function startServer({ port = 0, state = 'normal', fixed = false } = {}) {
  if (!STATES.includes(state)) throw new Error(`unknown --state ${state}; use one of ${STATES.join(', ')}`);
  const server = createServer(async (req, res) => {
    const send = (status, body, type = 'text/plain; charset=utf-8') =>
      res.writeHead(status, { 'content-type': type, 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' }).end(body);
    if (req.method !== 'GET' && req.method !== 'HEAD') return send(405, 'read only');
    const url = new URL(req.url, 'http://localhost');
    let path = decodeURIComponent(url.pathname);
    if (path.endsWith('/')) path += 'index.html';
    const ctx = { fixed, now: Date.now() };
    try {
      if (path === '/state.json') {
        const out = await stateBody(state, ctx);
        return send(out.status, out.body, TYPES['.json']);
      }
      if (path === '/issues.json') return send(200, await issuesBody(ctx), TYPES['.json']);
      const base = path.startsWith('/fixtures/') ? fixtures : root;
      const rel = path.startsWith('/fixtures/') ? path.slice('/fixtures/'.length) : path.slice(1);
      const file = normalize(join(base, rel));
      const allowed = base === fixtures ? file.startsWith(fixtures + sep) : file.startsWith(root + sep) && PUBLISHED.includes(file.slice(root.length + 1).split(sep)[0]);
      if (!allowed) return send(404, 'not found');
      return send(200, await readFile(file), TYPES[extname(file)] ?? 'application/octet-stream');
    } catch {
      return send(404, 'not found');
    }
  });
  return new Promise((resolveServer) => {
    server.listen(port, '127.0.0.1', () => {
      const { port: actual } = server.address();
      resolveServer({ server, port: actual, url: `http://127.0.0.1:${actual}/`, close: () => new Promise((done) => server.close(done)) });
    });
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const args = process.argv.slice(2);
  const opt = (name, fallback) => (args.includes(`--${name}`) ? args[args.indexOf(`--${name}`) + 1] : fallback);
  const { url } = await startServer({ port: Number(opt('port', '8090')), state: opt('state', 'normal'), fixed: args.includes('--fixed') });
  console.log(`control center on ${url}?data=state.json&issues=issues.json  (state: ${opt('state', 'normal')}${args.includes('--fixed') ? ', fixed times' : ''})`);
}
