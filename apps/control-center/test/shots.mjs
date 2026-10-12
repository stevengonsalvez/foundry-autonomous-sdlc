// Screenshots of the real page for docs/proof/, against the fixed fixture at a fixed time so they are
// reproducible:  npm run shots

import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

import { launch, loadPlaywright, openFixed } from './browser.mjs';
import { startServer } from './dev-server.mjs';

const outDir = process.env.SHOTS_OUT_DIR || fileURLToPath(new URL('../../../docs/proof/', import.meta.url));
const MAX_HEIGHT = 3000;

const VIEWS_TO_SHOOT = [
  ['board', '#/'],
  ['ticket', '#/ticket/24'],
  ['cost', '#/cost'],
  ['environments', '#/environments'],
  ['agents', '#/agents'],
  ['escalations', '#/escalations'],
  ['flow', '#/flow'],
  ['trail', '#/trail'],
];
const SIZES = { desktop: [1440, 900], mobile: [360, 800] };
const SCHEMES = ['light', 'dark'];

const pw = loadPlaywright();
const browser = pw ? await launch(pw) : null;
if (!browser) {
  console.error('Playwright or Chromium is missing: cd app && npm ci && npx playwright install chromium');
  process.exit(1);
}
const server = await startServer({ fixed: true });
await mkdir(outDir, { recursive: true });
try {
  for (const scheme of SCHEMES) {
    for (const [sizeName, [width, height]] of Object.entries(SIZES)) {
      for (const [name, hash] of VIEWS_TO_SHOOT) {
        const { context, page } = await openFixed(browser, server.url, { hash, width, height, scheme });
        await page.waitForTimeout(300);
        const full = await page.evaluate(() => document.documentElement.scrollHeight);
        const file = `${outDir}control-center-${name}-${sizeName}-${scheme}.png`;
        await page.screenshot({ path: file, fullPage: true, clip: { x: 0, y: 0, width, height: Math.min(full, MAX_HEIGHT) } });
        console.log(`wrote ${file} (${width}x${Math.min(full, MAX_HEIGHT)} ${scheme})`);
        // Also write legacy filename for light mode for backwards compatibility
        if (scheme === 'light' && (sizeName === 'desktop' || name === 'board')) {
          const legacyFile = `${outDir}control-center-${name}-${sizeName}.png`;
          await page.screenshot({ path: legacyFile, fullPage: true, clip: { x: 0, y: 0, width, height: Math.min(full, MAX_HEIGHT) } });
        }
        await context.close();
      }
    }
  }
} finally {
  await browser.close();
  await server.close();
}
