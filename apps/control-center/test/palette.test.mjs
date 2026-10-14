import { test } from 'node:test';
import assert from 'node:assert/strict';
import { run } from '../scripts/palette-distance.mjs';

test('all tokens satisfy same-role distance, neutral ladder separation, adjacent rungs contrast, and stage fill separation', async () => {
  const result = await run();
  assert.equal(result.allPass, true, 'all accents must pass same-role distance');
  assert.equal(result.neutralsPass, true, 'all neutrals must differ from all 8 reference neutrals by dE_ok >= 0.04');
  assert.equal(result.rungsPass, true, 'adjacent surface rungs must achieve contrast ratio >= 1.10:1');
  assert.equal(result.fillsPass, true, 'all stage fills must maintain circular dh >= 25 and dE_ok >= 0.06');
});
