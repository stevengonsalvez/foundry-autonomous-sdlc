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

test('no stylesheet or script URL is external', async () => {
  const html = await readFile(join(root, 'index.html'), 'utf8');
  for (const match of html.matchAll(/<(?:link|script)\b[^>]*(?:href|src)="([^"]+)"/gi)) {
    const url = match[1];
    assert.ok(!url.startsWith('http:') && !url.startsWith('https:') && !url.startsWith('//'), `${url} must not be external`);
    assert.ok(url.startsWith('./') || url.startsWith('data:'), `${url} must be local relative path`);
  }
});

test('every class name in JS has a corresponding rule in CSS stylesheets', async () => {
  const cssList = await files('css', '.css');
  const cssContent = (await Promise.all(cssList.map((f) => readFile(join(root, f), 'utf8')))).join('\n');
  const cssClasses = new Set();
  const classSelectorRegex = /\.([a-zA-Z0-9_-]+)/g;
  let match;
  while ((match = classSelectorRegex.exec(cssContent)) !== null) {
    cssClasses.add(match[1]);
  }

  // Documented explicit allowlist of dynamic prefix namespaces:
  // - st-text-, st-bg-, st-fill-: dynamic pipeline stage styling
  // - dot-, card-: dynamic lifecycle status chip indicators
  // - band-: dynamic macrobands and cost caps
  // - env-: dynamic environment card variants
  // - callout-: tone variants (danger, info)
  // - state-, agent-: agent state and agent identity classes
  // - release-: release outcome indicators
  // - col-: dynamic stage column identifiers
  // - mode-: stage execution mode markers
  // - tone-: semantic tone utility classes
  // - badge-: status badge color variants
  // - split-: billing cost split categories
  // - kpi-: kpi tone variants
  // - gate-, chain-, hop-: delivery pipeline and gate indicators
  const DYNAMIC_PREFIXES = [
    'st-text-',
    'st-bg-',
    'st-fill-',
    'dot-',
    'card-',
    'band-',
    'env-',
    'callout-',
    'state-',
    'agent-',
    'release-',
    'col-',
    'mode-',
    'tone-',
    'badge-',
    'split-',
    'kpi-',
    'gate-',
    'chain-',
    'hop-',
  ];

  function extractClassesFromCode(code) {
    const classes = new Set();
    const stringPropRe = /\bclass(?:Name)?\s*:\s*(['"])(.*?)\1/gs;
    for (const m of code.matchAll(stringPropRe)) {
      for (const token of m[2].split(/\s+/)) {
        if (/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(token)) classes.add(token);
      }
    }
    const tplPropRe = /\bclass(?:Name)?\s*:\s*`([^`]*)`/gs;
    for (const m of code.matchAll(tplPropRe)) {
      const raw = m[1];
      let depth = 0;
      let currentStatic = '';
      let inExpr = false;
      let expr = '';
      for (let i = 0; i < raw.length; i++) {
        if (!inExpr && raw[i] === '$' && raw[i + 1] === '{') {
          inExpr = true;
          depth = 1;
          i++;
          continue;
        }
        if (inExpr) {
          if (raw[i] === '{') depth++;
          else if (raw[i] === '}') {
            depth--;
            if (depth === 0) {
              inExpr = false;
              for (const sm of expr.matchAll(/['"]([^'"]+)['"]/g)) {
                for (const token of sm[1].split(/\s+/)) {
                  if (/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(token)) classes.add(token);
                }
              }
              expr = '';
              continue;
            }
          }
          expr += raw[i];
        } else {
          currentStatic += raw[i];
        }
      }
      for (const token of currentStatic.split(/\s+/)) {
        if (/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(token)) classes.add(token);
      }
    }
    const classListRe = /\bclassList\.(?:add|remove|toggle)\s*\(\s*(['"`])(.*?)\1\s*\)/g;
    for (const m of code.matchAll(classListRe)) {
      for (const token of m[2].split(/\s+/)) {
        if (/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(token)) classes.add(token);
      }
    }
    return classes;
  }

  const missing = [];
  for (const [file, code] of sources) {
    const classes = extractClassesFromCode(code);
    for (const cls of classes) {
      if (DYNAMIC_PREFIXES.some((p) => cls.startsWith(p))) continue;
      if (!cssClasses.has(cls)) {
        missing.push(`${file} uses class "${cls}" which has no rule in css/*.css`);
      }
    }
  }

  assert.deepEqual(missing, []);
});
