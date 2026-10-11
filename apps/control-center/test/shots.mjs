// Screenshots of the real page for docs/proof/, against the fixed fixture at a fixed time so they are
// reproducible:  npm run shots

import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

import { launch, loadPlaywright, openFixed } from './browser.mjs';
import { startServer } from './dev-server.mjs';

const outDir = fileURLToPath(new URL('../../../docs/proof/', import.meta.url));
const MAX_HEIGHT = 3000;

const SHOTS = [
  ['board', '#/', 'desktop'],
  ['board', '#/', 'mobile'],
  ['ticket', '#/ticket/24', 'desktop'],
  ['cost', '#/cost', 'desktop'],
  ['environments', '#/environments', 'desktop'],
  ['agents', '#/agents', 'desktop'],
  ['escalations', '#/escalations', 'desktop'],
  ['flow', '#/flow', 'desktop'],
  ['trail', '#/trail', 'desktop'],
];
const SIZES = { desktop: [1440, 900], mobile: [390, 844] };

const pw = loadPlaywright();
const browser = pw ? await launch(pw) : null;
if (!browser) {
  console.error('Playwright or Chromium is missing: cd app && npm ci && npx playwright install chromium');
  process.exit(1);
}
const server = await startServer({ fixed: true });
await mkdir(outDir, { recursive: true });
try {
  for (const [name, hash, size] of SHOTS) {
    const [width, height] = SIZES[size];
    const { context, page } = await openFixed(browser, server.url, { hash, width, height });
    await page.waitForTimeout(250);
    const full = await page.evaluate(() => document.documentElement.scrollHeight);
    const file = `${outDir}control-center-${name}-${size}.png`;
    await page.screenshot({ path: file, fullPage: true, clip: { x: 0, y: 0, width, height: Math.min(full, MAX_HEIGHT) } });
    console.log(`wrote ${file} (${width}x${Math.min(full, MAX_HEIGHT)})`);
    await context.close();
  }
} finally {
  await browser.close();
  await server.close();
}
