// Grep-able promises: the app only reads, and never turns text into markup.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));

async function files(dir, ext) {
  const out = [];
  for (const entry of await readdir(join(root, dir), { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) out.push(...(await files(path, ext)));
    else if (entry.name.endsWith(ext)) out.push(path);
  }
  return out;
}

const sources = await Promise.all((await files('js', '.js')).map(async (f) => [f, await readFile(join(root, f), 'utf8')]));

test('no script, markup or event-handler sinks in the app code', () => {
  const banned = [
    [/\binnerHTML\b/, 'innerHTML'],
    [/\bouterHTML\b/, 'outerHTML'],
    [/\binsertAdjacentHTML\b/, 'insertAdjacentHTML'],
    [/\bdocument\.write\b/, 'document.write'],
    [/\beval\s*\(/, 'eval'],
    [/\bnew Function\b/, 'new Function'],
    [/\bsetTimeout\(\s*['"`]/, 'string timer'],
    [/\.srcdoc\b/, 'srcdoc'],
    [/\.setAttribute\(\s*['"`]on/i, 'inline handler attribute'],
    [/\.setAttribute\(\s*['"`]style/i, 'inline style attribute'],
    [/\bcreateContextualFragment\b/, 'createContextualFragment'],
    [/\bDOMParser\b/, 'DOMParser'],
    [/\bXMLHttpRequest\b/, 'XMLHttpRequest'],
    [/\bsendBeacon\b/, 'sendBeacon'],
    [/\bWebSocket\b/, 'WebSocket'],
    [/\bEventSource\b/, 'EventSource'],
  ];
  for (const [file, code] of sources) {
    const body = code.replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '');
    for (const [pattern, name] of banned) assert.doesNotMatch(body, pattern, `${file} uses ${name}`);
  }
});

test('the only network call is one fetch, and it is a GET without credentials', () => {
  const fetches = sources.flatMap(([file, code]) => [...code.matchAll(/\bfetch\w*\s*\(/g)].map(() => file));
  assert.deepEqual([...new Set(fetches)].sort(), ['js/data.js', 'js/main.js']);
  const data = sources.find(([f]) => f === 'js/data.js')[1];
  assert.match(data, /method: 'GET'/);
  assert.doesNotMatch(data, /\b(POST|PUT|PATCH|DELETE)\b/);
  assert.doesNotMatch(data, /authorization|token/i);
  assert.match(data, /credentials: 'omit'/);
});

test('the page ships a strict content security policy and no inline code', async () => {
  const html = await readFile(join(root, 'index.html'), 'utf8');
  const csp = html.match(/Content-Security-Policy" content="([^"]+)"/)[1];
  for (const part of ["default-src 'none'", "script-src 'self'", "style-src 'self'", "base-uri 'none'", "form-action 'none'", 'connect-src \'self\' https://raw.githubusercontent.com https://api.github.com']) {
    assert.ok(csp.includes(part), `CSP lacks ${part}`);
  }
  assert.doesNotMatch(csp, /unsafe-inline|unsafe-eval|\*/);
  assert.doesNotMatch(html, /<script(?![^>]*\bsrc=)[^>]*>/i, 'no inline scripts');
  assert.doesNotMatch(html, /\son\w+\s*=/i, 'no inline handlers');
  assert.doesNotMatch(html, /\sstyle\s*=/i, 'no style attributes');
  assert.doesNotMatch(html, /(href|src)="https?:/i, 'no external resources in the page');
});

test('no em dashes, no placeholder names, relative asset URLs only', async () => {
  const all = [...(await files('js', '.js')), ...(await files('css', '.css')), 'index.html', 'package.json', ...(await files('test', '.mjs')), 'README.md'];
  for (const file of all) {
    let text;
    try {
      text = await readFile(join(root, file), 'utf8');
    } catch {
      continue;
    }
    assert.ok(!text.includes(String.fromCharCode(0x2014)), `${file} contains an em dash`);
    assert.doesNotMatch(text, /royal\s*mail/i, `${file} names a postal operator`);
  }
  const html = await readFile(join(root, 'index.html'), 'utf8');
  for (const [, url] of html.matchAll(/(?:href|src)="([^"#]+)"/g)) assert.ok(url.startsWith('./') || url.startsWith('data:'), `${url} must be relative`);
});
