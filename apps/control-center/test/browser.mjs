// Finds Playwright in the app workspace (app/node_modules, installed with `cd app && npm ci`) so this
// package needs no dependencies of its own.

import { createRequire } from 'node:module';

const requireFromApp = createRequire(new URL('../../../app/package.json', import.meta.url));

export function loadPlaywright() {
  try {
    return { chromium: requireFromApp('@playwright/test').chromium, AxeBuilder: loadAxe() };
  } catch {
    return null;
  }
}

function loadAxe() {
  try {
    const mod = requireFromApp('@axe-core/playwright');
    return mod.default ?? mod.AxeBuilder ?? mod;
  } catch {
    return null;
  }
}

/** Launch Chromium, or return null when the browser is not installed (`npx playwright install chromium`). */
export async function launch(pw) {
  try {
    return await pw.chromium.launch();
  } catch {
    return null;
  }
}

export const VIEWS = Object.freeze([
  ['board', '#/'],
  ['ticket', '#/ticket/24'],
  ['cost', '#/cost'],
  ['environments', '#/environments'],
  ['agents', '#/agents'],
  ['escalations', '#/escalations'],
  ['flow', '#/flow'],
  ['trail', '#/trail'],
]);

/** The time the fixed fixture is "now": two minutes after the sample was generated. */
export const FIXED_NOW = '2026-10-11T20:07:00Z';

export async function openFixed(browser, base, { hash = '#/', width = 1440, height = 900, scheme = 'light', query = '?data=state.json', reducedMotion = 'no-preference' } = {}) {
  const context = await browser.newContext({ viewport: { width, height }, colorScheme: scheme, reducedMotion });
  const page = await context.newPage();
  await page.clock.install({ time: new Date(FIXED_NOW) });
  await page.goto(`${base}${query}${hash}`);
  await page.waitForSelector('#app[aria-busy="false"] .view');
  return { context, page };
}
