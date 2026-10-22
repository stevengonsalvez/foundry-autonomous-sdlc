import { test } from 'node:test';
import assert from 'node:assert/strict';

import { agentTag } from '../js/views/common.js';

test('agentTag keeps the fixed codes for the eleven Foundry agents', () => {
  assert.equal(agentTag('sdlc-orchestrator'), 'OR');
  assert.equal(agentTag('sdlc-ci-triage'), 'CT');
  assert.equal(agentTag('sdlc-ledger'), 'LD');
});

test('agentTag tells factory agents apart by the name after the sdlc- prefix', () => {
  assert.equal(agentTag('sdlc-ui-tester'), 'UI');
  assert.equal(agentTag('sdlc-foreman'), 'FO');
  assert.notEqual(agentTag('sdlc-ui-tester'), agentTag('sdlc-foreman'));
  assert.equal(agentTag('worker'), 'WO');
});

test('agentTag shows a dash for no agent', () => {
  assert.equal(agentTag(''), '--');
  assert.equal(agentTag(null), '--');
});
