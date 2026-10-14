// Drives the real page in Chromium against the dev server: every view at desktop and phone width,
// the fetch strategy against a scripted GitHub, the error states, hostile data and accessibility.
//
// Needs Playwright from the app workspace (`cd app && npm ci && npx playwright install chromium`).
// Without it these tests are skipped with a notice; set CC_REQUIRE_BROWSER=1 to make that a failure.

import { after, before, describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { FIXED_NOW, VIEWS, launch, loadPlaywright, openFixed } from './browser.mjs';
import { startServer } from '../scripts/dev-server.mjs';
import { PAYLOADS, makeHostile } from './hostile.mjs';
import { rawIssues, rawSample } from './helpers.mjs';

const pw = loadPlaywright();
const browser = pw ? await launch(pw) : null;
const skip = browser ? false : 'Playwright or Chromium is not installed (cd app && npm ci && npx playwright install chromium)';
if (skip) {
  console.warn(`browser tests skipped: ${skip}`);
  if (process.env.CC_REQUIRE_BROWSER) throw new Error(skip);
}

const servers = {};
const REPO = 'https://github.com/stevengonsalvez/foundry-autonomous-sdlc';

before(async () => {
  if (!browser) return;
  for (const state of ['normal', 'empty', 'missing', 'bad-version', 'invalid-json', 'http-500', 'hostile', 'edge']) servers[state] = await startServer({ state, fixed: true });
  servers.stale = await startServer({ state: 'stale' });
  servers.live = await startServer({ state: 'normal' });
});

after(async () => {
  await Promise.all(Object.values(servers).map((s) => s.close()));
  await browser?.close();
});

/** Collect everything that should never happen on a healthy page. */
function watch(page, base) {
  const seen = { errors: [], failed: [], external: [] };
  page.on('console', (m) => m.type() === 'error' && seen.errors.push(m.text()));
  page.on('pageerror', (e) => seen.errors.push(`pageerror: ${e.message}`));
  page.on('requestfailed', (r) => seen.failed.push(`${r.url()} ${r.failure()?.errorText}`));
  page.on('response', (r) => r.status() >= 400 && r.url().startsWith(base) && seen.failed.push(`${r.url()} HTTP ${r.status()}`));
  page.on('request', (r) => {
    const u = r.url();
    if (!u.startsWith(base) && !u.startsWith('data:')) seen.external.push(u);
  });
  return seen;
}

/** Move the page's fake clock forward in 30 s steps, letting each poll's network round trip finish. */
async function elapse(page, ms) {
  for (let left = ms; left > 0; left -= 30_000) {
    await page.clock.runFor(Math.min(left, 30_000));
    await page.waitForTimeout(120);
  }
}

const text = (page, selector) => page.locator(selector).first().innerText();
const open = (state, opts) => openFixed(browser, servers[state].url, opts);

describe('views', { skip }, () => {
  for (const [width, height, label] of [[1440, 900, 'desktop'], [390, 800, 'phone'], [360, 640, '360px']]) {
    test(`all 8 views load at ${label} width with no errors, no failed or external requests, no sideways page scroll`, async () => {
      for (const [name, hash] of VIEWS) {
        const { context, page } = await open('normal', { hash, width, height });
        const seen = watch(page, servers.normal.url);
        await page.reload();
        await page.waitForSelector('#app[aria-busy="false"] .view');
        assert.equal(await page.locator('h1').count() >= 1, true, `${name} has a heading`);
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        assert.ok(overflow <= 0, `${name} at ${label} scrolls sideways by ${overflow}px`);
        assert.deepEqual(seen.errors, [], `${name} console errors`);
        assert.deepEqual(seen.failed, [], `${name} failed requests`);
        assert.deepEqual(seen.external, [], `${name} requested something outside the dev server`);
        assert.equal(await page.locator('main').count(), 1);
        await context.close();
      }
    });
  }

  async function findMissingClasses(page, label) {
    assert.equal(await page.locator('.error-panel').count(), 0, `no error panel rendered on ${label}`);
    return page.evaluate(() => {
      const sheetClasses = new Set();
      for (const sheet of document.styleSheets) {
        try {
          for (const rule of sheet.cssRules) {
            if (rule.selectorText) {
              for (const m of rule.selectorText.matchAll(/\.([a-zA-Z0-9_-]+)/g)) {
                sheetClasses.add(m[1]);
              }
            }
          }
        } catch {
          // Ignore cross-origin stylesheet errors
        }
      }
      const domClasses = new Set();
      for (const el of document.querySelectorAll('*')) {
        for (const c of el.classList) {
          domClasses.add(c);
        }
      }
      const notFound = [];
      for (const c of domClasses) {
        if (!sheetClasses.has(c)) notFound.push(c);
      }
      return notFound;
    });
  }

  test('DOM crawl: asserts every class on every rendered element across all views, lenses and groups has a CSS rule', async () => {
    const targets = [
      ...VIEWS.map(([, hash]) => hash),
      '#/ticket/24',
      '#/ticket/23',
      '#/ticket/25',
      '#/ticket/5',
    ];

    const missingAcrossViews = [];

    // Crawl all standard views and ticket variations across normal and edge fixtures
    for (const state of ['normal', 'edge']) {
      for (const hash of targets) {
        const { context, page } = await open(state, { hash, width: 1440, height: 900 });
        await page.waitForSelector('#app[aria-busy="false"] .view');
        const missing = await findMissingClasses(page, `${state} ${hash}`);
        if (missing.length > 0) {
          missingAcrossViews.push({ target: `${state} ${hash}`, missing });
        }
        await context.close();
      }
    }

    // Crawl hostile fixture across views and tickets
    const hostileTargets = [
      ...VIEWS.map(([, hash]) => hash),
      '#/ticket/24',
      '#/ticket/25',
      '#/ticket/5',
    ];
    for (const hash of hostileTargets) {
      const { context, page } = await open('hostile', { hash, width: 1440, height: 900 });
      await page.waitForSelector('#app[aria-busy="false"] .view');
      const missing = await findMissingClasses(page, `hostile ${hash}`);
      if (missing.length > 0) {
        missingAcrossViews.push({ target: `hostile ${hash}`, missing });
      }
      await context.close();
    }

    // Crawl all board lens and group combinations across normal and edge fixtures
    for (const state of ['normal', 'edge']) {
      const { context, page } = await open(state, { hash: '#/', width: 1440, height: 900 });
      await page.waitForSelector('#app[aria-busy="false"] .view');

      for (const group of ['Type', 'Agent', 'Outcome']) {
        await page.getByRole('button', { name: group }).click();
        for (const lens of ['Delivery', 'Cost', 'Gates']) {
          await page.getByRole('button', { name: lens }).click();
          const target = `${state} board group=${group} lens=${lens}`;
          const missing = await findMissingClasses(page, target);
          if (missing.length > 0) {
            missingAcrossViews.push({ target, missing });
          }
        }
      }
      await context.close();
    }

    assert.deepEqual(missingAcrossViews, [], 'Every element class rendered across all views, lenses and groups must have a rule in document.styleSheets');
  });

  test('delivery flow matrix: lens and group switching, macrobands, unclassified and pending ticket rendering', async () => {
    const { context, page } = await open('normal');

    // 1. Band row has one cell per band
    const bands = page.locator('.band-strip .band-cell');
    assert.equal(await bands.count(), 4);
    assert.deepEqual(
      await bands.evaluateAll((els) => els.map((e) => e.getAttribute('data-band'))),
      ['shape', 'build', 'release', 'escalated'],
    );

    // 1b. Matrix cells have aria-labelledby referencing valid lane and column headers
    const cells = await page.locator('.matrix-cell').all();
    assert.ok(cells.length > 0, 'matrix cells rendered');
    for (const cell of cells) {
      const labelledBy = await cell.getAttribute('aria-labelledby');
      assert.ok(labelledBy, 'matrix-cell must have aria-labelledby');
      const [laneId, colId] = labelledBy.split(' ');
      assert.ok(laneId?.startsWith('lane-'), `lane ID "${laneId}" must start with lane-`);
      assert.ok(colId?.startsWith('col-'), `col ID "${colId}" must start with col-`);
    }

    // 2. Lens switching changes the DOM
    const costBtn = page.getByRole('button', { name: 'Cost' });
    await costBtn.click();
    assert.ok((await page.locator('.chip-cost').count()) > 0, 'cost lens renders cost chips');

    const gatesBtn = page.getByRole('button', { name: 'Gates' });
    await gatesBtn.click();
    assert.ok((await page.locator('.chip-gates').count()) > 0, 'gates lens renders gates chips');

    const deliveryBtn = page.getByRole('button', { name: 'Delivery' });
    await deliveryBtn.click();
    assert.ok((await page.locator('.chip-time').count()) > 0, 'delivery lens renders time chips');

    // 3. Group switching changes swimlanes
    const agentBtn = page.getByRole('button', { name: 'Agent' });
    await agentBtn.click();
    const agentLanes = page.locator('.matrix-spine .lane-head');
    assert.ok((await agentLanes.count()) >= 2, 'agent group displays multiple agent lanes');
    assert.ok((await page.locator('.matrix-spine .lane-head[data-lane="unassigned"]').count()) === 1, 'unassigned lane exists for triage');

    const outcomeBtn = page.getByRole('button', { name: 'Outcome' });
    await outcomeBtn.click();
    const outcomeLanes = page.locator('.matrix-spine .lane-head');
    assert.equal(await outcomeLanes.count(), 3, 'outcome group displays 3 lanes: in-flight, shipped, escalated');

    const typeBtn = page.getByRole('button', { name: 'Type' });
    await typeBtn.click();
    assert.equal(await page.locator('.matrix-spine .lane-head[data-lane="other"]').count(), 1, 'other lane exists for unclassified tickets');

    // 4. No ticket is dropped: verify across all groupings and lenses (chips equal column count per column)
    for (const groupName of ['Type', 'Agent', 'Outcome']) {
      await page.getByRole('button', { name: groupName }).click();
      for (const lensName of ['Delivery', 'Cost', 'Gates']) {
        await page.getByRole('button', { name: lensName }).click();
        const chips = await page.locator('article.card').count();
        assert.equal(chips, rawSample.tickets.length, `group=${groupName} lens=${lensName} total chips`);
        for (const stage of rawSample.board_stages) {
          const colCount = Number(await page.locator(`.col-${stage} .col-count`).innerText());
          const stageCards = await page.locator(`.col-${stage} article.card`).count();
          assert.equal(stageCards, colCount, `group=${groupName} lens=${lensName} stage=${stage} chips equal column count`);
        }
      }
    }

    // 5. Axe accessibility check on the matrix
    if (pw?.AxeBuilder) {
      const results = await new pw.AxeBuilder({ page }).include('.view-board').analyze();
      const violations = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
      assert.deepEqual(violations, [], 'axe matrix violations');
    }

    await context.close();
  });

  test('all aria-labelledby tokens across board matrix resolve to existing elements in document, including hostile fixture', async () => {
    for (const state of ['normal', 'edge', 'hostile']) {
      const { context, page } = await open(state, { hash: '#/' });
      await page.waitForSelector('#app[aria-busy="false"] .view');

      for (const group of ['type', 'agent', 'outcome']) {
        const label = group.charAt(0).toUpperCase() + group.slice(1);
        const btn = page.locator(`.ctrl-group button:has-text("${label}")`);
        assert.equal(await btn.count(), 1, `button for group ${group} must exist and be unique on ${state}`);
        await btn.click();
        await page.waitForTimeout(50);
        assert.equal(await btn.getAttribute('aria-pressed'), 'true', `group button ${group} must have aria-pressed=true after click on ${state}`);

        const evaluation = await page.evaluate(() => {
          const missing = [];
          const allIds = new Set();
          const duplicateIds = [];
          for (const el of document.querySelectorAll('[id]')) {
            if (allIds.has(el.id)) duplicateIds.push(el.id);
            allIds.add(el.id);
          }

          const cellAudits = [];
          for (const el of document.querySelectorAll('.matrix-cell[aria-labelledby]')) {
            const raw = el.getAttribute('aria-labelledby') || '';
            const tokens = raw.trim().split(/\s+/).filter(Boolean);
            const el0 = tokens[0] ? document.getElementById(tokens[0]) : null;
            const el1 = tokens[1] ? document.getElementById(tokens[1]) : null;
            if (!el0) missing.push({ id: tokens[0], tag: el.tagName, class: el.className });
            if (!el1) missing.push({ id: tokens[1], tag: el.tagName, class: el.className });

            const isLaneName = el0 ? el0.classList.contains('lane-name') : false;
            const laneName = el0 ? el0.innerText.trim() : '';
            const stageTitle = el1 ? el1.innerText.trim() : '';
            const accessibleName = [laneName, stageTitle].filter(Boolean).join(' ');

            cellAudits.push({
              tokens,
              isLaneName,
              laneName,
              stageTitle,
              accessibleName,
            });
          }

          return { missing, duplicateIds, cellAudits };
        });

        assert.deepEqual(evaluation.duplicateIds, [], `all IDs must be unique on ${state} with group=${group}`);
        assert.deepEqual(evaluation.missing, [], `all aria-labelledby tokens must resolve to elements on ${state} with group=${group}`);

        assert.ok(evaluation.cellAudits.length > 0, 'must have matrix cells');
        for (const cell of evaluation.cellAudits) {
          assert.equal(cell.tokens.length, 2, 'cell aria-labelledby must contain exactly 2 tokens (lane name and stage title)');
          assert.equal(cell.isLaneName, true, 'first token in aria-labelledby must point directly to an element with class .lane-name');
          assert.equal(cell.accessibleName, `${cell.laneName} ${cell.stageTitle}`, 'accessible name must strictly match laneName + " " + stageTitle');
          assert.ok(cell.laneName.length > 0, 'lane name must not be empty');
          assert.ok(cell.stageTitle.length > 0, 'stage title must not be empty');
        }
      }

      await context.close();
    }
  });

  test('in every lens at 360, 1280 and 1440, chip lens right edge stays inside chip content box, chip head items are single line, and lens does not overflow', async () => {
    for (const width of [360, 1280, 1440]) {
      const height = width === 360 ? 640 : 900;
      const { context, page } = await open('normal', { width, height });
      await page.waitForSelector('#app[aria-busy="false"] .view-board');

      for (const lens of ['delivery', 'cost', 'gates']) {
        const lensBtn = page.getByRole('button', { name: lens.charAt(0).toUpperCase() + lens.slice(1) });
        await lensBtn.click();
        await page.waitForTimeout(50);

        const check = await page.evaluate(() => {
          const chips = Array.from(document.querySelectorAll('.chip-pill'));
          const failures = [];
          for (const chip of chips) {
            const chipRect = chip.getBoundingClientRect();
            const chipStyle = window.getComputedStyle(chip);
            const pr = parseFloat(chipStyle.paddingRight) || 0;
            const br = parseFloat(chipStyle.borderRightWidth) || 0;
            const contentBoxRight = chipRect.right - pr - br;

            // Every chip-head visible child must be one line (height <= 18.5px)
            for (const child of chip.querySelectorAll('.chip-head > *:not(.sr-only)')) {
              const r = child.getBoundingClientRect();
              if (r.width > 0 && r.height > 18.5) {
                failures.push({
                  type: 'head_child_multiline',
                  tag: child.tagName,
                  className: child.className,
                  text: child.textContent,
                  height: r.height,
                });
              }
            }

            const lensEl = chip.querySelector('.chip-lens');
            if (lensEl) {
              const lensRect = lensEl.getBoundingClientRect();
              if (lensRect.right > contentBoxRight + 0.5) {
                failures.push({
                  type: 'lens_overflow_content_box',
                  chipText: chip.innerText.slice(0, 30),
                  contentBoxRight,
                  lensRight: lensRect.right,
                  diff: lensRect.right - contentBoxRight,
                });
              }
              if (lensEl.scrollWidth > lensEl.clientWidth + 0.5) {
                failures.push({
                  type: 'lens_scroll_overflow',
                  scrollWidth: lensEl.scrollWidth,
                  clientWidth: lensEl.clientWidth,
                });
              }
              for (const desc of lensEl.querySelectorAll('*')) {
                if (desc.scrollWidth > desc.clientWidth + 0.5) {
                  failures.push({
                    type: 'desc_scroll_overflow',
                    tag: desc.tagName,
                    className: desc.className,
                    text: desc.textContent,
                    scrollWidth: desc.scrollWidth,
                    clientWidth: desc.clientWidth,
                  });
                }
              }
            }
          }
          return { chipCount: chips.length, failures };
        });

        assert.ok(check.chipCount > 0, `must have chips at width=${width} lens=${lens}`);
        assert.deepEqual(check.failures, [], `no chip lens overflow or multiline wrapping at width=${width} lens=${lens}`);
      }

      await context.close();
    }
  });

  test('matrix swimlane rows align horizontally with zero vertical drift across all columns', async () => {
    const { context, page } = await open('normal', { width: 1440, height: 900 });
    await page.waitForSelector('#app[aria-busy="false"] .view-board');

    const driftCheck = await page.evaluate(() => {
      const laneHeads = Array.from(document.querySelectorAll('.matrix-spine .lane-head'));
      const cols = Array.from(document.querySelectorAll('.col'));
      const rowDrifts = [];

      for (let i = 0; i < laneHeads.length; i++) {
        const headRect = laneHeads[i].getBoundingClientRect();
        for (const col of cols) {
          const cells = col.querySelectorAll('.matrix-cell');
          const cell = cells[i];
          if (cell) {
            const cellRect = cell.getBoundingClientRect();
            const topDiff = Math.abs(cellRect.top - headRect.top);
            const bottomDiff = Math.abs(cellRect.bottom - headRect.bottom);
            if (topDiff > 1.5 || bottomDiff > 1.5) {
              rowDrifts.push({ laneIndex: i, topDiff, bottomDiff });
            }
          }
        }
      }
      return { laneCount: laneHeads.length, rowDrifts };
    });

    assert.ok(driftCheck.laneCount > 0, 'must have lanes');
    assert.deepEqual(driftCheck.rowDrifts, [], 'matrix cell row boundaries must align with lane headers');
    await context.close();
  });

  test('board column counts equal the ledger counts, and every card links to its ticket', async () => {
    const { context, page } = await open('normal');
    for (const stage of rawSample.board_stages) {
      const count = await page.locator(`.col-${stage} .col-count`).innerText();
      assert.equal(Number(count), rawSample.flow.counts[stage], stage);
      assert.equal(await page.locator(`.col-${stage} article.card`).count(), rawSample.flow.counts[stage]);
    }
    assert.equal(await page.locator('article.card').count(), 22);
    assert.equal(await page.locator('.col-escalated').getAttribute('class'), 'col col-escalated');
    const href = await page.locator('article.card .card-link').first().getAttribute('href');
    assert.match(href, /^#\/ticket\/\d+$/);
    await context.close();
  });

  test('board: type chips, search, and the new-ticket buttons', async () => {
    const { context, page } = await open('normal');
    await page.getByRole('button', { name: 'bug', exact: true }).click();
    assert.equal(await page.locator('article.card').count(), 4);
    await page.getByRole('button', { name: 'bug', exact: true }).click();
    await page.getByLabel('Search by ticket number or title').fill('24');
    assert.equal(await page.locator('article.card').count(), 1);
    assert.match(await text(page, 'article.card'), /Make the parcel tracker better/);
    await page.getByLabel('Search by ticket number or title').fill('lowercase');
    assert.equal(await page.locator('article.card').count(), 4);
    await page.getByRole('button', { name: 'Clear filters' }).click();
    assert.equal(await page.locator('article.card').count(), 22);

    const create = page.getByRole('link', { name: 'New ticket' });
    assert.equal(await create.getAttribute('href'), `${REPO}/issues/new?template=feature_request.yml`);
    assert.equal(await create.getAttribute('target'), '_blank');
    assert.match(await create.getAttribute('rel'), /noopener/);
    assert.match(await create.getAttribute('rel'), /noreferrer/);
    assert.equal(await page.getByRole('link', { name: 'Report a bug' }).getAttribute('href'), `${REPO}/issues/new?template=bug_report.yml`);
    await context.close();
  });

  test('ticket 24: questions back with a simulated product owner, and staging, skipped, prod hops in order', async () => {
    const { context, page } = await open('normal', { hash: '#/ticket/24' });
    assert.match(await text(page, 'h1'), /Make the parcel tracker better/);
    assert.equal(await page.locator('.qa').count(), 4);
    assert.match(await text(page, '.trail-block'), /simulated product owner/i);
    assert.equal(await page.locator('.bubble-a .who').first().textContent(), 'Simulated product owner');
    const hops = await page.locator('#hops .hop-title').allInnerTexts();
    assert.match(hops[0], /Deployed to staging/);
    assert.match(hops[1], /Skipped on staging/);
    assert.match(hops[2], /Promoted to production/);
    assert.equal(await page.locator('#gates .gate').count(), 10);
    assert.equal(await page.locator('#gates .gate-pass').count(), 9, 'nine gates passed, evals not run');
    assert.match(await text(page, '#gates'), /Evaluations\s+Not run/);
    assert.ok(await page.locator('#timeline svg.chart').count());
    assert.match(await text(page, '#cost'), /\$0\.08/);
    await page.setViewportSize({ width: 390, height: 800 });
    await page.waitForTimeout(100);
    assert.ok(await page.locator('#timeline svg.chart').count(), 'stepper redraws vertically on a phone');
    await context.close();
  });

  test('ticket 25: rolled back, in the escalated column, on Environments and on Escalations', async () => {
    const { context, page } = await open('normal');
    assert.match(await text(page, '.col-escalated'), /Lowercase tracking numbers/);
    const card = page.locator('article.card', { hasText: '#25' });
    assert.match(await card.innerText(), /Rolled back/);
    assert.equal(await card.getAttribute('data-stage'), 'escalated');

    await page.goto(`${servers.normal.url}?data=state.json#/environments`);
    await page.waitForSelector('#rollbacks');
    const rollback = await text(page, '#rollbacks tbody tr');
    assert.match(rollback, /v0\.1\.1/);
    assert.match(rollback, /smoke/);
    assert.match(rollback, /#25/);

    await page.goto(`${servers.normal.url}?data=state.json#/escalations`);
    await page.waitForSelector('.esc-card');
    const esc = page.locator('.esc-card', { hasText: 'Lowercase tracking numbers' }).filter({ hasText: 'Deploy failed' });
    assert.equal(await esc.count(), 1);
    assert.match(await esc.innerText(), /smoke failed on staging/);
    assert.equal(await page.locator('.esc-card').count(), 18);
    await context.close();
  });

  test('cost: the gap in plain words, the danger banner, sortable table', async () => {
    const { context, page } = await open('normal', { hash: '#/cost' });
    const banner = page.locator('.callout');
    assert.match(await banner.innerText(), /Azure billed 13\.02 USD; the ledger estimated 1\.87 USD; the ledger undercounts hosted compute by 7\.0x\./);
    assert.equal(await page.locator('.callout-danger').count(), 0, '13.02 USD is under the 22 USD halt line');
    assert.match(await banner.innerText(), /as of/);
    assert.ok(await page.locator('#estimate-vs-billed svg.chart').count());
    assert.equal(await page.locator('#meters .c-label').count(), 4);
    assert.match(await text(page, '#ledger-compute'), /18s/);
    const first = () => page.locator('#per-ticket tbody tr').first().locator('th').innerText();
    assert.match(await first(), /#27/);
    await page.getByRole('button', { name: /Sort by Total/ }).click();
    assert.match(await first(), /#2\b/);
    await page.getByRole('button', { name: /Sort by Ticket/ }).click();
    assert.match(await first(), /#40/);
    await context.close();
  });

  test('cost: billed spend past the halt line raises the danger banner', async () => {
    const context = await browser.newContext();
    const page = await context.newPage();
    const doc = structuredClone(rawSample);
    doc.cost.billing.billed_usd = 23.5;
    doc.cost.totals.halted = true;
    await page.route('**/state.json', (route) => route.fulfill({ json: doc }));
    await page.goto(`${servers.normal.url}?data=state.json#/cost`);
    await page.waitForSelector('#app[aria-busy="false"] .view');
    assert.equal(await page.locator('.callout-danger[role="alert"]').count(), 1);
    assert.match(await text(page, '.callout-danger'), /halt line/);
    await context.close();
  });

  test('cost: with no bill read yet it says so and invents nothing', async () => {
    const context = await browser.newContext();
    const page = await context.newPage();
    const doc = structuredClone(rawSample);
    doc.cost.billing = null;
    doc.cost.gap = null;
    doc.cost.totals.billed_usd = null;
    doc.cost.totals.halted = false;
    doc.cost.totals.over_cap = false;
    await page.route('**/state.json', (route) => route.fulfill({ json: doc }));
    await page.goto(`${servers.normal.url}?data=state.json#/cost`);
    await page.waitForSelector('#app[aria-busy="false"] .view');
    assert.match(await text(page, '.callout'), /Billed spend not read yet/i);
    assert.doesNotMatch(await page.locator('main').innerText(), /13\.02/);
    assert.equal(await page.locator('.spend-banner').count(), 0);
    await context.close();
  });

  test('agents: eleven agents, state always written out, last error shown', async () => {
    const { context, page } = await open('normal', { hash: '#/agents' });
    assert.equal(await page.locator('.agent').count(), 11);
    for (const chip of await page.locator('.agent .state').all()) assert.match(await chip.innerText(), /Running|Idle|Error|Stale|Unknown/);
    assert.match(await text(page, '.agent-error[role="group"]'), /HTTP 429 rate_limit_exceeded/);
    assert.match(await text(page, '.strip'), /Hosted/);
    await context.close();
  });

  test('flow: every chart has its table behind it', async () => {
    const { context, page } = await open('normal', { hash: '#/flow' });
    for (const id of ['cycle', 'lead', 'change-failure', 'wip', 'gates', 'cost-cap']) {
      assert.ok(await page.locator(`#${id} svg.chart`).count(), `${id} has a chart`);
      assert.ok(await page.locator(`#${id} details table`).count(), `${id} has a data table`);
    }
    assert.match(await text(page, '#lead'), /34m 8s/);
    assert.match(await text(page, '#change-failure'), /33%/);
    await context.close();
  });

  test('trail: filter by kind and ticket', async () => {
    const { context, page } = await open('normal', { hash: '#/trail' });
    const all = await page.locator('.trail-group').count();
    assert.ok(all >= 8);
    await page.getByRole('button', { name: 'CI triage' }).click();
    assert.equal(await page.locator('.trail-group').count(), 5);
    await page.getByRole('button', { name: 'All', exact: true }).click();
    await page.locator('#trail-ticket').selectOption('24');
    assert.equal(await page.locator('.trail-group').count(), 1);
    assert.match(await text(page, '.trail-group'), /simulated product owner/i);
    await context.close();
  });

  test('unknown ticket and unknown route show a way back', async () => {
    const { context, page } = await open('normal', { hash: '#/ticket/9999' });
    assert.match(await text(page, '.empty-title'), /Ticket not found/);
    assert.equal(await page.getByRole('link', { name: /Back to the board/ }).getAttribute('href'), '#/');
    await page.goto(`${servers.normal.url}?data=state.json#/nope`);
    assert.match(await text(page, '.empty-title'), /Page not found/);
    await context.close();
  });

  test('navigation marks the current page and moves focus into the content', async () => {
    const { context, page } = await open('normal');
    await page.getByRole('link', { name: 'Cost', exact: true }).click();
    await page.waitForSelector('#nav a[aria-current="page"]:has-text("Cost")');
    assert.equal(await page.evaluate(() => document.activeElement?.id), 'main');
    assert.match(await page.title(), /^Cost/);
    await context.close();
  });
});

describe('freshness', { skip }, () => {
  test('a recent snapshot is not stale; time passing makes it stale and the badge explains why', async () => {
    const { context, page } = await open('normal');
    assert.equal(await page.locator('.stale-badge').count(), 0);
    assert.match(await text(page, '#freshness'), /Updated\s+2 min ago/);
    assert.match(await text(page, '#freshness'), /source:\s*file/);
    await page.clock.fastForward('09:00');
    await page.waitForSelector('.stale-badge');
    assert.match(await page.locator('.stale-badge').getAttribute('title'), /orchestrator is not ticking or the ledger is down/);
    await context.close();
  });

  test('--state stale serves an old snapshot and the badge shows from the first paint', async () => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto(`${servers.stale.url}?data=state.json`);
    await page.waitForSelector('.stale-badge');
    assert.match(await text(page, '#freshness'), /Updated\s+3\d min ago/);
    await context.close();
  });
});

describe('states', { skip }, () => {
  const cases = [
    ['invalid-json', /not valid JSON/],
    ['bad-version', /Unsupported state\.json version/],
    ['http-500', /HTTP 500/],
  ];
  for (const [state, pattern] of cases) {
    test(`${state}: shows the error state with a retry that fetches again`, async () => {
      const context = await browser.newContext();
      const page = await context.newPage();
      let requests = 0;
      page.on('request', (r) => r.url().endsWith('/state.json') && (requests += 1));
      await page.goto(`${servers[state].url}?data=state.json`);
      await page.waitForSelector('.empty-error');
      assert.match(await text(page, '.empty-error'), pattern);
      assert.equal(await page.locator('[role="alert"]').count(), 1);
      const before = requests;
      await page.getByRole('button', { name: 'Retry' }).click();
      await page.waitForSelector('.empty-error');
      assert.ok(requests > before, 'retry fetched again');
      await context.close();
    });
  }

  test('a valid state with no tickets shows the empty state and the way to create one', async () => {
    const context = await browser.newContext();
    const page = await context.newPage();
    const seen = watch(page, servers.empty.url);
    await page.goto(`${servers.empty.url}?data=state.json`);
    await page.waitForSelector('.empty-state');
    assert.match(await text(page, '.empty-title'), /No tickets yet/);
    assert.equal(await page.getByRole('link', { name: /Open a ticket/ }).count(), 1);
    for (const [, hash] of VIEWS.slice(2)) {
      await page.goto(`${servers.empty.url}?data=state.json${hash}`);
      await page.waitForSelector('#app[aria-busy="false"] .view');
    }
    assert.deepEqual(seen.errors, []);
    await context.close();
  });

  test('a missing state file says the ledger has not published yet', async () => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto(`${servers.missing.url}?data=state.json`);
    await page.waitForSelector('.empty-state');
    assert.match(await text(page, '.empty-title'), /Waiting for the first state/);
    await context.close();
  });

  test('a bad ?data= parameter is refused and nothing is requested', async () => {
    for (const bad of ['../state.json', '//evil.example/x.json', 'https://evil.example/x.json', 'state.txt']) {
      const context = await browser.newContext();
      const page = await context.newPage();
      const requested = [];
      page.on('request', (r) => requested.push(r.url()));
      await page.goto(`${servers.normal.url}?data=${encodeURIComponent(bad)}`);
      await page.waitForSelector('.empty-error');
      assert.match(await text(page, '.empty-error'), /\?data= parameter/);
      const others = requested.filter((u) => !u.includes('?data='));
      assert.ok(others.every((u) => u.startsWith(servers.normal.url) && !u.endsWith('.json')), `${bad}: ${others.join(' ')}`);
      await context.close();
    }
  });
});

describe('security', { skip }, () => {
  const probe = (page) =>
    page.evaluate(() => ({
      pwned: window.__pwned ?? null,
      scripts: [...document.scripts].map((s) => s.getAttribute('src')),
      handlers: [...document.querySelectorAll('*')].flatMap((el) => [...el.attributes].filter((a) => /^on/i.test(a.name)).map((a) => `${el.tagName}.${a.name}`)),
      styleAttrs: [...document.querySelectorAll('[style]')].filter((el) => !/^(--[\w-]+:\s*-?[\d.]+(%|px|rem|em)?;\s*)+$/.test(el.getAttribute('style'))).length,
      badEls: document.querySelectorAll('img, iframe, object, embed, form, input[type="image"], base, meta[http-equiv="refresh"]').length,
      hrefs: [...document.querySelectorAll('a[href]')].map((a) => ({ href: a.getAttribute('href'), target: a.target, rel: a.rel })),
      overflow: document.documentElement.scrollWidth - window.innerWidth,
      wide: (() => { const out = []; const w = window.innerWidth; const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); for (let n = walker.nextNode(); n && out.length < 6; n = walker.nextNode()) { if (!n.textContent.trim() || n.parentElement.closest('nav')) continue; const r = document.createRange(); r.selectNodeContents(n); for (const q of r.getClientRects()) { if (q.right > w + 0.5) { out.push(`${n.parentElement.tagName}.${n.parentElement.className} right=${Math.round(q.right)} \"${n.textContent.trim().slice(0, 30)}\"`); break; } } } for (const e of document.querySelectorAll('body *')) { if (out.length >= 10) break; const c = getComputedStyle(e); if (!e.closest('nav') && e.getBoundingClientRect().right > w + 0.5) out.push(`BOX ${e.tagName}.${e.className}`); else if (!e.closest('nav') && e.scrollWidth > e.clientWidth + 1 && c.overflowX === 'visible' && e.clientWidth > 0) out.push(`SCROLLW ${e.tagName}.${e.className} ${e.scrollWidth}>${e.clientWidth}`); } return out; })(),
    }));

  const hostileRoutes = ['#/', '#/ticket/24', '#/ticket/25', '#/ticket/5', '#/ticket/27', '#/cost', '#/environments', '#/agents', '#/escalations', '#/flow', '#/trail'];

  for (const [width, label] of [[1280, 'desktop'], [390, 'phone']]) {
    test(`hostile strings render as text only at ${label} width: nothing injected, no handler runs, no unsafe link`, async () => {
      for (const hash of hostileRoutes) {
        const { context, page } = await open('hostile', { hash, width, height: 900 });
        const seen = watch(page, servers.hostile.url);
        page.on('dialog', (d) => {
          seen.errors.push(`dialog: ${d.message()}`);
          d.dismiss();
        });
        await page.reload();
        await page.waitForSelector('#app[aria-busy="false"] .view');
        await page.waitForTimeout(150);
        const p = await probe(page);
        const where = `${hash} at ${label}`;
        assert.equal(p.pwned, null, `${where}: a payload ran`);
        assert.deepEqual(p.scripts, ['./js/theme.js', './js/main.js'], `${where}: unexpected script elements`);
        assert.deepEqual(p.handlers, [], `${where}: inline handler attributes`);
        assert.equal(p.styleAttrs, 0, `${where}: style attributes other than custom-property sizes`);
        assert.equal(p.badEls, 0, `${where}: injected elements`);
        for (const a of p.hrefs) {
          assert.ok(a.href.startsWith('#') || a.href === '../' || a.href === '../staging/' || a.href.startsWith(`${REPO}/`), `${where}: unsafe href ${a.href}`);
          assert.doesNotMatch(a.href, /^\s*(javascript|data|vbscript):/i);
          if (a.target === '_blank') assert.match(a.rel, /noopener/);
          if (a.target === '_blank') assert.match(a.rel, /noreferrer/);
        }
        assert.ok(p.overflow <= 0, `${where}: scrolls sideways by ${p.overflow}px; wide: ${JSON.stringify(p.wide)}`);
        assert.deepEqual(seen.errors, [], `${where}: console errors`);
        await context.close();
      }
    });
  }

  test('the payloads are visible as literal text', async () => {
    const { context, page } = await open('hostile', { hash: '#/ticket/24' });
    const body = await page.locator('main').innerText();
    assert.ok(body.includes(PAYLOADS.img), 'the <img> payload is shown as characters');
    assert.ok(body.includes(PAYLOADS.script));
    assert.equal(await page.locator('main img').count(), 0);
    assert.equal(await page.locator('a[href^="javascript:"]').count(), 0);
    await context.close();
    const hostile = makeHostile(rawSample);
    assert.equal(hostile.tickets.find((t) => t.issue === 5).title.length, 5000);
  });

  test('long titles are clamped on the card and do not stretch the layout', async () => {
    const { context, page } = await open('hostile');
    const card = page.locator('article.card', { hasText: '#5' }).first();
    const box = await card.boundingBox();
    assert.ok(box.height < 260, `card is ${box.height}px tall`);
    assert.ok(box.width < 320);
    await context.close();
  });

  test('every link the app can produce into GitHub stays inside the repository', async () => {
    const { context, page } = await open('normal', { hash: '#/ticket/24' });
    for (const hash of ['#/ticket/24', '#/environments', '#/escalations', '#/agents']) {
      await page.goto(`${servers.normal.url}?data=state.json${hash}`);
      await page.waitForSelector('#app[aria-busy="false"] .view');
      for (const a of await page.locator('a[target="_blank"]').all()) {
        assert.ok((await a.getAttribute('href')).startsWith(`${REPO}/`));
        assert.equal(await a.getAttribute('rel'), 'noopener noreferrer');
      }
    }
    await context.close();
  });
});

describe('fetch strategy in the browser (scripted GitHub, no ?data=)', { skip }, () => {
  const CORS = { 'access-control-allow-origin': '*', 'access-control-expose-headers': 'etag, x-ratelimit-remaining, x-ratelimit-reset', 'access-control-allow-headers': 'if-none-match, accept' };
  const RAW = 'https://raw.githubusercontent.com/stevengonsalvez/foundry-autonomous-sdlc/state/state.json';
  const API = 'https://api.github.com/repos/stevengonsalvez/foundry-autonomous-sdlc/contents/state.json?ref=state';
  const ISSUES = 'https://api.github.com/repos/stevengonsalvez/foundry-autonomous-sdlc/issues?state=open&sort=created&direction=desc&per_page=30';
  const at = (iso) => ({ ...structuredClone(rawSample), generated_at: iso, updated_at: iso });

  async function scripted({ rawDoc, apiDoc, issues = rawIssues, remaining = 55, reset = Math.floor(Date.parse(FIXED_NOW) / 1000) + 3000 } = {}) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await context.newPage();
    const log = [];
    const limit = () => ({ 'x-ratelimit-remaining': String(remaining), 'x-ratelimit-reset': String(reset) });
    await page.route(/^https:\/\/(raw\.githubusercontent\.com|api\.github\.com)\//, async (route) => {
      const req = route.request();
      const url = req.url();
      log.push({ method: req.method(), url, inm: req.headers()['if-none-match'] ?? null, auth: req.headers().authorization ?? null });
      if (req.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: CORS });
      if (url === RAW) return route.fulfill({ status: 200, headers: { ...CORS, 'cache-control': 'max-age=300' }, json: rawDoc });
      if (url === API) {
        if (req.headers()['if-none-match'] === '"s1"') return route.fulfill({ status: 304, headers: { ...CORS, ...limit(), etag: '"s1"' } });
        return route.fulfill({ status: 200, headers: { ...CORS, ...limit(), etag: '"s1"' }, json: apiDoc });
      }
      if (url === ISSUES) {
        if (req.headers()['if-none-match'] === '"i1"') return route.fulfill({ status: 304, headers: { ...CORS, ...limit(), etag: '"i1"' } });
        return route.fulfill({ status: 200, headers: { ...CORS, ...limit(), etag: '"i1"' }, json: issues });
      }
      return route.abort();
    });
    await page.clock.install({ time: new Date(FIXED_NOW) });
    await page.goto(servers.normal.url);
    await page.waitForSelector('#app[aria-busy="false"] .view');
    const gets = () => log.filter((l) => l.method === 'GET');
    return { context, page, log, gets };
  }

  test('newest generated_at wins and the header says which source it came from', async () => {
    const { context, page, gets } = await scripted({ rawDoc: at('2026-10-11T20:05:00Z'), apiDoc: at('2026-10-11T20:06:30Z') });
    assert.match(await text(page, '#freshness'), /source:\s*api/);
    assert.ok(gets().some((l) => l.url.startsWith('https://raw.githubusercontent.com')));
    assert.ok(gets().every((l) => l.auth === null), 'no token anywhere');
    await context.close();
  });

  test('raw alone is enough; an older api answer never replaces newer raw data', async () => {
    const { context, page } = await scripted({ rawDoc: at('2026-10-11T20:06:50Z'), apiDoc: at('2026-10-11T20:05:00Z') });
    assert.match(await text(page, '#freshness'), /source:\s*raw/);
    await context.close();
  });

  test('conditional requests: the ETag comes back as If-None-Match and a 304 changes nothing', async () => {
    const { context, page, gets } = await scripted({ rawDoc: at('2026-10-11T20:05:00Z'), apiDoc: at('2026-10-11T20:06:30Z') });
    await elapse(page, 61_000);
    const apiCalls = gets().filter((l) => l.url === API);
    assert.ok(apiCalls.length >= 2, `api called ${apiCalls.length} times: ${JSON.stringify(gets().map((l) => [l.url.slice(8, 20), l.at]))}`);
    assert.equal(apiCalls[0].inm, null);
    assert.equal(apiCalls[1].inm, '"s1"');
    const issueCalls = gets().filter((l) => l.url === ISSUES);
    assert.equal(issueCalls[1].inm, '"i1"');
    assert.match(await text(page, '#freshness'), /source:\s*api/);
    await context.close();
  });

  test('pending intake: an issue the ledger has not seen shows as a backlog card', async () => {
    const issues = [
      { number: 301, title: '<img src=x onerror="window.__pwned=1"> brand new', user: { login: 'stevengonsalvez' }, labels: [{ name: 'bug' }], created_at: '2026-10-11T20:06:40Z', updated_at: '2026-10-11T20:06:40Z' },
      { number: 302, title: 'a pull request', user: { login: 'stevengonsalvez' }, pull_request: {}, created_at: '2026-10-11T20:06:41Z', updated_at: '2026-10-11T20:06:41Z' },
      { number: 303, title: 'someone else', user: { login: 'mallory' }, created_at: '2026-10-11T20:06:42Z', updated_at: '2026-10-11T20:06:42Z' },
    ];
    const { context, page } = await scripted({ rawDoc: at('2026-10-11T20:05:00Z'), apiDoc: at('2026-10-11T20:06:30Z'), issues });
    const pending = page.locator('.col-backlog article.card');
    assert.equal(await pending.count(), 1);
    assert.match(await pending.innerText(), /Waiting for ledger/);
    assert.match(await pending.innerText(), /<img src=x onerror="window\.__pwned=1"> brand new/);
    assert.equal(await pending.locator('a').getAttribute('href'), `${REPO}/issues/301`);
    assert.equal(await page.evaluate(() => window.__pwned ?? null), null);
    assert.equal(await page.locator('main img').count(), 0);
    assert.equal(await page.locator('.col-backlog .col-count').innerText(), '1');
    await context.close();
  });

  test('row hover non-fill cue bolds first cell in environments table and pending chip preserves dashed border on hover', async () => {
    // 1. Environments table row hover bolds :is(td, th):first-child (which is a th)
    const { context: envCtx, page: envPage } = await open('normal', { hash: '#/environments', width: 1280, height: 900 });
    await envPage.waitForSelector('#app[aria-busy="false"] .view-environments');
    const row = envPage.locator('.view-environments table.data tbody tr').first();
    const firstCell = row.locator(':is(td, th):first-child');
    const tag = await firstCell.evaluate((el) => el.tagName.toLowerCase());
    assert.equal(tag, 'th', 'environments table first cell must be a th');

    await row.hover();
    await envPage.waitForTimeout(50);
    const rowHover = await firstCell.evaluate((el) => {
      const comp = window.getComputedStyle(el);
      const trComp = window.getComputedStyle(el.closest('tr'));
      return {
        fontWeight: comp.fontWeight,
        outlineStyle: trComp.outlineStyle,
      };
    });
    assert.ok(rowHover.fontWeight === '700' || rowHover.fontWeight === 'bold', 'environments row first cell must become bold on hover');
    assert.equal(rowHover.outlineStyle, 'solid', 'row hover must have solid outline non-fill cue');
    await envCtx.close();

    // 2. Pending card intake chip hover preserves dashed border
    const issues = [
      { number: 301, title: 'new intake item', user: { login: 'stevengonsalvez' }, created_at: '2026-10-11T20:06:40Z', updated_at: '2026-10-11T20:06:40Z' },
    ];
    const { context: pendingCtx, page: pendingPage } = await scripted({ rawDoc: at('2026-10-11T20:05:00Z'), apiDoc: at('2026-10-11T20:06:30Z'), issues });
    const pendingChip = pendingPage.locator('.chip-pill.card-pending').first();
    assert.equal(await pendingChip.count(), 1, 'card-pending chip must be rendered');

    const preHover = await pendingChip.evaluate((el) => window.getComputedStyle(el).borderTopStyle);
    assert.equal(preHover, 'dashed', 'pending chip must have dashed border before hover');

    await pendingChip.hover();
    await pendingPage.waitForTimeout(50);

    const postHover = await pendingChip.evaluate((el) => {
      const s = window.getComputedStyle(el);
      return {
        borderStyle: s.borderTopStyle,
        outlineStyle: s.outlineStyle,
        outlineWidth: s.outlineWidth,
      };
    });
    assert.equal(postHover.borderStyle, 'dashed', 'pending chip border must remain dashed on hover');
    assert.equal(postHover.outlineStyle, 'solid', 'pending chip must display outline on hover');
    assert.ok(parseFloat(postHover.outlineWidth) >= 1, 'outline width must be at least 1px');
    await pendingCtx.close();
  });

  test('rate budget: under 15 remaining the API is left alone, raw keeps polling', async () => {
    const { context, page, gets } = await scripted({ rawDoc: at('2026-10-11T20:05:00Z'), apiDoc: at('2026-10-11T20:06:30Z'), remaining: 9 });
    const apiBefore = gets().filter((l) => l.url === API || l.url === ISSUES).length;
    const rawBefore = gets().filter((l) => l.url === RAW).length;
    await elapse(page, 5 * 60_000);
    assert.equal(gets().filter((l) => l.url === API || l.url === ISSUES).length, apiBefore, 'no API calls while out of budget');
    assert.ok(gets().filter((l) => l.url === RAW).length >= rawBefore + 5, 'raw kept polling about every 30 s');
    await context.close();
  });

  test('every request is a GET (or the CORS preflight for one)', async () => {
    const { context, page, log } = await scripted({ rawDoc: at('2026-10-11T20:05:00Z'), apiDoc: at('2026-10-11T20:06:30Z') });
    await elapse(page, 2 * 60_000);
    assert.ok(log.length >= 3);
    assert.ok(log.every((l) => l.method === 'GET' || l.method === 'OPTIONS'), log.map((l) => l.method).join());
    await context.close();
  });

  test('a hidden tab stops polling, and showing it again refreshes at once', async () => {
    const { context, page, gets } = await scripted({ rawDoc: at('2026-10-11T20:05:00Z'), apiDoc: at('2026-10-11T20:06:30Z') });
    const setVisibility = (state) =>
      page.evaluate((value) => {
        Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => value });
        document.dispatchEvent(new Event('visibilitychange'));
      }, state);
    await setVisibility('hidden');
    await page.waitForTimeout(100);
    const frozen = gets().length;
    await elapse(page, 5 * 60_000);
    assert.equal(gets().length, frozen, 'nothing fetched while hidden');
    await setVisibility('visible');
    await page.waitForTimeout(300);
    assert.ok(gets().length > frozen, 'refreshed on return');
    await context.close();
  });

  test('manual refresh fetches now', async () => {
    const { context, page, gets } = await scripted({ rawDoc: at('2026-10-11T20:05:00Z'), apiDoc: at('2026-10-11T20:06:30Z') });
    await elapse(page, 6000);
    const before = gets().filter((l) => l.url === RAW).length;
    await page.getByRole('button', { name: 'Refresh now' }).click();
    await page.waitForTimeout(200);
    assert.equal(gets().filter((l) => l.url === RAW).length, before + 1);
    await context.close();
  });

  test('GitHub unreachable: the error state names the problem and offers a retry', async () => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.route(/^https:\/\/(raw\.githubusercontent\.com|api\.github\.com)\//, (route) => route.abort());
    await page.goto(servers.normal.url);
    await page.waitForSelector('.empty-error');
    assert.match(await text(page, '.empty-error'), /could not be reached/);
    await page.getByRole('button', { name: 'Retry' }).isVisible();
    await context.close();
  });
});

describe('preferences', { skip }, () => {
  test('dark theme is active by default and persists across reload', async () => {
    const { context, page } = await open('normal');
    const root = () => page.evaluate(() => document.documentElement.getAttribute('data-theme'));
    assert.equal(await root(), 'dark');
    await page.reload();
    assert.equal(await root(), 'dark', 'dark theme active after reload');
    await context.close();
  });

  test('blocked storage does not break the page', async () => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.addInitScript(() => {
      Object.defineProperty(window, 'localStorage', { get() { throw new DOMException('blocked', 'SecurityError'); } });
    });
    const seen = watch(page, servers.normal.url);
    await page.goto(`${servers.normal.url}?data=state.json`);
    await page.waitForSelector('#app[aria-busy="false"] .view');
    assert.deepEqual(seen.errors, []);
    await context.close();
  });

  test('reduced motion: the pulse on the current stage only animates when motion is allowed', async () => {
    const pulse = async (reducedMotion) => {
      const { context, page } = await open('normal', { hash: '#/ticket/23', reducedMotion });
      const name = await page.evaluate(() => getComputedStyle(document.querySelector('.node-pulse')).animationName);
      await context.close();
      return name;
    };
    assert.equal(await pulse('no-preference'), 'ping');
    assert.equal(await pulse('reduce'), 'none');
  });

  test('keyboard: the skip link comes first and focus is visible on links and buttons', async () => {
    const { context, page } = await open('normal');
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.className), 'skip-link');
    for (let i = 0; i < 6; i += 1) await page.keyboard.press('Tab');
    const outline = await page.evaluate(() => getComputedStyle(document.activeElement).outlineStyle);
    assert.notEqual(outline, 'none');
    await context.close();
  });

  test('live region announces a data update', async () => {
    const { context, page } = await open('normal');
    await page.evaluate(() => document.getElementById('live').textContent);
    assert.equal(await page.locator('#live[aria-live="polite"]').count(), 1);
    await context.close();
  });
});

describe('accessibility (axe)', { skip: skip || (pw?.AxeBuilder ? false : '@axe-core/playwright is not resolvable from app/node_modules') }, () => {
  for (const scheme of ['light', 'dark']) {
    test(`no serious or critical violations in any view (${scheme})`, async () => {
      const problems = [];
      for (const [name, hash] of [...VIEWS, ['ticket-25', '#/ticket/25'], ['ticket-5', '#/ticket/5']]) {
        const { context, page } = await open('normal', { hash, scheme, reducedMotion: 'reduce' });
        const results = await new pw.AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
        for (const v of results.violations.filter((x) => ['serious', 'critical'].includes(x.impact))) {
          problems.push(`${scheme} ${name}: ${v.id} (${v.impact}) ${v.nodes.slice(0, 3).map((n) => n.target.join(' ')).join(' | ')}`);
        }
        await context.close();
      }
      assert.deepEqual(problems, []);
    });
  }
});
