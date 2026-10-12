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

export const FLOWTRON_NEUTRALS = {
  ink: '#0E1217',
  panel: '#161C24',
  'panel-2': '#1B232D',
  'line-soft': '#1F2832',
  line: '#27313D',
  'muted-2': '#4D596A',
  muted: '#697686',
  text: '#CBD6E3',
};

export const SAME_ROLE_NEUTRALS = {
  '--canvas': 'ink',
  '--surface-0': 'ink',
  '--surface-1': 'panel',
  '--surface-2': 'panel-2',
  '--surface-3': 'line-soft',
  '--edge': 'line',
  '--edge-subtle': 'line-soft',
  '--fg': 'text',
  '--fg-dim': 'muted',
  '--fg-muted': 'muted-2',
};

export async function parseCssTokens(cssPath) {
  const css = await readFile(cssPath, 'utf8');
  const tokens = {};
  const tokenRegex = /(--[\w-]+)\s*:\s*oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)/g;
  let match;
  while ((match = tokenRegex.exec(css)) !== null) {
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

export async function run() {
  const root = new URL('../', import.meta.url);
  const cssPath = fileURLToPath(new URL('css/styles.css', root));
  const accentsPath = fileURLToPath(new URL('scripts/flowtron-accents.json', root));
  const indexHtmlPath = fileURLToPath(new URL('index.html', root));

  const cssTokens = await parseCssTokens(cssPath);
  const flowtronAccents = JSON.parse(await readFile(accentsPath, 'utf8'));

  // Extract favicon colors from index.html
  const html = await readFile(indexHtmlPath, 'utf8');
  const favBgMatch = html.match(/rect[^>]*fill=['"](#[\da-fA-F]{6})['"]/);
  const favDotMatch = html.match(/circle[^>]*fill=['"](#[\da-fA-F]{6})['"]/);
  const favBgHex = favBgMatch ? favBgMatch[1] : '#04070d';
  const favDotHex = favDotMatch ? favDotMatch[1] : '#06b6d4';

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

  console.log('# Palette Distance Matrix: Control Center Tokens vs Flowtron Reference Accents\n');
  console.log('Measurement standard: OKLab Delta-E (dE_ok) and circular hue distance in degrees.');
  console.log('Rule: Same-role distance dE_ok >= 0.06 and circular hue diff >= 12 deg. Where within 20 deg of another role, explicitly listed.\n');

  // Markdown table header
  const headerCols = ['Our Token', 'OKLCH', 'Role', 'Same-Role Accent', 'Same-Role dE', 'Same-Role dh', 'Min dE Accent', 'Min dE', 'Status'];
  console.log(`| ${headerCols.join(' | ')} |`);
  console.log(`| ${headerCols.map(() => '---').join(' | ')} |`);

  let allPass = true;
  const crossRoleNear = [];

  for (const tokenName of accentTokens) {
    const t = cssTokens[tokenName];
    if (!t) continue;

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

    const oklchStr = `${t.L.toFixed(2)} ${t.C.toFixed(2)} ${Math.round(t.h)}°`;
    const roleStr = sameRole || 'neutral';
    const sameDEStr = sameRoleDE !== null ? sameRoleDE.toFixed(4) : '-';
    const sameDhStr = sameRoleDh !== null ? `${sameRoleDh.toFixed(1)}°` : '-';
    const minStr = `${minAccent} (${minDE.toFixed(4)})`;

    console.log(
      `| \`${tokenName}\` | ${oklchStr} | ${roleStr} | ${sameRole || '-'} | ${sameDEStr} | ${sameDhStr} | ${minAccent} | ${minDE.toFixed(4)} | ${status} |`
    );
  }

  console.log('\n### Cross-Role Accents Within 20° Hue (Permitted by Decision)\n');
  if (crossRoleNear.length === 0) {
    console.log('None.');
  } else {
    console.log('| Token | Flowtron Accent | Role of Accent | Hue Diff | dE_ok |');
    console.log('| --- | --- | --- | --- | --- |');
    for (const c of crossRoleNear) {
      console.log(`| \`${c.token}\` | \`${c.accent}\` | ${c.accent} | ${c.dh.toFixed(1)}° | ${c.dist.toFixed(4)} |`);
    }
  }

  // Neutrals check
  console.log('\n### Neutrals Distance vs Flowtron Neutrals (Target: dE_ok >= 0.04)\n');
  const neutralCols = ['Token', 'Our OKLCH', 'Flowtron Token', 'Flowtron Hex', 'dE_ok', 'Status'];
  console.log(`| ${neutralCols.join(' | ')} |`);
  console.log(`| ${neutralCols.map(() => '---').join(' | ')} |`);

  for (const [tokenName, flowtronName] of Object.entries(SAME_ROLE_NEUTRALS)) {
    const t = cssTokens[tokenName];
    if (!t) continue;
    const fHex = FLOWTRON_NEUTRALS[flowtronName];
    const fLab = hexToOklab(fHex);
    const dist = dE(t.lab, fLab);
    const pass = dist >= 0.04;
    if (!pass) allPass = false;
    console.log(
      `| \`${tokenName}\` | ${t.L.toFixed(2)} ${t.C.toFixed(3)} ${Math.round(t.h)}° | \`${flowtronName}\` | \`${fHex}\` | ${dist.toFixed(4)} | ${pass ? 'PASS' : '**FAIL**'} |`
    );
  }

  // Stage Fills Inter-Distance Table
  console.log('\n### Stage Fills Inter-Distance Matrix (Target: Circular dh >= 25° AND dE_ok >= 0.06)\n');
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

  console.log('| Stage A | Stage B | Hue A | Hue B | Circular dh | dE_ok | Status |');
  console.log('| --- | --- | --- | --- | --- | --- | --- |');

  let fillsPass = true;
  for (let i = 0; i < stageTokens.length; i++) {
    for (let j = i + 1; j < stageTokens.length; j++) {
      const a = cssTokens[stageTokens[i]];
      const b = cssTokens[stageTokens[j]];
      const dh = circularHueDiff(a.h, b.h);
      const dist = dE(a.lab, b.lab);
      const pass = dh >= 25 && dist >= 0.06;
      if (!pass) fillsPass = false;
      console.log(
        `| \`${stageTokens[i]}\` | \`${stageTokens[j]}\` | ${Math.round(a.h)}° | ${Math.round(b.h)}° | ${dh.toFixed(1)}° | ${dist.toFixed(4)} | ${pass ? 'PASS' : '**FAIL**'} |`
      );
    }
  }

  console.log(`\nOverall Accent Same-Role Distance: ${allPass ? 'PASS' : 'FAIL'}`);
  console.log(`Overall Stage Fills Separation: ${fillsPass ? 'PASS' : 'FAIL'}`);
  return { allPass, fillsPass };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = await run();
  if (!result.allPass || !result.fillsPass) {
    process.exit(1);
  }
}
