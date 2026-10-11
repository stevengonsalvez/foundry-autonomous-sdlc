import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { cp, mkdir, mkdtemp, readFile, readdir, rm, stat, symlink, writeFile } from 'node:fs/promises';
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

async function builtApp(dir, name, sha) {
  const dist = join(dir, name);
  await mkdir(join(dist, 'assets'), { recursive: true });
  await writeFile(join(dist, 'index.html'), `<!doctype html><title>${name}</title>`);
  await writeFile(join(dist, 'assets', 'app.js'), `console.log("${name}");`);
  if (sha) await writeFile(join(dist, 'build.json'), JSON.stringify({ sha, short: sha.slice(0, 7) }));
  return dist;
}

async function controlCenter(dir, extra = {}) {
  const src = join(dir, 'control-center-src');
  await mkdir(join(src, 'css'), { recursive: true });
  await mkdir(join(src, 'js'), { recursive: true });
  await writeFile(join(src, 'index.html'), '<!doctype html><title>Control center</title>');
  await writeFile(join(src, 'css', 'app.css'), 'body{}');
  await writeFile(join(src, 'js', 'app.js'), 'export {};');
  for (const [path, body] of Object.entries(extra)) {
    await mkdir(join(src, path, '..'), { recursive: true });
    await writeFile(join(src, path), body);
  }
  return src;
}

test('PROD_DIST is the same as APP_DIST, and setting both is refused', async () => {
  const sb = await sandbox();
  try {
    const ok = run([sb.out], { PROD_DIST: sb.appDist });
    assert.equal(ok.status, 0, ok.stderr);
    assert.ok(await exists(join(sb.out, 'assets', 'app.js')));

    const both = run([join(sb.dir, 'out2')], { PROD_DIST: sb.appDist, APP_DIST: sb.appDist });
    assert.notEqual(both.status, 0);
    assert.match(both.stderr, /only one of APP_DIST and PROD_DIST/);
  } finally {
    await sb.cleanup();
  }
});

test('publishes prod at the root and staging under /staging/, each with its own build.json', async () => {
  const sb = await sandbox();
  try {
    const prod = await builtApp(sb.dir, 'prod', 'a'.repeat(40));
    const staging = await builtApp(sb.dir, 'staging', 'b'.repeat(40));
    const r = run([sb.out], { PROD_DIST: prod, STAGING_DIST: staging });
    assert.equal(r.status, 0, r.stderr);
    const files = await listFiles(sb.out);
    for (const expected of ['index.html', 'build.json', 'assets/app.js', 'staging/index.html', 'staging/build.json', 'staging/assets/app.js', 'dashboard/index.html']) {
      assert.ok(files.includes(expected), `missing ${expected}`);
    }
    assert.equal(JSON.parse(await readFile(join(sb.out, 'build.json'), 'utf8')).sha, 'a'.repeat(40));
    assert.equal(JSON.parse(await readFile(join(sb.out, 'staging', 'build.json'), 'utf8')).sha, 'b'.repeat(40));
    assert.match(r.stdout, /staging published at \/staging\//);
  } finally {
    await sb.cleanup();
  }
});

test('without STAGING_DIST no /staging/ is published', async () => {
  const sb = await sandbox();
  try {
    const r = run([sb.out], { PROD_DIST: sb.appDist });
    assert.equal(r.status, 0, r.stderr);
    assert.ok(!(await exists(join(sb.out, 'staging'))));
    assert.match(r.stdout, /\/staging\/ is not published/);
  } finally {
    await sb.cleanup();
  }
});

for (const [name, setup] of [
  ['an invalid build.json', (dist) => writeFile(join(dist, 'build.json'), '{not json')],
  ['a build.json without a sha', (dist) => writeFile(join(dist, 'build.json'), '{"short":"abc"}')],
  ['a staging path inside the artifact', (dist) => mkdir(join(dist, 'staging'))],
  ['a control-center path inside the artifact', (dist) => mkdir(join(dist, 'control-center'))],
]) {
  test(`refuses a built app with ${name}`, async () => {
    const sb = await sandbox();
    try {
      const staging = await builtApp(sb.dir, 'staging', 'b'.repeat(40));
      await setup(staging);
      const r = run([sb.out], { PROD_DIST: sb.appDist, STAGING_DIST: staging });
      assert.notEqual(r.status, 0);
      assert.match(r.stderr, /staging build/);
    } finally {
      await sb.cleanup();
    }
  });
}

test('refuses a staging build without index.html', async () => {
  const sb = await sandbox();
  try {
    const staging = await builtApp(sb.dir, 'staging');
    await rm(join(staging, 'index.html'));
    const r = run([sb.out], { PROD_DIST: sb.appDist, STAGING_DIST: staging });
    assert.notEqual(r.status, 0);
    assert.match(r.stderr, /staging build has no index\.html/);
  } finally {
    await sb.cleanup();
  }
});

test('publishes the control center through an allowlist', async () => {
  const sb = await sandbox();
  try {
    const src = await controlCenter(sb.dir, {
      'assets/logo.svg': '<svg/>',
      'notes.md': 'dev notes',
      'package.json': '{}',
      'tsconfig.json': '{}',
      'scripts/dev.mjs': 'x',
    });
    const r = run([sb.out], { PROD_DIST: sb.appDist, CONTROL_CENTER_SRC: src });
    assert.equal(r.status, 0, r.stderr);
    const files = (await listFiles(sb.out)).filter((f) => f.startsWith('control-center/'));
    assert.deepEqual(files, [
      'control-center/assets/logo.svg',
      'control-center/css/app.css',
      'control-center/index.html',
      'control-center/js/app.js',
    ]);
  } finally {
    await sb.cleanup();
  }
});

test('a missing or empty control center source is skipped without error', async () => {
  const sb = await sandbox();
  try {
    for (const [i, src] of [join(sb.dir, 'nope'), sb.dir.concat('/app-dist/assets'), ''].entries()) {
      const out = join(sb.dir, `out-${i}`);
      const r = run([out], { PROD_DIST: sb.appDist, CONTROL_CENTER_SRC: src });
      assert.equal(r.status, 0, r.stderr);
      assert.ok(!(await exists(join(out, 'control-center'))));
      assert.match(r.stdout, /\/control-center\/ is not published/);
    }
  } finally {
    await sb.cleanup();
  }
});

for (const [name, extra] of [
  ['a test file', { 'js/app.test.js': 'x' }],
  ['a fixture', { 'js/fixture-data.js': 'x' }],
  ['a sample json', { 'assets/orders.sample.json': '{}' }],
  ['a README', { 'css/README.md': 'x' }],
  ['a test directory', { 'js/test/a.js': 'x' }],
  ['a package.json', { 'js/package.json': '{}' }],
]) {
  test(`the leak guard stops the control center from shipping ${name}`, async () => {
    const sb = await sandbox();
    try {
      const src = await controlCenter(sb.dir, extra);
      const r = run([sb.out], { PROD_DIST: sb.appDist, CONTROL_CENTER_SRC: src });
      assert.notEqual(r.status, 0);
      assert.match(r.stderr, /refusing to publish/);
      assert.match(r.stderr, /control-center output/);
    } finally {
      await sb.cleanup();
    }
  });
}

test('the leak guard stops a symlink in the control center from shipping', async () => {
  const sb = await sandbox();
  try {
    const src = await controlCenter(sb.dir);
    await symlink('/etc/hosts', join(src, 'js', 'hosts.js'));
    const r = run([sb.out], { PROD_DIST: sb.appDist, CONTROL_CENTER_SRC: src });
    assert.notEqual(r.status, 0);
    assert.match(r.stderr, /refusing to publish/);
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
