import { test } from 'node:test';
import assert from 'node:assert/strict';

import { parseRoute } from '../js/router.js';

test('hash routes', () => {
  assert.deepEqual(parseRoute(''), { name: 'board' });
  assert.deepEqual(parseRoute('#/'), { name: 'board' });
  assert.deepEqual(parseRoute('#/ticket/24'), { name: 'ticket', issue: 24 });
  assert.deepEqual(parseRoute('#/ticket/24/'), { name: 'ticket', issue: 24 });
  for (const name of ['cost', 'environments', 'agents', 'escalations', 'flow', 'trail']) {
    assert.deepEqual(parseRoute(`#/${name}`), { name });
  }
  for (const bad of ['#/ticket/abc', '#/ticket/', '#/ticket/1/2', '#/ticket/-3', '#/nope', '#/constructor', '#/__proto__', '#/cost/x']) {
    assert.deepEqual(parseRoute(bad), { name: 'not-found' }, bad);
  }
});
