import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { BOARD_STAGES, AGENT_STATES } from '../js/schema.js';
import { OUTCOME_GLYPH, NODE_STATES } from '../js/charts.js';
import { MACROBANDS, CHIP_STATES, LANE_TONES } from '../js/views/board.js';
import { GATE_STATUSES, CHAIN_STATUSES, SPLIT, HOP_STATUS } from '../js/views/ticket.js';
import { HOP_ACTIONS, MODE_TONES, TYPE_TONE, ENV_BADGE } from '../js/views/common.js';
import { ROW_STATUS, OUTCOME } from '../js/views/environments.js';
import { SEVERITY_TONE } from '../js/views/trail.js';
import { RESULT_TONE } from '../js/views/agents.js';
import { BADGE_TONES, classToken } from '../js/dom.js';
import { COST_BANDS } from '../js/model.js';

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
  const rawCss = (await Promise.all(cssList.map((f) => readFile(join(root, f), 'utf8')))).join('\n');
  const cleanCss = rawCss.replace(/\/\*[\s\S]*?\*\//g, '');
  const cssClasses = new Set();
  let prelude = '';
  for (let i = 0; i < cleanCss.length; i++) {
    const ch = cleanCss[i];
    if (ch === '{') {
      const text = prelude.trim();
      if (!text.startsWith('@keyframes')) {
        for (const m of text.matchAll(/\.([a-zA-Z0-9_-]+)/g)) {
          cssClasses.add(m[1]);
        }
      }
      prelude = '';
    } else if (ch === '}' || ch === ';') {
      prelude = '';
    } else {
      prelude += ch;
    }
  }

  const ENUM_PREFIX_MAP = {
    'col-': BOARD_STAGES,
    'st-text-': BOARD_STAGES,
    'st-bg-': BOARD_STAGES,
    'st-fill-': BOARD_STAGES,
    'release-': Object.keys(OUTCOME_GLYPH),
    'node-': NODE_STATES,
    'tone-': BADGE_TONES,
    'state-': AGENT_STATES,
    'agent-': AGENT_STATES,
    'dot-': [...new Set([...CHIP_STATES, ...LANE_TONES])],
    'card-': CHIP_STATES,
    'band-': [...MACROBANDS.map((m) => m.id), ...COST_BANDS],
    'mode-': MODE_TONES,
    'callout-': ['danger', 'info'],
    'env-': ['staging', 'production'],
    'hop-': [...new Set([...Object.keys(HOP_STATUS).map(classToken), ...HOP_ACTIONS.map(classToken)])],
    'gate-': GATE_STATUSES,
    'chain-': CHAIN_STATUSES,
    'fill-': ['ok', 'high', 'over', 'warn', 'info', 'accent', 'bad'],
  };

  const SPLIT_CLASSES = [...SPLIT.map((s) => s[2]), 'split-other'];

  const requiredClasses = new Set();
  for (const [prefix, variants] of Object.entries(ENUM_PREFIX_MAP)) {
    for (const v of variants) requiredClasses.add(`${prefix}${v}`);
  }
  for (const c of SPLIT_CLASSES) requiredClasses.add(c);

  const unmappedTemplates = [];

  function parseClassTemplate(rawTpl) {
    let i = 0;
    let staticPart = '';
    while (i < rawTpl.length) {
      if (rawTpl[i] === '$' && rawTpl[i + 1] === '{') {
        const tokens = staticPart.split(/\s+/);
        const prefixCandidate = tokens[tokens.length - 1];
        if (prefixCandidate && prefixCandidate.endsWith('-')) {
          if (!ENUM_PREFIX_MAP[prefixCandidate]) {
            unmappedTemplates.push(`Unknown template prefix: ${prefixCandidate}`);
          }
        }
        for (const t of tokens) {
          if (/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(t) && !t.endsWith('-')) {
            requiredClasses.add(t);
          }
        }
        staticPart = '';
        let depth = 1;
        i += 2;
        let expr = '';
        while (i < rawTpl.length && depth > 0) {
          if (rawTpl[i] === '{') depth++;
          else if (rawTpl[i] === '}') {
            depth--;
            if (depth === 0) break;
          } else {
            expr += rawTpl[i];
          }
          i++;
        }
        let qTarget = expr;
        const qIdx = expr.indexOf('?');
        if (qIdx !== -1) qTarget = expr.slice(qIdx + 1);
        for (const m of qTarget.matchAll(/['"]([^'"]+)['"]/g)) {
          for (const t of m[1].trim().split(/\s+/)) {
            if (/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(t)) requiredClasses.add(t);
          }
        }
      } else {
        staticPart += rawTpl[i];
      }
      i++;
    }
    for (const t of staticPart.split(/\s+/)) {
      if (/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(t) && !t.endsWith('-')) {
        requiredClasses.add(t);
      }
    }
  }

  for (const [file, code] of sources) {
    const lines = code.split('\n');
    lines.forEach((l) => {
      // 1. Template literals assigned to class or cls
      const tplMatches = l.matchAll(/\b(?:class(?:Name)?|cls)\s*:\s*`([^`]*)`|\b(?:const|let|var)\s+cls\s*=\s*`([^`]*)`|\bclass\s*=\s*`([^`]*)`/g);
      for (const tm of tplMatches) {
        parseClassTemplate(tm[1] ?? tm[2] ?? tm[3]);
      }

      // 2. Class property strings or conditional expressions
      const propMatches = l.matchAll(/\b(?:class(?:Name)?|cls)\s*:\s*([^,`}\n]+)/g);
      for (const pm of propMatches) {
        let expr = pm[1];
        const qIdx = expr.indexOf('?');
        if (qIdx !== -1) expr = expr.slice(qIdx + 1);
        for (const m of expr.matchAll(/['"]([^'"]+)['"]/g)) {
          for (const t of m[1].trim().split(/\s+/)) {
            if (/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(t)) requiredClasses.add(t);
          }
        }
      }

      // 3. Variable assignments to cls
      const varMatches = l.matchAll(/\b(?:const|let|var)\s+cls\s*=\s*([^;`\n]+)/g);
      for (const vm of varMatches) {
        let expr = vm[1];
        const qIdx = expr.indexOf('?');
        if (qIdx !== -1) expr = expr.slice(qIdx + 1);
        for (const m of expr.matchAll(/['"]([^'"]+)['"]/g)) {
          for (const t of m[1].trim().split(/\s+/)) {
            if (/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(t)) requiredClasses.add(t);
          }
        }
      }

      // 4. classList calls
      for (const m of l.matchAll(/\bclassList\.(?:add|remove|toggle)\s*\(\s*(['"])(.*?)\1\s*\)/g)) {
        for (const t of m[2].trim().split(/\s+/)) {
          if (/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(t)) requiredClasses.add(t);
        }
      }

      // 5. badge(..., ..., className) parsed per call with depth awareness
      // (handled per-file below outside line loop)

      // 6. text(x, y, cls, ...) in charts.js
      if (file.endsWith('charts.js')) {
        for (const tm of l.matchAll(/\btext\s*\([^,]+,[^,]+,\s*([^,]+),/g)) {
          let expr = tm[1];
          const qIdx = expr.indexOf('?');
          if (qIdx !== -1) expr = expr.slice(qIdx + 1);
          for (const m of expr.matchAll(/['"]([^'"]+)['"]/g)) {
            for (const t of m[1].trim().split(/\s+/)) {
              if (/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(t)) requiredClasses.add(t);
            }
          }
        }
      }
    });

    // Extract stateTone assignments and lane tones from board.js
    if (file.endsWith('board.js')) {
      for (const m of code.matchAll(/\bstateTone\s*=\s*['"]([^'"]+)['"]/g)) {
        requiredClasses.add(`card-${m[1]}`);
        requiredClasses.add(`dot-${m[1]}`);
      }
      for (const m of code.matchAll(/\btone\s*:\s*['"]([^'"]+)['"]/g)) {
        requiredClasses.add(`dot-${m[1]}`);
      }
    }

    // 5. badge(..., ..., className) parsed with depth awareness (handles conditionals & multiple arguments)
    const badgeRegex = /\bbadge\s*\(/g;
    let bMatch;
    while ((bMatch = badgeRegex.exec(code)) !== null) {
      const start = bMatch.index + bMatch[0].length;
      let depth = 1;
      let currentArg = '';
      const args = [];
      for (let i = start; i < code.length; i++) {
        const ch = code[i];
        if (ch === '(' || ch === '[' || ch === '{') depth++;
        else if (ch === ')' || ch === ']' || ch === '}') {
          depth--;
          if (depth === 0) {
            args.push(currentArg.trim());
            break;
          }
        } else if (ch === ',' && depth === 1) {
          args.push(currentArg.trim());
          currentArg = '';
          continue;
        }
        currentArg += ch;
      }
      if (args.length >= 2) {
        const toneArg = args[1]
          .replace(/[!=]==?\s*['"][^'"]+['"]/g, '')
          .replace(/['"][^'"]+['"]\s*[!=]==?/g, '');
        for (const m of toneArg.matchAll(/['"]([^'"]+)['"]/g)) {
          const toneVal = m[1].trim();
          assert.ok(
            BADGE_TONES.includes(toneVal),
            `badge tone "${toneVal}" in ${file} is not in BADGE_TONES: ${BADGE_TONES.join(', ')}`,
          );
          requiredClasses.add(`tone-${toneVal}`);
        }
      }
      if (args.length >= 3) {
        const classArg = args[2];
        for (const m of classArg.matchAll(/['"]([^'"]+)['"]/g)) {
          for (const t of m[1].trim().split(/\s+/)) {
            if (/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(t)) requiredClasses.add(t);
          }
        }
      }
    }
  }

  // 7. Scan index.html for static classes
  const html = await readFile(join(root, 'index.html'), 'utf8');
  for (const m of html.matchAll(/\bclass=["']([^"']+)["']/g)) {
    for (const t of m[1].trim().split(/\s+/)) {
      if (/^[a-zA-Z][a-zA-Z0-9_-]*$/.test(t)) requiredClasses.add(t);
    }
  }

  assert.deepEqual(unmappedTemplates, [], 'All template literal prefixes must be registered in ENUM_PREFIX_MAP');

  const missing = [];
  for (const cls of requiredClasses) {
    if (!cssClasses.has(cls)) {
      missing.push(`class "${cls}" has no rule in css/*.css`);
    }
  }

  assert.deepEqual(missing, []);
});

test('all exported tone maps produce values that belong to BADGE_TONES', () => {
  for (const [key, tone] of Object.entries(SEVERITY_TONE)) {
    assert.ok(BADGE_TONES.includes(tone), `SEVERITY_TONE["${key}"] = "${tone}" is not in BADGE_TONES: ${BADGE_TONES.join(', ')}`);
  }
  for (const [key, tone] of Object.entries(RESULT_TONE)) {
    assert.ok(BADGE_TONES.includes(tone), `RESULT_TONE["${key}"] = "${tone}" is not in BADGE_TONES: ${BADGE_TONES.join(', ')}`);
  }
  for (const [key, tone] of Object.entries(TYPE_TONE)) {
    assert.ok(BADGE_TONES.includes(tone), `TYPE_TONE["${key}"] = "${tone}" is not in BADGE_TONES: ${BADGE_TONES.join(', ')}`);
  }
  for (const [key, [, tone]] of Object.entries(ENV_BADGE)) {
    assert.ok(BADGE_TONES.includes(tone), `ENV_BADGE["${key}"][1] = "${tone}" is not in BADGE_TONES: ${BADGE_TONES.join(', ')}`);
  }
  for (const [key, [, tone]] of Object.entries(HOP_STATUS)) {
    assert.ok(BADGE_TONES.includes(tone), `HOP_STATUS["${key}"][1] = "${tone}" is not in BADGE_TONES: ${BADGE_TONES.join(', ')}`);
  }
  for (const [key, [, tone]] of Object.entries(ROW_STATUS)) {
    assert.ok(BADGE_TONES.includes(tone), `ROW_STATUS["${key}"][1] = "${tone}" is not in BADGE_TONES: ${BADGE_TONES.join(', ')}`);
  }
  for (const [key, [, tone]] of Object.entries(OUTCOME)) {
    assert.ok(BADGE_TONES.includes(tone), `OUTCOME["${key}"][1] = "${tone}" is not in BADGE_TONES: ${BADGE_TONES.join(', ')}`);
  }
});
