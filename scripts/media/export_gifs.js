#!/usr/bin/env node
/**
 * Export GIF fallbacks for all animated SVGs using headless Chromium and ffmpeg.
 * Produces crisp, high-quality, lightweight GIFs (< 2 MB each).
 */

const { chromium } = require('playwright');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execSync } = require('child_process');

const ASSETS = [
  { name: 'topology', width: 880, height: 513, fps: 5, duration: 12 },
  { name: 'scenario-feature', width: 880, height: 403, fps: 5, duration: 14 },
  { name: 'scenario-bug', width: 880, height: 403, fps: 5, duration: 14 },
  { name: 'scenario-escalation', width: 880, height: 403, fps: 5, duration: 14 },
  { name: 'scenario-rollback', width: 880, height: 403, fps: 5, duration: 14 },
  { name: 'hero', width: 880, height: 458, fps: 5, duration: 14 }
];

const MEDIA_DIR = path.resolve(__dirname, '../../docs/media');
const TMP_FRAMES_DIR = path.resolve(__dirname, '../../docs/media/.gif_frames');

async function exportGifs() {
  console.log('=== EXPORTING GIF FALLBACKS VIA CHROMIUM & FFMPEG ===');

  if (fs.existsSync(TMP_FRAMES_DIR)) {
    fs.rmSync(TMP_FRAMES_DIR, { recursive: true, force: true });
  }
  fs.mkdirSync(TMP_FRAMES_DIR, { recursive: true });

  const chromePath = process.env.CHROME_PATH || path.join(os.homedir(), '.local/pw-browsers/chromium-1234/chrome-linux64/chrome');
  const browser = await chromium.launch({
    executablePath: chromePath,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  for (const asset of ASSETS) {
    const svgPath = path.join(MEDIA_DIR, `${asset.name}.svg`);
    const gifPath = path.join(MEDIA_DIR, `${asset.name}.gif`);
    const framesDir = path.join(TMP_FRAMES_DIR, asset.name);
    fs.mkdirSync(framesDir, { recursive: true });

    console.log(`\nRecording frames for ${asset.name} (${asset.duration}s @ ${asset.fps}fps)...`);

    const page = await browser.newPage({
      viewport: { width: asset.width, height: asset.height }
    });

    await page.goto(`file://${svgPath}`);

    const totalFrames = Math.round(asset.duration * asset.fps);
    const intervalMs = 1000 / asset.fps;

    const startTime = Date.now();
    for (let i = 0; i < totalFrames; i++) {
      const frameFile = path.join(framesDir, `frame_${String(i).padStart(4, '0')}.png`);
      await page.screenshot({ path: frameFile });
      await page.waitForTimeout(intervalMs);
    }
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    console.log(`  Captured ${totalFrames} frames in ${elapsed}s`);
    await page.close();

    console.log(`  Encoding ${asset.name}.gif via ffmpeg...`);
    // High-quality palette generation and dithering for crisp monochrome and neon tones
    const ffmpegCmd = `ffmpeg -y -framerate ${asset.fps} -i "${framesDir}/frame_%04d.png" ` +
      `-filter_complex "[0:v] fps=${asset.fps},scale=${asset.width}:-1:flags=lanczos,split [a][b];[a] palettegen=max_colors=128:reserve_transparent=0 [p];[b][p] paletteuse=dither=bayer:bayer_scale=3" ` +
      `"${gifPath}"`;

    execSync(ffmpegCmd, { stdio: 'pipe' });

    const stats = fs.statSync(gifPath);
    const sizeMb = (stats.size / 1024 / 1024).toFixed(2);
    console.log(`  Created ${asset.name}.gif: ${sizeMb} MB (target < 2.0 MB)`);

    if (stats.size > 2 * 1024 * 1024) {
      console.warn(`  WARNING: ${asset.name}.gif exceeds 2 MB!`);
    }

    // Clean up frames for this asset
    fs.rmSync(framesDir, { recursive: true, force: true });
  }

  await browser.close();

  // Clean up frames directory
  fs.rmSync(TMP_FRAMES_DIR, { recursive: true, force: true });

  console.log('\n=== ALL 6 GIF FALLBACKS EXPORTED SUCCESSFULLY ===');
}

exportGifs().catch(err => {
  console.error(err);
  process.exit(1);
});
