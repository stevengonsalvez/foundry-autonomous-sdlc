// Screenshots of the real page for docs/proof/, against the fixed fixture at a fixed time so they are
// reproducible:  npm run shots

import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { launch, loadPlaywright, openFixed } from './browser.mjs';
import { startServer } from './dev-server.mjs';

const outDir = process.env.SHOTS_OUT_DIR
  ? resolve(process.env.SHOTS_OUT_DIR).replace(/\/?$/, '/')
  : fileURLToPath(new URL('../docs/proof/', import.meta.url));
const MAX_HEIGHT = 3000;

const VIEWS_TO_SHOOT = [
  ['ticket', '#/ticket/24'],
  ['cost', '#/cost'],
  ['environments', '#/environments'],
  ['agents', '#/agents'],
  ['escalations', '#/escalations'],
  ['flow', '#/flow'],
  ['trail', '#/trail'],
];

const SIZES = {
  desktop: [1440, 900],
  '1280': [1280, 800],
  mobile: [390, 844],
  '360': [360, 640],
};

const pw = loadPlaywright();
const browser = pw ? await launch(pw) : null;
if (!browser) {
  console.error('Playwright or Chromium is missing: cd app && npm ci && npx playwright install chromium');
  process.exit(1);
}
const server = await startServer({ fixed: true });
await mkdir(outDir, { recursive: true });

async function snap(page, file, width) {
  await page.waitForTimeout(250);
  const full = await page.evaluate(() => document.documentElement.scrollHeight);
  const height = Math.min(full, MAX_HEIGHT);
  await page.screenshot({ path: file, fullPage: true, clip: { x: 0, y: 0, width, height } });
  console.log(`wrote ${file} (${width}x${height})`);
}

try {
  // 1. Board across lenses: Delivery, Cost, Gates at desktop, 1280, mobile, and 360
  for (const size of ['desktop', '1280', 'mobile', '360']) {
    const [width, height] = SIZES[size];
    const { context, page } = await openFixed(browser, server.url, { hash: '#/', width, height });

    // Delivery lens (default)
    await snap(page, `${outDir}control-center-board-${size}.png`, width);
    await snap(page, `${outDir}control-center-board-delivery-${size}.png`, width);

    // Cost lens
    const costBtn = page.getByRole('button', { name: 'Cost' });
    if (await costBtn.count()) {
      await costBtn.first().click();
      await page.waitForTimeout(150);
      await snap(page, `${outDir}control-center-board-cost-${size}.png`, width);
    }

    // Gates lens
    const gatesBtn = page.getByRole('button', { name: 'Gates' });
    if (await gatesBtn.count()) {
      await gatesBtn.first().click();
      await page.waitForTimeout(150);
      await snap(page, `${outDir}control-center-board-gates-${size}.png`, width);
    }

    // Agent group
    const agentBtn = page.getByRole('button', { name: 'Agent' });
    if (await agentBtn.count()) {
      await agentBtn.first().click();
      await page.waitForTimeout(150);
      await snap(page, `${outDir}control-center-board-group-agent-${size}.png`, width);
    }

    // Outcome group
    const outcomeBtn = page.getByRole('button', { name: 'Outcome' });
    if (await outcomeBtn.count()) {
      await outcomeBtn.first().click();
      await page.waitForTimeout(150);
      await snap(page, `${outDir}control-center-board-group-outcome-${size}.png`, width);
    }

    await context.close();
  }

  // 2. All other views at desktop and 360
  for (const [name, hash] of VIEWS_TO_SHOOT) {
    for (const size of ['desktop', '360']) {
      const [width, height] = SIZES[size];
      const { context, page } = await openFixed(browser, server.url, { hash, width, height });
      await snap(page, `${outDir}control-center-${name}-${size}.png`, width);
      await context.close();
    }
  }
} finally {
  await browser.close();
  await server.close();
}
