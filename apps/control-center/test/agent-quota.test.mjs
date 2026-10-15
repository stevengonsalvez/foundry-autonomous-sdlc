import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { escalationLabel } from '../js/format.js';
import { boardColumns, emptyFilters, openEscalations } from '../js/model.js';
import { parseState } from '../js/schema.js';

const raw = JSON.parse(await readFile(new URL('./fixtures/state.agent-quota.json', import.meta.url), 'utf8'));
const NOW = Date.parse('2026-10-15T13:00:00Z');

test('an agent-quota escalation is an open escalation with its label and reasons', () => {
  const r = parseState(structuredClone(raw));
  assert.equal(r.status, 'ok');
  const open = openEscalations(r.state);
  assert.equal(open.length, 1);
  assert.equal(open[0].escalation.label, 'escalated:agent-quota');
  assert.equal(escalationLabel(open[0].escalation.label), 'Agent quota');
  assert.match(open[0].escalation.reasons[1], /account quota/);
});

test('the ticket sits in the escalated column of the board', () => {
  const { state } = parseState(structuredClone(raw));
  const cols = boardColumns(state, [], emptyFilters(), NOW);
  assert.deepEqual(cols.find((c) => c.stage === 'escalated').tickets.map((t) => t.issue), [96]);
});
