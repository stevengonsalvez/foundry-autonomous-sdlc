import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { escalationLabel } from '../js/format.js';
import { boardColumns, emptyFilters, openEscalations } from '../js/model.js';
import { parseState } from '../js/schema.js';

const raw = JSON.parse(await readFile(new URL('./fixtures/state.merge-conflict.json', import.meta.url), 'utf8'));
const NOW = Date.parse('2026-10-15T11:00:00Z');

test('a merge-conflict escalation is an open escalation with its label and reason', () => {
  const r = parseState(structuredClone(raw));
  assert.equal(r.status, 'ok');
  const open = openEscalations(r.state);
  assert.equal(open.length, 1);
  assert.equal(open[0].issue, 96);
  assert.equal(open[0].escalation.label, 'escalated:merge-conflict');
  assert.equal(escalationLabel(open[0].escalation.label), 'Merge conflict');
  assert.match(open[0].escalation.reasons[0], /merge conflict rounds: GitHub 405/);
});

test('the ticket sits in the escalated column of the board', () => {
  const { state } = parseState(structuredClone(raw));
  const cols = boardColumns(state, [], emptyFilters(), NOW);
  assert.deepEqual(cols.find((c) => c.stage === 'escalated').tickets.map((t) => t.issue), [96]);
});
