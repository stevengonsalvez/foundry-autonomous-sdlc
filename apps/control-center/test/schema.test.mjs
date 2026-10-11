import { test } from 'node:test';
import assert from 'node:assert/strict';

import { parseState } from '../js/schema.js';
import { rawSample, sampleState } from './helpers.mjs';

test('the sample parses and keeps every ticket', () => {
  const state = sampleState();
  assert.equal(state.tickets.length, rawSample.tickets.length);
  assert.equal(state.dropped, 0);
  assert.deepEqual(state.board_stages, rawSample.board_stages);
  assert.equal(state.cost.billing.billed_usd, 13.0194);
  assert.equal(state.agents.length, 11);
});

test('wrong shapes are errors, not crashes', () => {
  assert.equal(parseState(null).status, 'error');
  assert.equal(parseState([]).status, 'error');
  assert.equal(parseState('x').status, 'error');
  const v2 = parseState({ version: 2, tickets: [] });
  assert.equal(v2.status, 'error');
  assert.match(v2.message, /found 2/);
  assert.match(parseState({ tickets: [] }).message, /found none/);
  assert.equal(parseState({ version: 1, tickets: 'nope' }).status, 'error');
});

test('a bare version-1 document is valid and empty', () => {
  const r = parseState({ version: 1 });
  assert.equal(r.status, 'ok');
  assert.deepEqual(r.state.tickets, []);
  assert.equal(r.state.environments.source, 'none');
  assert.equal(r.state.cost.billing, null);
  assert.equal(r.state.cost.caps.halt_usd, 22);
  assert.deepEqual(r.state.agents, []);
  assert.equal(r.state.ledger.last_tick, null);
});

test('every optional ticket field may be missing or null', () => {
  const r = parseState({ version: 1, tickets: [{ issue: 7 }, { issue: 8, escalation: null, pr: null, cost: null, gates: null, hops: null, qa: null, reviews: 5, stage: 'nope' }] });
  assert.equal(r.state.tickets.length, 2);
  const t = r.state.tickets[1];
  assert.equal(t.stage, 'backlog');
  assert.ok(t.flags.includes('unknown-stage'));
  assert.deepEqual(t.hops, []);
  assert.deepEqual(t.reviews, []);
  assert.equal(t.cost.usd, 0);
  assert.equal(t.cost.cap_usd, 3);
  assert.equal(t.escalation, null);
});

test('unusable tickets are dropped and counted, duplicates collapse', () => {
  const r = parseState({ version: 1, tickets: [{ issue: 1 }, { issue: 1 }, { issue: 'x' }, null, 'str', { issue: -4 }, { title: 'no number' }] });
  assert.equal(r.state.tickets.length, 1);
  assert.equal(r.state.dropped, 6);
});

test('strings stay strings and numbers stay numbers', () => {
  const r = parseState({ version: 1, tickets: [{ issue: 3, title: 42, cost: { usd: '9' }, agent_runs: [{ agent: null, in: 'x' }] }] });
  const t = r.state.tickets[0];
  assert.equal(t.title, '42');
  assert.equal(t.cost.usd, 0);
  assert.equal(t.agent_runs[0].agent, 'unknown');
  assert.equal(t.agent_runs[0].in, 0);
});

test('agents: unknown state becomes unknown, string errors are kept', () => {
  const r = parseState({ version: 1, agents: [{ name: 'a', state: 'on-fire', last_error: 'boom' }, { state: 'idle' }, 7] });
  assert.equal(r.state.agents.length, 1);
  assert.equal(r.state.agents[0].state, 'unknown');
  assert.equal(r.state.agents[0].last_error.detail, 'boom');
});

test('billing without a number is not billing', () => {
  assert.equal(parseState({ version: 1, cost: { billing: { billed_usd: 'lots' } } }).state.cost.billing, null);
  assert.equal(parseState({ version: 1, cost: { billing: { billed_usd: 2, by_meter: [{ name: 'a', usd: 2 }] } } }).state.cost.billing.by_meter.length, 1);
});

test('staging reads deployed_at, production reads promoted_at', () => {
  const state = sampleState();
  assert.equal(state.environments.staging.at, '2026-10-10T17:46:00Z', 'sample staging row only carries promoted_at');
  const r = parseState({ version: 1, environments: { source: 'x', staging: { deployed_at: '2026-01-01T00:00:00Z', promoted_at: '2026-01-02T00:00:00Z' }, prod: { deployed_at: '2026-01-01T00:00:00Z', promoted_at: '2026-01-02T00:00:00Z' } } });
  assert.equal(r.state.environments.staging.at, '2026-01-01T00:00:00Z');
  assert.equal(r.state.environments.prod.at, '2026-01-02T00:00:00Z');
});
