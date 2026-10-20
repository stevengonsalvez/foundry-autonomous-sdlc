import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  billingSummary,
  boardColumns,
  COST_BANDS,
  costBand,
  costRows,
  emptyFilters,
  escalationList,
  failedGate,
  flaggedIssue,
  freshness,
  GATE_STATUSES,
  gateOutcome,
  gateStatus,
  isNewer,
  isOpenEscalation,
  openEscalations,
  pipelineChain,
  releaseRows,
  resolvedEscalations,
  rollbackRows,
  scenarioRows,
  sortRows,
  stageDurations,
  stageEntries,
  tddOrder,
  timeInStage,
  trailGroups,
  withPending,
} from '../js/model.js';
import { pendingFromIssues } from '../js/data.js';
import { parseState } from '../js/schema.js';
import { NOW, rawIssues, sampleState } from './helpers.mjs';

const ticket = (state, n) => state.tickets.find((t) => t.issue === n);

test('board columns match the ledger counts, in board order', () => {
  const state = sampleState();
  const cols = boardColumns(state, [], emptyFilters(), NOW);
  assert.deepEqual(cols.map((c) => c.stage), state.board_stages);
  for (const c of cols) assert.equal(c.tickets.length, state.flow.counts[c.stage], c.stage);
  assert.equal(cols.reduce((n, c) => n + c.tickets.length, 0), 6);
});

test('filters: type, number, title, finished-and-old', () => {
  const state = sampleState();
  const count = (filters) => boardColumns(state, [], filters, NOW).reduce((n, c) => n + c.tickets.length, 0);
  assert.equal(count({ ...emptyFilters(), types: new Set(['bug']) }), 1);
  assert.equal(count({ ...emptyFilters(), types: new Set(['bug', 'maintenance']) }), 2);
  assert.equal(count({ ...emptyFilters(), query: '24' }), 1);
  assert.equal(count({ ...emptyFilters(), query: '#24' }), 1);
  assert.equal(count({ ...emptyFilters(), query: 'lowercase' }), 1);
  assert.equal(count({ ...emptyFilters(), query: 'LOWERCASE tracking' }), 1);
  assert.equal(count({ ...emptyFilters(), query: 'zzz' }), 0);
  assert.equal(count({ ...emptyFilters(), hideOld: true }), 6, 'nothing is older than 7 days yet');
  const later = NOW + 10 * 86_400_000;
  const hidden = boardColumns(state, [], { ...emptyFilters(), hideOld: true }, later).reduce((n, c) => n + c.tickets.length, 0);
  assert.ok(hidden < 6 && hidden >= 1, `finished old tickets are hidden (left ${hidden})`);
  assert.ok(boardColumns(state, [], { ...emptyFilters(), hideOld: true }, later).find((c) => c.stage === 'staging').tickets.length === 1, 'unfinished tickets stay');
});

test('pending intake: owner issues only, not pull requests, replaced once the ledger has them', () => {
  const pending = pendingFromIssues(rawIssues);
  assert.deepEqual(pending.map((p) => p.issue), [99, 24]);
  assert.equal(pending[0].type, 'feature');
  assert.equal(pending[0].pending, true);
  assert.deepEqual(pending[0].flags, ['waiting-for-ledger']);
  const state = sampleState();
  const merged = withPending(state.tickets, pending);
  assert.equal(merged.length, 23, 'issue 24 is already in the ledger, so only 99 is added');
  assert.equal(merged.find((t) => t.issue === 24).pending, false);
  const backlog = boardColumns(state, pending, emptyFilters(), NOW)[0];
  assert.deepEqual(backlog.tickets.map((t) => t.issue), [99]);
  assert.deepEqual(pendingFromIssues(null), []);
  assert.deepEqual(pendingFromIssues([{ number: 1, title: 'x', user: { login: 'STEVENGONSALVEZ' } }, { number: 2, title: 5, user: { login: 'stevengonsalvez' } }, null]).map((p) => p.issue), [1]);
});

test('time in stage: terminal stages come from the deploy record', () => {
  const state = sampleState();
  const t24 = ticket(state, 24);
  assert.equal(t24.stage, 'prod');
  const entered = timeInStage(t24, NOW);
  assert.equal(entered.since, '2026-10-10T17:46:00Z');
  assert.equal(Math.round(entered.seconds), (NOW - Date.parse('2026-10-10T17:46:00Z')) / 1000);
  const t25 = ticket(state, 25);
  assert.equal(timeInStage(t25, NOW).since, '2026-10-10T17:15:00Z', 'escalated at the rollback');
  const t23 = ticket(state, 23);
  assert.equal(timeInStage(t23, NOW).since, t23.stage_history.at(-2).at, 'a run of equal stages counts from its first entry');
});

test('stage durations: loops count as visits, closed stages are not measured to now', () => {
  const state = sampleState();
  const d = Object.fromEntries(stageDurations(ticket(state, 24), NOW).map((x) => [x.stage, x]));
  assert.equal(d.building.visits, 2);
  assert.equal(d.building.seconds, 278 + 887);
  assert.equal(d.refining.seconds, 69 + 33);
  assert.equal(d.staging.open, false, 'staging ended when prod began');
  assert.equal(d.prod.open, true);
  const entries = stageEntries(ticket(state, 24), NOW);
  assert.equal(entries.at(-1).stage, 'prod');
  assert.equal(entries.at(-1).synthetic, true);
});

test('gates: pass, fail, not run, derived review, first-attempt', () => {
  const state = sampleState();
  const t25 = ticket(state, 25);
  assert.equal(gateStatus(t25, 'smoke').status, 'fail');
  assert.equal(gateStatus(t25, 'soak').status, 'none');
  assert.equal(gateStatus(t25, 'test').status, 'pass');
  assert.equal(gateStatus(t25, 'test').firstPass, true);
  const review = gateStatus(ticket(state, 24), 'review');
  assert.equal(review.status, 'pass');
  assert.equal(review.derived, true);
  const t38 = ticket(state, 38);
  assert.equal(gateStatus(t38, 'review').status, 'fail', 'request-changes is not a pass');
  assert.equal(gateStatus(t38, 'test').attempts, 2);
  assert.equal(gateStatus(t38, 'test').firstPass, false);
});

test('delivery chain: staging, skipped, then production for ticket 24', () => {
  const chain = Object.fromEntries(pipelineChain(ticket(sampleState(), 24)).map((n) => [n.key, n.status]));
  assert.deepEqual(chain, { staging: 'skipped', smoke: 'pass', soak: 'pass', prod: 'pass' });
  const rolled = Object.fromEntries(pipelineChain(ticket(sampleState(), 25)).map((n) => [n.key, n.status]));
  assert.deepEqual(rolled, { staging: 'fail', smoke: 'fail', soak: 'none', prod: 'none' });
});

test('tests-first order', () => {
  assert.equal(tddOrder([{ kind: 'test' }, { kind: 'feat' }]).status, 'tests-first');
  assert.equal(tddOrder([{ kind: 'feat' }, { kind: 'test' }]).status, 'impl-first');
  assert.equal(tddOrder([{ kind: 'docs' }, { kind: 'test' }]).status, 'unknown');
  assert.equal(tddOrder([]).status, 'unknown');
});

test('billing story: the gap in plain words, honest when unread', () => {
  const state = sampleState();
  const s = billingSummary(state.cost);
  assert.equal(s.sentence, 'Azure billed 13.02 USD; the ledger estimated 1.87 USD; the ledger undercounts hosted compute by 7.0x.');
  assert.equal(s.tone, 'info', '13.02 USD is under the 32 USD halt line');
  assert.equal(s.overCap, false);
  assert.equal(s.overHalt, false);
  const over = structuredClone(state.cost);
  over.billing.billed_usd = 36;
  const o = billingSummary(over);
  assert.equal(o.tone, 'danger');
  assert.equal(o.overCap, true);
  assert.equal(o.overHalt, true);
  const calm = structuredClone(state.cost);
  calm.billing.billed_usd = 1.5;
  calm.gap = null;
  const c = billingSummary(calm);
  assert.equal(c.tone, 'info');
  assert.doesNotMatch(c.sentence, /undercounts/);
  const unread = structuredClone(state.cost);
  unread.billing = null;
  unread.gap = null;
  const u = billingSummary(unread);
  assert.equal(u.read, false);
  assert.equal(u.billed, null);
  assert.match(u.sentence, /not read yet/);
});

test('cost rows sort and flag over-cap', () => {
  const state = sampleState();
  const t23 = state.tickets.find((t) => t.issue === 23);
  if (t23) t23.cost.cap_used_pct = 120;
  const t27 = state.tickets.find((t) => t.issue === 27);
  if (t27) t27.cost.cap_used_pct = 80;
  const rows = costRows(state);
  const top = sortRows(rows, 'usd', 'desc')[0];
  assert.equal(top.issue, 27);
  assert.equal(sortRows(rows, 'usd', 'asc')[0].issue, 2);
  assert.equal(rows.find((r) => r.issue === 23).over, true);
  assert.equal(rows.find((r) => r.issue === 27).over, false);
  state.tickets[0].cost.cap_used_pct = 140;
  assert.equal(costRows(state)[0].over, true);
});

test('escalations newest first, with the rollback one included', () => {
  const state = sampleState();
  const list = escalationList(state);
  assert.equal(list.length, 18);
  assert.ok(list.some((t) => t.issue === 25));
  const times = list.map((t) => Date.parse(t.escalation.at));
  assert.deepEqual(times, [...times].sort((a, b) => b - a));
  assert.equal(openEscalations(state).length, 2);
  assert.equal(resolvedEscalations(state).length, 16);
  const resTimes = resolvedEscalations(state).map((t) => Date.parse(t.escalation.resolved.at));
  assert.deepEqual(resTimes, [...resTimes].sort((a, b) => b - a));
  assert.equal(isOpenEscalation(list.find((t) => t.issue === 25)), true);
  assert.equal(isOpenEscalation(list.find((t) => t.issue === 2)), false);
});

test('old state without resolved field normalizes safely and renders', () => {
  const raw = sampleState();
  for (const t of raw.tickets) {
    if (t.escalation) {
      delete t.escalation.resolved;
      delete t.escalation.open;
    }
  }
  const res = parseState(raw);
  assert.equal(res.status, 'ok');
  const parsed = res.state;
  for (const t of parsed.tickets) {
    if (t.escalation) {
      assert.equal(t.escalation.resolved, null);
      assert.equal(t.escalation.open, true);
      assert.equal(isOpenEscalation(t), true);
    }
  }
  const cols = boardColumns(parsed, [], emptyFilters(), NOW);
  assert.equal(cols.find((c) => c.stage === 'escalated').tickets.length, 18);
  assert.equal(openEscalations(parsed).length, 18);
  assert.equal(resolvedEscalations(parsed).length, 0);
});

test('trail groups: questions, reviews, CI triage, filterable', () => {
  const state = sampleState();
  const all = trailGroups(state);
  const g24 = all.find((g) => g.ticket.issue === 24);
  assert.deepEqual(g24.items.map((i) => i.kind), ['qa', 'review']);
  assert.equal(g24.items[0].data.length, 4);
  assert.ok(all.find((g) => g.ticket.issue === 27).items.some((i) => i.kind === 'ci'));
  assert.ok(trailGroups(state, { kind: 'qa' }).every((g) => g.items.every((i) => i.kind === 'qa')));
  assert.equal(trailGroups(state, { issue: 24 }).length, 1);
  assert.equal(trailGroups(state, { issue: 2 }).length, 0);
});

test('environments: rollbacks, releases, scenarios', () => {
  const state = sampleState();
  const rb = rollbackRows(state);
  assert.equal(rb.length, 1);
  assert.equal(failedGate(rb[0].reason), 'smoke');
  assert.equal(flaggedIssue(rb[0]), 25);
  assert.equal(failedGate('nothing to see'), null);
  const rel = releaseRows(state);
  assert.deepEqual(rel.map((r) => r.outcome), ['ok', 'skipped', 'failed', 'ok', 'pending']);
  assert.deepEqual(rel[0].issues, [24, 40]);
  const sc = scenarioRows(state);
  assert.deepEqual(sc.map((s) => s.scenario), ['a', 'b', 'c', 'd', 'd-maintenance']);
  assert.equal(sc.reduce((n, s) => n + s.tickets.length, 0), 22);
});

test('freshness and which document is newer', () => {
  const state = sampleState();
  assert.equal(freshness(state, Date.parse('2026-10-11T20:14:00Z')).stale, false);
  assert.equal(freshness(state, Date.parse('2026-10-11T20:15:01Z')).stale, true);
  assert.equal(freshness({ generated_at: null }, NOW).stale, true);
  const a = { generated_at: '2026-10-11T20:05:00Z', seq: 1 };
  const b = { generated_at: '2026-10-11T20:06:00Z', seq: 1 };
  assert.equal(isNewer(b, a), true);
  assert.equal(isNewer(a, b), false);
  assert.equal(isNewer(a, a), false);
  assert.equal(isNewer({ ...a, seq: 2 }, a), true);
  assert.equal(isNewer(a, null), true);
  assert.equal(isNewer({ generated_at: null, seq: 9 }, a), false);
});

test('costBand returns valid COST_BANDS member over all ranges', () => {
  const inputs = [-1, 0, 74.9, 75, 100, 100.1, 1e9];
  for (const pct of inputs) {
    const band = costBand(pct);
    assert.ok(COST_BANDS.includes(band), `costBand(${pct}) returned "${band}" which is not in COST_BANDS`);
  }
  assert.equal(costBand(-1), 'ok');
  assert.equal(costBand(0), 'ok');
  assert.equal(costBand(74.9), 'ok');
  assert.equal(costBand(75), 'high');
  assert.equal(costBand(100), 'high');
  assert.equal(costBand(100.1), 'over');
  assert.equal(costBand(1e9), 'over');
});

test('gateOutcome returns valid GATE_STATUSES member', () => {
  const cases = ['success', 'passed', 'pass', 'failure', 'failed', 'error', 'timed_out', 'cancelled', 'rolled_back', 'in_progress', 'pending', 'queued', 'running', 'waiting', 'skipped', 'unknown', null, undefined];
  for (const raw of cases) {
    const outcome = gateOutcome(raw);
    assert.ok(GATE_STATUSES.includes(outcome), `gateOutcome(${raw}) returned "${outcome}" not in GATE_STATUSES`);
  }
});
