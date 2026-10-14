import { test } from 'node:test';
import assert from 'node:assert/strict';

import { cleanSha, commitUrl, isSafeHref, issueUrl, limitText, positiveInt, pullUrl, releaseUrl, resolveDataParam, safeGithubUrl } from '../js/safe.js';
import { classToken } from '../js/dom.js';

const REPO = 'https://github.com/stevengonsalvez/foundry-autonomous-sdlc';

test('safeGithubUrl keeps only URLs inside this repository', () => {
  assert.equal(safeGithubUrl(`${REPO}/issues/24`), `${REPO}/issues/24`);
  assert.equal(safeGithubUrl(`${REPO}/actions/runs/5`), `${REPO}/actions/runs/5`);
  assert.equal(safeGithubUrl(`${REPO}/issues/new?template=feature_request.yml`), `${REPO}/issues/new?template=feature_request.yml`);
  for (const bad of [
    'javascript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'https://evil.example/x',
    'http://github.com/stevengonsalvez/foundry-autonomous-sdlc/issues/1',
    'https://github.com.evil.example/stevengonsalvez/foundry-autonomous-sdlc/issues/1',
    'https://github.com/stevengonsalvez/foundry-autonomous-sdlc.evil/x',
    'https://github.com/stevengonsalvez/foundry-autonomous-sdlc',
    'https://github.com/other/repo/issues/1',
    `${REPO}/../../evil/x`,
    'https://user:pass@github.com/stevengonsalvez/foundry-autonomous-sdlc/x',
    'https://github.com:8443/stevengonsalvez/foundry-autonomous-sdlc/x',
    `${REPO}/issues/1 onclick=1`,
    `${REPO}/issues/1\\@evil.example`,
    '',
    null,
    undefined,
    42,
    {},
  ]) {
    assert.equal(safeGithubUrl(bad), null, `should reject ${String(bad)}`);
  }
});

test('isSafeHref allows fragments, the two site links and repo URLs only', () => {
  assert.equal(isSafeHref('#/ticket/24'), true);
  assert.equal(isSafeHref('../'), true);
  assert.equal(isSafeHref('../staging/'), true);
  assert.equal(isSafeHref(`${REPO}/pull/3`), true);
  for (const bad of ['javascript:1', '//evil.example', 'https://evil.example', '/etc/passwd', '../../x', '#/a b', 'mailto:a@b.c']) {
    assert.equal(isSafeHref(bad), false, bad);
  }
});

test('link builders validate their input', () => {
  assert.equal(issueUrl(24), `${REPO}/issues/24`);
  assert.equal(issueUrl('24'), `${REPO}/issues/24`);
  assert.equal(issueUrl('24/../x'), null);
  assert.equal(issueUrl(-1), null);
  assert.equal(pullUrl(1.5), null);
  assert.equal(commitUrl('1897EA106BA36AC8D8873FC2A29701B6314C298D'), `${REPO}/commit/1897ea106ba36ac8d8873fc2a29701b6314c298d`);
  assert.equal(commitUrl('xyz'), null);
  assert.equal(cleanSha('abc123'), null);
  assert.equal(releaseUrl('v0.3.0'), `${REPO}/releases/tag/v0.3.0`);
  assert.equal(releaseUrl('prod/20261010-174600-f677ba5'), `${REPO}/releases/tag/prod/20261010-174600-f677ba5`);
  assert.equal(releaseUrl('v1"onmouseover="x'), null);
  assert.equal(releaseUrl('../x'), null);
  assert.equal(positiveInt('0'), null);
  assert.equal(positiveInt('12'), 12);
});

test('resolveDataParam accepts only same-origin relative .json paths', () => {
  const base = 'http://127.0.0.1:8090/control-center/?data=x';
  assert.equal(resolveDataParam('state.json', base), 'http://127.0.0.1:8090/control-center/state.json');
  assert.equal(resolveDataParam('./test/fixtures/state.sample.json', base), 'http://127.0.0.1:8090/control-center/test/fixtures/state.sample.json');
  for (const bad of ['../state.json', 'a/../b.json', '/state.json', '//evil.example/x.json', 'https://evil.example/x.json', 'state.txt', 'state.json?x=1', 'state.json#a', '', 'a b.json', 'x'.repeat(300) + '.json', null, undefined, 5]) {
    assert.equal(resolveDataParam(bad, base), null, `should reject ${String(bad)}`);
  }
});

test('limitText flattens control characters and caps the length', () => {
  assert.equal(limitText('a\nb\tc'), 'a b c');
  assert.equal(limitText('x'.repeat(5000), 10).length, 10);
  assert.equal(limitText('x'.repeat(5000), 10).endsWith('\u2026'), true);
  assert.equal(limitText(null), '');
});

test('classToken sanitizes hostile and malformed tokens to bounded [a-z0-9-]', () => {
  assert.equal(classToken('x is-stale'), 'x-is-stale');
  assert.equal(classToken('Backlog'), 'backlog');
  assert.equal(classToken('DEPLOY_FAILED'), 'deploy-failed');
  assert.equal(classToken('  --leading-and-trailing--  '), 'leading-and-trailing');
  assert.equal(classToken('<script>alert(1)</script>'), 'script-alert-1-script');
  assert.equal(classToken('a'.repeat(60)).length, 32);
  assert.equal(classToken(null), '');
  assert.equal(classToken(undefined), '');
  assert.equal(classToken(''), '');
  assert.equal(classToken('!!!'), '');
});
