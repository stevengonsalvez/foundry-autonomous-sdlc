import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { cp, mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = fileURLToPath(new URL('../../', import.meta.url));
const script = join(repoRoot, 'scripts', 'build_pages.sh');
const fixturePath = join(repoRoot, 'dashboard', 'test', 'fixtures', 'metrics.sample.json');

async function sandbox() {
  const dir = await mkdtemp(join(tmpdir(), 'build-pages-'));
  const appDist = join(dir, 'app-dist');
  await mkdir(join(appDist, 'assets'), { recursive: true });
  await writeFile(join(appDist, 'index.html'), '<!doctype html><title>Parcel tracker</title>');
  await writeFile(join(appDist, 'assets', 'app.js'), 'console.log("app");');
  return { dir, appDist, out: join(dir, 'out'), cleanup: () => rm(dir, { recursive: true, force: true }) };
}

function run(args, env = {}) {
  return spawnSync('bash', [script, ...args], { encoding: 'utf8', env: { ...process.env, ...env } });
}

async function listFiles(root, dir = root) {
  const files = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await listFiles(root, full)));
    else files.push(relative(root, full));
  }
  return files.sort();
}

const exists = (p) => stat(p).then(() => true, () => false);

test('assembles the app at the root and the dashboard under /dashboard/', async () => {
  const sb = await sandbox();
  try {
    const r = run([sb.out], { APP_DIST: sb.appDist });
    assert.equal(r.status, 0, r.stderr);
    const files = await listFiles(sb.out);
    for (const expected of [
      '.nojekyll',
      'index.html',
      'assets/app.js',
      'dashboard/index.html',
      'dashboard/css/styles.css',
      'dashboard/js/aggregate.js',
      'dashboard/js/main.js',
      'dashboard/js/panels.js',
    ]) {
      assert.ok(files.includes(expected), `missing ${expected}`);
    }
    assert.ok(!files.includes('dashboard/metrics.json'), 'no metrics checkout was given');
    assert.match(r.stdout, /published tree/);
    assert.match(r.stdout, /dashboard\/index\.html/);
  } finally {
    await sb.cleanup();
  }
});

test('no fixture, test, package or doc file leaks into the output', async () => {
  const sb = await sandbox();
  try {
    const metricsDir = join(sb.dir, 'metrics');
    await mkdir(metricsDir);
    await cp(fixturePath, join(metricsDir, 'metrics.json'));
    const r = run([sb.out, metricsDir], { APP_DIST: sb.appDist });
    assert.equal(r.status, 0, r.stderr);
    const files = await listFiles(sb.out);
    const leaks = files.filter((f) => /fixture|sample|\.test\.|(^|\/)test\/|node_modules|package\.json|README/i.test(f));
    assert.deepEqual(leaks, []);
    assert.deepEqual(files.filter((f) => f.endsWith('.json')), ['dashboard/metrics.json']);
  } finally {
    await sb.cleanup();
  }
});

test('publishes metrics.json from the checkout when it is valid for this schema version', async () => {
  const sb = await sandbox();
  try {
    const metricsDir = join(sb.dir, 'metrics');
    await mkdir(metricsDir);
    const body = JSON.stringify({ version: 1, generated_at: '2026-10-10T12:00:00Z', issues: [] });
    await writeFile(join(metricsDir, 'metrics.json'), body);
    const r = run([sb.out, metricsDir], { APP_DIST: sb.appDist });
    assert.equal(r.status, 0, r.stderr);
    assert.equal(await readFile(join(sb.out, 'dashboard', 'metrics.json'), 'utf8'), body);
    assert.match(r.stdout, /metrics\.json published/);
  } finally {
    await sb.cleanup();
  }
});

for (const [name, body] of [
  ['a different schema version', JSON.stringify({ version: 2, issues: [] })],
  ['invalid JSON', '{"version": 1,'],
  ['a JSON array', '[]'],
  ['an empty file', ''],
]) {
  test(`does not publish metrics.json with ${name}`, async () => {
    const sb = await sandbox();
    try {
      const metricsDir = join(sb.dir, 'metrics');
      await mkdir(metricsDir);
      await writeFile(join(metricsDir, 'metrics.json'), body);
      const r = run([sb.out, metricsDir], { APP_DIST: sb.appDist });
      assert.equal(r.status, 0, r.stderr);
      assert.ok(!(await exists(join(sb.out, 'dashboard', 'metrics.json'))));
      assert.match(r.stdout, /skipped/);
    } finally {
      await sb.cleanup();
    }
  });
}

test('a metrics checkout without metrics.json is not an error', async () => {
  const sb = await sandbox();
  try {
    const metricsDir = join(sb.dir, 'metrics');
    await mkdir(metricsDir);
    const r = run([sb.out, metricsDir], { APP_DIST: sb.appDist });
    assert.equal(r.status, 0, r.stderr);
    assert.ok(!(await exists(join(sb.out, 'dashboard', 'metrics.json'))));
  } finally {
    await sb.cleanup();
  }
});

test('refuses a non-empty output directory', async () => {
  const sb = await sandbox();
  try {
    await mkdir(sb.out);
    await writeFile(join(sb.out, 'keep.txt'), 'do not delete');
    const r = run([sb.out], { APP_DIST: sb.appDist });
    assert.notEqual(r.status, 0);
    assert.match(r.stderr, /not empty/);
    assert.equal(await readFile(join(sb.out, 'keep.txt'), 'utf8'), 'do not delete');
  } finally {
    await sb.cleanup();
  }
});

test('refuses the repository root and its parents as output', async () => {
  const r = run([repoRoot], { APP_DIST: repoRoot });
  assert.notEqual(r.status, 0);
  assert.match(r.stderr, /must not be the repository root/);
});

test('fails when the app build has no index.html', async () => {
  const sb = await sandbox();
  try {
    await rm(join(sb.appDist, 'index.html'));
    const r = run([sb.out], { APP_DIST: sb.appDist });
    assert.notEqual(r.status, 0);
    assert.match(r.stderr, /no index\.html/);
  } finally {
    await sb.cleanup();
  }
});

test('prints usage without arguments', () => {
  const r = run([]);
  assert.equal(r.status, 2);
  assert.match(r.stderr, /usage:/);
});

test('the script is shellcheck clean', { skip: spawnSync('shellcheck', ['--version']).status !== 0 && 'shellcheck not installed' }, () => {
  const r = spawnSync('shellcheck', [script], { encoding: 'utf8' });
  assert.equal(r.status, 0, r.stdout);
});
