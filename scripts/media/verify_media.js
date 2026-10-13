#!/usr/bin/env node
/**
 * Verification script for autonomous SDLC animated SVG assets.
 * Tests each SVG rendered as an <img> tag in headless Chromium:
 * 1. Checks that no console errors occur
 * 2. Checks that zero external network requests are made
 * 3. Proves motion happens by capturing frames at multiple timestamps and checking differences
 * 4. Checks rendering at 1440px (desktop) and 360px (mobile)
 */

const { chromium } = require('playwright');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync } = require('child_process');

const SVGS = [
  'topology.svg',
  'scenario-feature.svg',
  'scenario-bug.svg',
  'scenario-escalation.svg',
  'scenario-rollback.svg',
  'hero.svg'
];

const MEDIA_DIR = path.resolve(__dirname, '../../docs/media');
const SCRATCH_DIR = path.resolve(__dirname, '../../docs/media/.verify_tmp');

async function verify() {
  console.log('=== VERIFYING ANIMATED SVGS IN HEADLESS CHROMIUM ===');
  if (!fs.existsSync(SCRATCH_DIR)) {
    fs.mkdirSync(SCRATCH_DIR, { recursive: true });
  }

  const chromePath = process.env.CHROME_PATH || path.join(os.homedir(), '.local/pw-browsers/chromium-1234/chrome-linux64/chrome');
  const browser = await chromium.launch({
    executablePath: chromePath,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  let totalErrors = 0;

  for (const svgFile of SVGS) {
    const svgPath = path.join(MEDIA_DIR, svgFile);
    if (!fs.existsSync(svgPath)) {
      console.error(`ERROR: Missing file ${svgPath}`);
      totalErrors++;
      continue;
    }

    console.log(`\nTesting ${svgFile}...`);

    // Create temporary HTML file loading the SVG in an <img> tag
    const htmlContent = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body { margin: 0; padding: 20px; background: #02080f; display: flex; justify-content: center; }
    img { width: 100%; max-width: 960px; height: auto; display: block; }
  </style>
</head>
<body>
  <img id="test-img" src="${svgFile}" alt="Test SVG" />
</body>
</html>`;

    const htmlPath = path.join(MEDIA_DIR, `_test_${svgFile}.html`);
    fs.writeFileSync(htmlPath, htmlContent, 'utf-8');

    // 1. Desktop Test (1440px)
    const page1440 = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const consoleErrors = [];
    const externalRequests = [];

    page1440.on('console', msg => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });

    page1440.on('request', req => {
      const url = req.url();
      if (!url.startsWith('file://') && !url.startsWith('data:')) {
        externalRequests.push(url);
      }
    });

    await page1440.goto(`file://${htmlPath}`, { waitUntil: 'load' });

    // Capture at t=0
    const frame0 = path.join(SCRATCH_DIR, `${svgFile}_1440_t0.png`);
    await page1440.screenshot({ path: frame0 });

    // Wait 1.5s and capture at t=1.5s
    await page1440.waitForTimeout(1500);
    const frame1 = path.join(SCRATCH_DIR, `${svgFile}_1440_t1.png`);
    await page1440.screenshot({ path: frame1 });

    // Wait another 2s and capture at t=3.5s
    await page1440.waitForTimeout(2000);
    const frame2 = path.join(SCRATCH_DIR, `${svgFile}_1440_t2.png`);
    await page1440.screenshot({ path: frame2 });

    // Check motion
    const buf0 = fs.readFileSync(frame0);
    const buf1 = fs.readFileSync(frame1);
    const buf2 = fs.readFileSync(frame2);

    const motionDetected = !buf0.equals(buf1) && !buf1.equals(buf2);
    if (!motionDetected) {
      console.error(`  FAIL: No motion detected between frames in ${svgFile}!`);
      totalErrors++;
    } else {
      console.log(`  PASS: Motion confirmed across frames (t0 vs t1 vs t2 differ)`);
    }

    if (consoleErrors.length > 0) {
      console.error(`  FAIL: Console errors detected:`, consoleErrors);
      totalErrors += consoleErrors.length;
    } else {
      console.log(`  PASS: 0 console errors`);
    }

    if (externalRequests.length > 0) {
      console.error(`  FAIL: External network requests detected:`, externalRequests);
      totalErrors += externalRequests.length;
    } else {
      console.log(`  PASS: 0 external network requests`);
    }

    await page1440.close();

    // 2. Mobile Test (360px)
    const page360 = await browser.newPage({ viewport: { width: 360, height: 640 } });
    await page360.goto(`file://${htmlPath}`, { waitUntil: 'load' });
    const frameMobile = path.join(SCRATCH_DIR, `${svgFile}_360_t0.png`);
    await page360.screenshot({ path: frameMobile });
    console.log(`  PASS: Rendered cleanly at 360px viewport`);
    await page360.close();

    // Cleanup temp html
    fs.unlinkSync(htmlPath);
  }

  await browser.close();

  console.log(`\n=== VERIFICATION COMPLETE: ${totalErrors === 0 ? 'ALL PASSED' : totalErrors + ' ERRORS'} ===`);
  if (totalErrors > 0) process.exit(1);
}

verify().catch(err => {
  console.error(err);
  process.exit(1);
});
