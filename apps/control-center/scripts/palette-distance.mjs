// Delivery Flow Control Center - Palette Distance Analysis
// Reads :root tokens from css/styles.css and measured flowtron accents from scripts/flowtron-accents.json.
// Computes OKLab delta-E (dE_ok) and circular hue distance between tokens and flowtron reference accents.
//
// Rule (Stevie Decision):
// 1. Same-role distance: dE_ok >= 0.06 (and at least 12 degrees circular hue when chroma >= 0.03).
// 2. Cross-role proximity: accents within 20 degrees of another-role accent are allowed but listed.
// 3. Neutrals distance: surface ladder differs from flowtron neutrals by dE_ok >= 0.04.
// 4. Stage fills: no two stage fills closer than 25 degrees circular hue AND dE_ok >= 0.06.

import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export function oklchToLab(L, C, h) {
  const rad = (h * Math.PI) / 180;
  return [L, C * Math.cos(rad), C * Math.sin(rad)];
}

export function hexToRgb(hex) {
  const clean = hex.replace('#', '');
  return [
    parseInt(clean.slice(0, 2), 16) / 255,
    parseInt(clean.slice(2, 4), 16) / 255,
    parseInt(clean.slice(4, 6), 16) / 255,
  ];
}

export function srgbToLinear(c) {
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

export function hexToOklab(hex) {
  const [r, g, b] = hexToRgb(hex).map(srgbToLinear);
  const l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b;
  const m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b;
  const s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b;
  const l_ = Math.cbrt(l);
  const m_ = Math.cbrt(m);
  const s_ = Math.cbrt(s);
  const L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_;
  const a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_;
  const bLab = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_;
  return [L, a, bLab];
}

export function labToOklch(L, a, b) {
  const C = Math.hypot(a, b);
  let h = (Math.atan2(b, a) * 180) / Math.PI;
  if (h < 0) h += 360;
  return [L, C, h];
}

export function dE(lab1, lab2) {
  return Math.hypot(lab1[0] - lab2[0], lab1[1] - lab2[1], lab1[2] - lab2[2]);
}

export function circularHueDiff(h1, h2) {
  const d = Math.abs(h1 - h2) % 360;
  return d > 180 ? 360 - d : d;
}

export function oklabToLinearSrgb(L, a, b) {
  const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = L - 0.0894841775 * a - 1.2914855480 * b;
  const l = l_ * l_ * l_;
  const m = m_ * m_ * m_;
  const s = s_ * s_ * s_;
  const r = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s;
  const g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s;
  const bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s;
  return [Math.max(0, r), Math.max(0, g), Math.max(0, bl)];
}

export function relLum(lab) {
  const [r, g, b] = oklabToLinearSrgb(...lab);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrastRatio(lab1, lab2) {
  const l1 = relLum(lab1);
  const l2 = relLum(lab2);
  const max = Math.max(l1, l2);
  const min = Math.min(l1, l2);
  return (max + 0.05) / (min + 0.05);
}

export const SAME_ROLES = {
  '--tone-run': 'auto',
  '--tone-wait': 'assist',
  '--tone-block': 'gate',
  '--tone-info': 'dit',
  '--tone-agent': 'app-1',
  '--tone-done': 'done',
  '--edge-focus': 'dit',
  '--st-fill-backlog': null,
  '--st-fill-refining': 'assist',
  '--st-fill-feasible': 'contract',
  '--st-fill-tests': 'gate',
  '--st-fill-building': 'auto',
  '--st-fill-review': 'app-1',
  '--st-fill-staging': 'dit',
  '--st-fill-prod': 'auto',
  '--st-fill-escalated': 'gate',
  'favicon-dot': 'dit',
  'favicon-bg': 'ink',
};

const flowtronData = JSON.parse(await readFile(new URL('flowtron-accents.json', import.meta.url), 'utf8'));
export const FLOWTRON_ACCENTS = flowtronData.accents ?? flowtronData;
export const FLOWTRON_NEUTRALS = flowtronData.neutrals ?? {};

export async function parseCssTokens(cssPath) {
  const rawCss = await readFile(cssPath, 'utf8');
  const cleanCss = rawCss.replace(/\/\*[\s\S]*?\*\//g, '');
  const rootMatch = cleanCss.match(/:root\s*\{([^}]*)\}/);
  if (!rootMatch) throw new Error(':root block not found in stylesheet');
  const rootContent = rootMatch[1];

  const tokens = {};
  const tokenRegex = /(--[\w-]+)\s*:\s*oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)/g;
  let match;
  while ((match = tokenRegex.exec(rootContent)) !== null) {
    const [, name, L, C, h] = match;
    tokens[name] = {
      name,
      L: parseFloat(L),
      C: parseFloat(C),
      h: parseFloat(h),
      lab: oklchToLab(parseFloat(L), parseFloat(C), parseFloat(h)),
    };
  }
  return tokens;
}

export async function run({ verbose = false } = {}) {
  const print = verbose ? console.log : () => {};
  const root = new URL('../', import.meta.url);
  const cssPath = fileURLToPath(new URL('css/styles.css', root));
  const indexHtmlPath = fileURLToPath(new URL('index.html', root));

  const cssTokens = await parseCssTokens(cssPath);
  const flowtronAccents = FLOWTRON_ACCENTS;

  // Extract favicon colors from index.html with URI decoding (throw if missing, no fallback)
  const html = await readFile(indexHtmlPath, 'utf8');
  const favLinkMatch = html.match(/<link\s+rel=["']icon["']\s+href="([^"]+)"/i) || html.match(/<link\s+rel=["']icon["']\s+href='([^']+)'/i);
  if (!favLinkMatch) throw new Error('favicon <link rel="icon"> not found in index.html');
  const decodedHref = decodeURIComponent(favLinkMatch[1]);
  const favBgMatch = decodedHref.match(/rect[^>]*fill=['"](#[\da-fA-F]{6})['"]/i);
  const favDotMatch = decodedHref.match(/circle[^>]*fill=['"](#[\da-fA-F]{6})['"]/i);
  if (!favBgMatch) throw new Error('Could not parse favicon background color from decoded SVG in index.html');
  if (!favDotMatch) throw new Error('Could not parse favicon dot color from decoded SVG in index.html');
  const favBgHex = favBgMatch[1];
  const favDotHex = favDotMatch[1];

  const favDotLab = hexToOklab(favDotHex);
  const [dotL, dotC, dotH] = labToOklch(...favDotLab);
  cssTokens['favicon-dot'] = { name: 'favicon-dot', L: dotL, C: dotC, h: dotH, lab: favDotLab, hex: favDotHex };

  const favBgLab = hexToOklab(favBgHex);
  const [bgL, bgC, bgH] = labToOklch(...favBgLab);
  cssTokens['favicon-bg'] = { name: 'favicon-bg', L: bgL, C: bgC, h: bgH, lab: favBgLab, hex: favBgHex };

  // Convert flowtron accents to OKLab
  const flowtron = {};
  for (const [name, hex] of Object.entries(flowtronAccents)) {
    const lab = hexToOklab(hex);
    const [L, C, h] = labToOklch(...lab);
    flowtron[name] = { name, hex, L, C, h, lab };
  }

  // Tokens of interest for accent table
  const accentTokens = [
    '--tone-run',
    '--tone-wait',
    '--tone-block',
    '--tone-info',
    '--tone-agent',
    '--tone-done',
    '--edge-focus',
    '--st-fill-backlog',
    '--st-fill-refining',
    '--st-fill-feasible',
    '--st-fill-tests',
    '--st-fill-building',
    '--st-fill-review',
    '--st-fill-staging',
    '--st-fill-prod',
    '--st-fill-escalated',
    'favicon-dot',
  ];

  const accentKeys = Object.keys(flowtron);

  print('# Palette Distance Matrix: Control Center Tokens vs Flowtron Reference Accents\n');
  print('Measurement standard: OKLab Delta-E (dE_ok) and circular hue distance in degrees.');
  print('Rule: Same-role distance dE_ok >= 0.06 and circular hue diff >= 12 deg. Where within 20 deg of another role, explicitly listed.\n');

  // Markdown table header
  const headerCols = ['Our Token', 'OKLCH', 'Role', 'Same-Role Accent', 'Same-Role dE', 'Same-Role dh', 'Min dE Accent', 'Min dE', 'Status'];
  print(`| ${headerCols.join(' | ')} |`);
  print(`| ${headerCols.map(() => '---').join(' | ')} |`);

  let allPass = true;
  const crossRoleNear = [];

  for (const tokenName of accentTokens) {
    const t = cssTokens[tokenName];
    if (!t) throw new Error(`Missing expected accent token: ${tokenName}`);

    let minDE = Infinity;
    let minAccent = '';
    const sameRole = SAME_ROLES[tokenName];
    let sameRoleDE = null;
    let sameRoleDh = null;

    for (const [accName, acc] of Object.entries(flowtron)) {
      const dist = dE(t.lab, acc.lab);
      const dh = circularHueDiff(t.h, acc.h);

      if (dist < minDE) {
        minDE = dist;
        minAccent = accName;
      }

      if (sameRole === accName) {
        sameRoleDE = dist;
        sameRoleDh = dh;
      }

      // Check cross-role within 20 deg
      if (sameRole !== accName && dh < 20 && t.C >= 0.03 && acc.C >= 0.03) {
        crossRoleNear.push({ token: tokenName, accent: accName, dh, dist });
      }
    }

    let pass = true;
    let status = 'PASS';
    if (sameRole) {
      const deOk = sameRoleDE >= 0.06;
      const dhOk = t.C < 0.03 || sameRoleDh >= 12;
      pass = deOk && dhOk;
      status = pass ? 'PASS' : '**FAIL**';
      if (!pass) allPass = false;
    }

    const oklchStr = `${t.L.toFixed(3)} ${t.C.toFixed(3)} ${Math.round(t.h)}°`;
    const roleStr = sameRole || 'neutral';
    const sameDEStr = sameRoleDE !== null ? sameRoleDE.toFixed(4) : '-';
    const sameDhStr = sameRoleDh !== null ? `${sameRoleDh.toFixed(1)}°` : '-';

    print(
      `| \`${tokenName}\` | ${oklchStr} | ${roleStr} | ${sameRole || '-'} | ${sameDEStr} | ${sameDhStr} | ${minAccent} | ${minDE.toFixed(4)} | ${status} |`
    );
  }

  // Full All-Pairs Table
  print('\n### Full All-Pairs Distance Matrix: Every Token vs Every Reference Accent\n');
  const allPairsCols = ['Token', ...accentKeys, 'Min dE', 'Same-Role dE', 'Status'];
  print(`| ${allPairsCols.join(' | ')} |`);
  print(`| ${allPairsCols.map(() => '---').join(' | ')} |`);

  for (const tokenName of accentTokens) {
    const t = cssTokens[tokenName];
    const sameRole = SAME_ROLES[tokenName];
    let minDE = Infinity;
    let sameRoleDE = null;
    const rowVals = [`\`${tokenName}\``];

    for (const accName of accentKeys) {
      const dist = dE(t.lab, flowtron[accName].lab);
      if (dist < minDE) minDE = dist;
      if (accName === sameRole) sameRoleDE = dist;
      rowVals.push(dist.toFixed(4));
    }
    rowVals.push(minDE.toFixed(4));
    rowVals.push(sameRoleDE !== null ? sameRoleDE.toFixed(4) : '-');
    const pass = sameRole === null || (sameRoleDE !== null && sameRoleDE >= 0.06 && (t.C < 0.03 || circularHueDiff(t.h, flowtron[sameRole].h) >= 12));
    rowVals.push(pass ? 'PASS' : '**FAIL**');
    print(`| ${rowVals.join(' | ')} |`);
  }

  print('\n### Cross-Role Accents Within 20° Hue (Permitted by Decision)\n');
  if (crossRoleNear.length === 0) {
    print('None.');
  } else {
    print('| Token | Flowtron Accent | Role of Accent | Hue Diff | dE_ok |');
    print('| --- | --- | --- | --- | --- |');
    for (const c of crossRoleNear) {
      print(`| \`${c.token}\` | \`${c.accent}\` | ${c.accent} | ${c.dh.toFixed(1)}° | ${c.dist.toFixed(4)} |`);
    }
  }

  // Neutrals check across ALL 8 reference neutrals
  print('\n### Neutrals Distance Matrix vs All 8 Reference Neutrals (Target: dE_ok >= 0.04)\n');
  const refNeutrals = ['ink', 'panel', 'panel-2', 'line-soft', 'line', 'muted-2', 'muted', 'text'];
  const refNeutralLabs = Object.fromEntries(refNeutrals.map((n) => [n, hexToOklab(FLOWTRON_NEUTRALS[n])]));

  const ourDarkNeutrals = [
    '--canvas',
    '--surface-0',
    '--surface-1',
    '--surface-2',
    '--surface-3',
    '--edge-subtle',
    '--edge',
    'favicon-bg',
  ];

  const neutralMatrixCols = [
    'Token',
    'Our OKLCH',
    'vs ink',
    'vs panel',
    'vs panel-2',
    'vs line-soft',
    'vs line',
    'vs muted-2',
    'vs muted',
    'vs text',
    'Min dE',
    'Status',
  ];
  print(`| ${neutralMatrixCols.join(' | ')} |`);
  print(`| ${neutralMatrixCols.map(() => '---').join(' | ')} |`);

  let neutralsPass = true;
  for (const tokenName of ourDarkNeutrals) {
    const t = cssTokens[tokenName];
    if (!t) throw new Error(`Missing expected neutral token: ${tokenName}`);

    const dists = refNeutrals.map((n) => dE(t.lab, refNeutralLabs[n]));
    const minD = Math.min(...dists);
    const pass = minD >= 0.04;
    if (!pass) {
      neutralsPass = false;
      allPass = false;
    }

    const row = [
      `\`${tokenName}\``,
      `${t.L.toFixed(3)} ${t.C.toFixed(3)} ${Math.round(t.h)}°`,
      ...dists.map((d) => d.toFixed(4)),
      minD.toFixed(4),
      pass ? 'PASS' : '**FAIL**',
    ];
    print(`| ${row.join(' | ')} |`);
  }

  // Adjacent Surface Rungs Contrast
  print('\n### Adjacent Surface Rungs Contrast (Target: ratio >= 1.10:1)\n');
  const rungPairs = [
    ['--surface-0', '--canvas'],
    ['--surface-1', '--surface-0'],
    ['--surface-2', '--surface-1'],
    ['--surface-3', '--surface-2'],
  ];
  print('| Rung Pair | Upper Surface | Lower Surface | Contrast Ratio | Status |');
  print('| --- | --- | --- | --- | --- |');

  let rungsPass = true;
  for (const [upper, lower] of rungPairs) {
    const u = cssTokens[upper];
    const l = cssTokens[lower];
    if (!u) throw new Error(`Missing upper surface token: ${upper}`);
    if (!l) throw new Error(`Missing lower surface token: ${lower}`);
    const cr = contrastRatio(u.lab, l.lab);
    const pass = cr >= 1.10;
    if (!pass) {
      rungsPass = false;
      allPass = false;
    }
    print(`| \`${upper}\` vs \`${lower}\` | ${u.L.toFixed(3)} | ${l.L.toFixed(3)} | ${cr.toFixed(3)}:1 | ${pass ? 'PASS' : '**FAIL**'} |`);
  }

  // Typography Neutrals
  print('\n### Typography Neutrals vs Flowtron Reference Values\n');
  const typoCols = ['Token', 'Our OKLCH', 'Flowtron Token', 'Flowtron Hex', 'dE_ok', 'Status'];
  print(`| ${typoCols.join(' | ')} |`);
  print(`| ${typoCols.map(() => '---').join(' | ')} |`);

  for (const [tokenName, flowtronName] of Object.entries({ '--fg': 'text', '--fg-dim': 'muted', '--fg-muted': 'muted-2' })) {
    const t = cssTokens[tokenName];
    if (!t) throw new Error(`Missing typography token: ${tokenName}`);
    const fHex = FLOWTRON_NEUTRALS[flowtronName];
    const dist = dE(t.lab, hexToOklab(fHex));
    const pass = dist >= 0.06;
    if (!pass) allPass = false;
    print(`| \`${tokenName}\` | ${t.L.toFixed(3)} ${t.C.toFixed(3)} ${Math.round(t.h)}° | \`${flowtronName}\` | \`${fHex}\` | ${dist.toFixed(4)} | ${pass ? 'PASS' : '**FAIL**'} |`);
  }

  // Stage Fills Inter-Distance Table
  print('\n### Stage Fills Inter-Distance Matrix (Target: Circular dh >= 25° AND dE_ok >= 0.06)\n');
  const stageTokens = [
    '--st-fill-backlog',
    '--st-fill-refining',
    '--st-fill-feasible',
    '--st-fill-tests',
    '--st-fill-building',
    '--st-fill-review',
    '--st-fill-staging',
    '--st-fill-prod',
    '--st-fill-escalated',
  ];

  print('| Stage A | Stage B | Hue A | Hue B | Circular dh | dE_ok | Status |');
  print('| --- | --- | --- | --- | --- | --- | --- |');

  let fillsPass = true;
  for (let i = 0; i < stageTokens.length; i++) {
    for (let j = i + 1; j < stageTokens.length; j++) {
      const a = cssTokens[stageTokens[i]];
      const b = cssTokens[stageTokens[j]];
      if (!a) throw new Error(`Missing stage token: ${stageTokens[i]}`);
      if (!b) throw new Error(`Missing stage token: ${stageTokens[j]}`);
      const dh = circularHueDiff(a.h, b.h);
      const dist = dE(a.lab, b.lab);
      const pass = dh >= 25 && dist >= 0.06;
      if (!pass) fillsPass = false;
      print(
        `| \`${stageTokens[i]}\` | \`${stageTokens[j]}\` | ${Math.round(a.h)}° | ${Math.round(b.h)}° | ${dh.toFixed(1)}° | ${dist.toFixed(4)} | ${pass ? 'PASS' : '**FAIL**'} |`
      );
    }
  }

  print(`\nOverall Accent Same-Role Distance: ${allPass ? 'PASS' : 'FAIL'}`);
  print(`Overall Neutrals Distance Separation: ${neutralsPass ? 'PASS' : 'FAIL'}`);
  print(`Overall Adjacent Surface Rungs Contrast: ${rungsPass ? 'PASS' : 'FAIL'}`);
  print(`Overall Stage Fills Separation: ${fillsPass ? 'PASS' : 'FAIL'}`);
  return { allPass, neutralsPass, fillsPass, rungsPass };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = await run({ verbose: true });
  if (!result.allPass || !result.neutralsPass || !result.fillsPass || !result.rungsPass) {
    process.exit(1);
  }
}
