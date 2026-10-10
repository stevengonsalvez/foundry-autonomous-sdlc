// Local development server. Serves the dashboard directory and answers /metrics.json from the
// sample fixture, so nothing is copied into the site. Not part of the published output.
//
//   node test/dev-server.mjs [--port 8080] [--state ok|empty|bad-version|invalid-json|http-500]

import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const fixture = join(root, 'test', 'fixtures', 'metrics.sample.json');
const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i === -1 ? fallback : args[i + 1];
};
const port = Number(opt('port', '8080'));
const state = opt('state', 'ok');

const types = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
};
const PUBLISHED = ['index.html', 'css', 'js'];

function metricsResponse(res) {
  switch (state) {
    case 'empty':
      res.writeHead(404).end('not found');
      return null;
    case 'http-500':
      res.writeHead(500).end('boom');
      return null;
    case 'invalid-json':
      return { body: '{"version": 1,', status: 200 };
    case 'bad-version':
      return { body: JSON.stringify({ version: 2, issues: [] }), status: 200 };
    default:
      return readFile(fixture, 'utf8').then((body) => ({ body, status: 200 }));
  }
}

createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  let path = decodeURIComponent(url.pathname);
  if (path.endsWith('/')) path += 'index.html';

  try {
    if (path === '/metrics.json') {
      const out = await metricsResponse(res);
      if (out) res.writeHead(out.status, { 'content-type': types['.json'], 'cache-control': 'no-store' }).end(out.body);
      return;
    }
    const file = normalize(join(root, path));
    const rel = file.slice(root.length + 1);
    if (!file.startsWith(root + sep) || !PUBLISHED.includes(rel.split(sep)[0])) {
      res.writeHead(404).end('not found');
      return;
    }
    const body = await readFile(file);
    res.writeHead(200, { 'content-type': types[extname(file)] ?? 'application/octet-stream', 'cache-control': 'no-store' }).end(body);
  } catch {
    res.writeHead(404).end('not found');
  }
}).listen(port, '127.0.0.1', () => {
  console.log(`dashboard on http://127.0.0.1:${port}/ (metrics: ${state})`);
});
