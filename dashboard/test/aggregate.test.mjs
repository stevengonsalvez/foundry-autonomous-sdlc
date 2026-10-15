import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

import {
  costSummary,
  defectSummary,
  gateRates,
  headlineCounts,
  issueLinks,
  median,
  normalizeIssue,
  parseMetrics,
  stageDurations,
} from '../js/aggregate.js';
import { formatDuration, formatPercent, formatTimestamp, formatUsd, stageLabel, truncate } from '../js/format.js';

const fixture = JSON.parse(await readFile(new URL('./fixtures/metrics.sample.json', import.meta.url), 'utf8'));
const parsedFixture = parseMetrics(fixture);
const issues = parsedFixture.metrics.issues;
const byNumber = (n) => issues.find((i) => i.number === n);
const byRef = (r) => issues.find((i) => i.ref === r);

const ok = (raw) => {
  const r = parseMetrics(raw);
  assert.equal(r.status, 'ok');
  return r.metrics;
};
const minimal = (extra = {}) => ({ version: 1, issues: [{ number: 1, ...extra }] });

test('median handles empty, odd, even and non-numeric input', () => {
  assert.equal(median([]), null);
  assert.equal(median(undefined), null);
  assert.equal(median([5]), 5);
  assert.equal(median([9, 1, 5]), 5);
  assert.equal(median([1, 2, 3, 10]), 2.5);
  assert.equal(median([4, NaN, null, 'x', 2]), 3);
});

test('parseMetrics: nothing published is empty, not an error', () => {
  assert.equal(parseMetrics(null).status, 'empty');
  assert.equal(parseMetrics({}).status, 'empty');
  const r = parseMetrics({ version: 1, generated_at: '2026-10-10T12:00:00Z', issues: [] });
  assert.equal(r.status, 'empty');
  assert.equal(r.metrics.generatedAt, '2026-10-10T12:00:00Z');
  assert.equal(parseMetrics({ version: 1 }).status, 'empty');
});

test('parseMetrics: wrong shape or schema version is an error', () => {
  assert.equal(parseMetrics([]).status, 'error');
  assert.equal(parseMetrics('text').status, 'error');
  const v2 = parseMetrics({ version: 2, issues: [] });
  assert.equal(v2.status, 'error');
  assert.match(v2.message, /found 2/);
  assert.match(parseMetrics({ issues: [{ number: 1 }] }).message, /found none/);
  assert.equal(parseMetrics({ version: 1, issues: 'nope' }).status, 'error');
});

test('parseMetrics: unusable issues are dropped and counted', () => {
  const m = ok({ version: 1, issues: [{ number: 1 }, { number: 'x' }, null, { title: 'no number' }, { number: -3 }] });
  assert.equal(m.issues.length, 1);
  assert.equal(m.skipped, 4);
});

test('parseMetrics: repo slug is validated before it can become a link', () => {
  assert.equal(ok({ ...minimal(), repo: 'a/b' }).repo, 'a/b');
  assert.equal(ok({ ...minimal(), repo: 'javascript:alert(1)//x/y' }).repo, null);
  assert.equal(ok({ ...minimal(), repo: 'a/b/c' }).repo, null);
});

test('normalizeIssue tolerates a bare issue with every optional field missing', () => {
  const i = normalizeIssue({ number: 7 });
  assert.equal(i.title, 'Issue #7');
  assert.equal(i.outcome, 'unknown');
  assert.deepEqual(i.stages, []);
  assert.deepEqual(i.cost, { usd: null, model: null, coder: null, calls: null });
  assert.equal(i.pr, null);
  assert.equal(i.release, null);
  assert.equal(i.resolutionSeconds, null);
});

test('normalizeIssue strips label prefixes and rejects bad severities', () => {
  const i = normalizeIssue({ number: 1, type: 'type:bug', owner: 'owner:api', severity: 's9' });
  assert.equal(i.type, 'bug');
  assert.equal(i.owner, 'api');
  assert.equal(i.severity, null);
});

test('normalizeIssue sums cost parts when usd is missing', () => {
  assert.equal(normalizeIssue({ number: 1, cost: { model_usd: 0.25, coder_usd: 0.5 } }).cost.usd, 0.75);
  assert.equal(normalizeIssue({ number: 1, cost: { model_usd: 0.25 } }).cost.usd, 0.25);
  assert.equal(normalizeIssue({ number: 1, cost: { usd: -1 } }).cost.usd, null);
});

test('stage seconds missing are derived from the next stage, otherwise unknown', () => {
  const i = normalizeIssue({
    number: 1,
    stages: [
      { stage: 'stage:ready', entered_at: '2026-10-10T10:00:00Z' },
      { stage: 'stage:feasible', entered_at: '2026-10-10T10:01:30Z' },
      { stage: 'stage:tests-written', entered_at: '2026-10-10T10:02:00Z' },
    ],
  });
  assert.deepEqual(i.stages.map((s) => s.seconds), [90, 30, null]);
});

test('resolution falls back to opened_at to stage:merged when not given', () => {
  const i = normalizeIssue({
    number: 1,
    type: 'bug',
    opened_at: '2026-10-10T10:00:00Z',
    stages: [{ stage: 'stage:merged', entered_at: '2026-10-10T11:00:00Z' }],
  });
  assert.equal(i.resolutionSeconds, 3600);
});

test('stageDurations: empty input', () => {
  const d = stageDurations([]);
  assert.deepEqual(d.stages, []);
  assert.deepEqual(d.perIssue, []);
  assert.equal(d.medianTotal, null);
  assert.equal(d.maxTotal, 0);
});

test('stageDurations: medians follow state machine order and ignore unknown durations', () => {
  const d = stageDurations(issues);
  assert.deepEqual(
    d.stages.map((s) => s.stage),
    ['stage:needs-refinement', 'stage:ready', 'stage:feasible', 'stage:tests-written', 'stage:building', 'stage:in-review', 'stage:merged'],
  );
  // issue 12 is still building: it is left out of the median
  const building = d.stages.find((s) => s.stage === 'stage:building');
  assert.equal(building.count, 4);
  assert.equal(building.median, median([3120, 5280, 2160, 8640]));
  // issue 13 is still in tests-written: left out, not counted as zero
  const tests = d.stages.find((s) => s.stage === 'stage:tests-written');
  assert.equal(tests.count, 6);
  assert.equal(d.perIssue.find((p) => p.ref === 13).hasOpen, true);
});

test('stageDurations: repeated stages in one issue are summed, unknown stages appended last', () => {
  const m = ok({
    version: 1,
    issues: [
      {
        number: 1,
        stages: [
          { stage: 'stage:needs-refinement', seconds: 100 },
          { stage: 'stage:ready', seconds: 10 },
          { stage: 'stage:needs-refinement', seconds: 50 },
          { stage: 'stage:custom', seconds: 5 },
        ],
      },
    ],
  });
  const d = stageDurations(m.issues);
  assert.deepEqual(d.stages.map((s) => [s.stage, s.median]), [
    ['stage:needs-refinement', 150],
    ['stage:ready', 10],
    ['stage:custom', 5],
  ]);
  assert.equal(d.perIssue[0].total, 165);
});

test('stageDurations: an escalated issue with no PR still contributes its stages', () => {
  const p = stageDurations(issues).perIssue.find((x) => x.ref === 5);
  assert.equal(byNumber(5).pr, null);
  assert.equal(p.total, 345);
  assert.equal(p.outcome, 'escalated');
  // the terminal escalated:* entry has no duration and is not charted
  assert.deepEqual(p.segments.map((s) => s.stage), ['stage:needs-refinement', 'stage:ready']);
});

test('stageDurations: issue with no stages yields an empty row and no total', () => {
  const d = stageDurations(ok(minimal()).issues);
  assert.equal(d.perIssue[0].total, 0);
  assert.equal(d.medianTotal, null);
  assert.equal(d.totalCount, 0);
});

test('gateRates: first attempt vs eventual from gate_attempts', () => {
  const rates = gateRates(issues, parsedFixture.metrics.gatePassRates);
  const coverage = rates.find((g) => g.gate === 'coverage');
  assert.deepEqual([coverage.first.pass, coverage.first.total], [4, 5]);
  assert.deepEqual([coverage.eventual.pass, coverage.eventual.total], [5, 5]);
  assert.equal(coverage.first.rate, 0.8);
  assert.deepEqual(coverage.runs, { pass: 6, fail: 1 });
  const e2e = rates.find((g) => g.gate === 'e2e');
  assert.equal(e2e.eventual.rate, 0.8);
});

test('gateRates: gates come out in pipeline order', () => {
  const names = gateRates(issues).map((g) => g.gate);
  assert.deepEqual(names, ['test', 'coverage', 'e2e', 'gitleaks', 'tdd-order', 'agent-scope', 'evals']);
});

test('gateRates: without attempts the first-attempt rate is null, not invented', () => {
  const m = ok({ version: 1, issues: [{ number: 1, gates: { test: 'success' } }, { number: 2, gates: { test: 'failure' } }] });
  const test = gateRates(m.issues).find((g) => g.gate === 'test');
  assert.equal(test.first.rate, null);
  assert.equal(test.eventual.rate, 0.5);
  assert.equal(test.runs, null);
});

test('gateRates: pending and skipped results are not counted; unknown gates are kept', () => {
  const m = ok({ version: 1, issues: [{ number: 1, gates: { test: 'pending', lint: 'success', e2e: 'skipped' } }] });
  const rates = gateRates(m.issues);
  assert.equal(rates.find((g) => g.gate === 'test').eventual.total, 0);
  assert.equal(rates.find((g) => g.gate === 'e2e').eventual.rate, null);
  assert.equal(rates.at(-1).gate, 'lint');
});

test('gateRates: empty input has no rates', () => {
  for (const g of gateRates([])) {
    assert.equal(g.first.rate, null);
    assert.equal(g.eventual.rate, null);
  }
});

test('costSummary: totals, cap and per issue line', () => {
  const c = costSummary(parsedFixture.metrics);
  assert.equal(c.total, 1.9915);
  assert.equal(c.cap, 35);
  assert.ok(Math.abs(c.percentOfCap - 5.69) < 0.01);
  assert.ok(Math.abs(c.remaining - 33.0085) < 1e-9);
  assert.equal(c.haltReached, false);
  assert.deepEqual(c.rows.filter((r) => r.overLine).map((r) => r.ref), []); // none is over the 3 USD line
  assert.equal(c.callsTotal, 82);
  assert.ok(Math.abs(c.rowTotal - 1.9503) < 1e-9);
  assert.equal(c.orchestrator, 0.0412);
  assert.ok(Math.abs(c.accounted - c.total) < 1e-9);
  // coder cost is the coder runtime plus the model spend of its fallback loop
  assert.ok(Math.abs(c.rows.find((r) => r.ref === 10).coder - 0.13) < 1e-9);
});

test('costSummary: sums rows when totals.usd is missing, tolerates issues without cost', () => {
  const m = ok({ version: 1, issues: [{ number: 1, cost: { usd: 0.5 } }, { number: 2 }] });
  const c = costSummary(m);
  assert.equal(c.total, 0.5);
  assert.equal(c.totalReported, false);
  assert.equal(c.rows[1].usd, null);
});

test('costSummary: over the cap is clamped for the bar but not for the figure', () => {
  const m = ok({ version: 1, totals: { usd: 40 }, issues: [{ number: 1, cost: { usd: 40 } }] });
  const c = costSummary(m);
  assert.equal(c.fractionOfCap, 1);
  assert.equal(c.total, 40);
  assert.equal(c.remaining, 0);
  assert.equal(c.haltReached, true);
});

test('defectSummary: bugs only, grouped by owner, open bug has no resolution', () => {
  const d = defectSummary(issues);
  assert.deepEqual(d.bugs.map((b) => b.ref), [6, 13]);
  assert.equal(d.bugs[0].resolutionSeconds, 3155);
  assert.equal(d.bugs[1].resolutionSeconds, null);
  assert.deepEqual(d.byOwner.map((o) => [o.owner, o.count, o.medianResolution]), [
    ['api', 1, 3155],
    ['web', 1, null],
  ]);
  assert.equal(d.medianResolution, 3155);
});

test('defectSummary: no bugs, and bugs with no owner', () => {
  assert.deepEqual(defectSummary([]).bugs, []);
  const m = ok({ version: 1, issues: [{ number: 1, type: 'bug' }, { number: 2, type: 'feature' }] });
  const d = defectSummary(m.issues);
  assert.deepEqual(d.byOwner.map((o) => o.owner), ['unassigned']);
  assert.equal(d.medianResolution, null);
});

test('headlineCounts prefers totals, falls back to counting', () => {
  assert.deepEqual(headlineCounts(parsedFixture.metrics), { issues: 8, released: 4, escalated: 2 });
  const m = ok({ version: 1, issues: [{ number: 1, outcome: 'released' }, { number: 2, outcome: 'escalated' }, { number: 3, outcome: 'open' }] });
  assert.deepEqual(headlineCounts(m), { issues: 3, released: 1, escalated: 1 });
});

test('issueLinks derive from repo and numbers, and degrade without a valid repo', () => {
  const links = issueLinks('o/r', { number: 12, pr: 13, release: 'v0.2.0' });
  assert.equal(links.issue, 'https://github.com/o/r/issues/12');
  assert.equal(links.pr, 'https://github.com/o/r/pull/13');
  assert.equal(links.release, 'https://github.com/o/r/releases/tag/v0.2.0');
  const bare = issueLinks('o/r', { number: 5, pr: null, release: null });
  assert.equal(bare.pr, null);
  assert.equal(bare.release, null);
  assert.deepEqual(issueLinks(null, { number: 1, pr: 2, release: 'v1' }), { repo: null, issue: null, pr: null, release: null });
  assert.equal(issueLinks('bad repo', { number: 1, pr: null, release: null }).issue, null);
  assert.equal(issueLinks('o/r', { number: 1, pr: null, release: 'v1/../x' }).release, 'https://github.com/o/r/releases/tag/v1%2F..%2Fx');
});

test('a pull request entry without an issue number is kept, identified by its pr', () => {
  const pr = byRef(9);
  assert.equal(pr.number, null);
  assert.equal(pr.kind, 'pr');
  assert.equal(pr.label, 'PR #9');
  assert.equal(pr.scenario, 'd-maintenance');
  const links = issueLinks('o/r', pr);
  assert.equal(links.issue, null);
  assert.equal(links.pr, 'https://github.com/o/r/pull/9');
  assert.equal(normalizeIssue({ number: null, kind: 'pr' }), null);
  assert.equal(normalizeIssue({ number: null, pr: null }), null);
});

test('the current stage is measured up to generated_at and kept out of medians', () => {
  const m = ok({
    version: 1,
    generated_at: '2026-10-10T12:00:00Z',
    issues: [
      {
        number: 1,
        stages: [
          { stage: 'stage:ready', entered_at: '2026-10-10T10:00:00Z', seconds: 60 },
          { stage: 'stage:building', entered_at: '2026-10-10T10:01:00Z', seconds: 0, in_progress: true },
        ],
      },
    ],
  });
  const [issue] = m.issues;
  assert.equal(issue.stages[1].inProgress, true);
  assert.equal(issue.stages[1].seconds, 7140);
  const d = stageDurations(m.issues);
  assert.deepEqual(d.stages.map((s) => s.stage), ['stage:ready']);
  assert.deepEqual(d.perIssue[0].segments.map((s) => [s.stage, s.open]), [['stage:ready', false], ['stage:building', true]]);
  assert.equal(d.medianTotal, null);
});

test('an in progress stage has unknown duration when generated_at is missing', () => {
  const m = ok({ version: 1, issues: [{ number: 1, stages: [{ stage: 'stage:building', entered_at: '2026-10-10T10:01:00Z', seconds: 0, in_progress: true }] }] });
  assert.equal(m.issues[0].stages[0].seconds, null);
  assert.deepEqual(stageDurations(m.issues).stages, []);
});

test('terminal stages carry no duration', () => {
  const m = ok({ version: 1, issues: [{ number: 1, stages: [{ stage: 'stage:ready', seconds: 5 }, { stage: 'escalated:cost-cap', seconds: 0 }, { stage: 'stage:released', seconds: 0 }] }] });
  assert.deepEqual(stageDurations(m.issues).perIssue[0].segments.map((s) => s.stage), ['stage:ready']);
});

test('escalation reason loses its label prefix', () => {
  assert.equal(byNumber(5).escalation, 'not-agent-suitable');
  assert.equal(normalizeIssue({ number: 1, escalation: 'escalated:cost-cap' }).escalation, 'cost-cap');
  assert.equal(normalizeIssue({ number: 1, escalation: null }).escalation, null);
});

test('gateRates prefers the reported first-attempt counts and falls back to gate_attempts', () => {
  const reported = { e2e: { pass: 9, fail: 1, firstPass: 7, firstFail: 3 } };
  const e2e = gateRates(issues, reported).find((g) => g.gate === 'e2e');
  assert.deepEqual([e2e.first.pass, e2e.first.total], [7, 10]);
  assert.deepEqual(e2e.runs, { pass: 9, fail: 1 });
  const derived = gateRates(issues, { e2e: { pass: 9, fail: 1, firstPass: null, firstFail: null } }).find((g) => g.gate === 'e2e');
  assert.equal(derived.first.total, 5);
});

test('the fixture reports first-attempt counts that agree with its attempts', () => {
  const fromReport = gateRates(issues, parsedFixture.metrics.gatePassRates);
  const fromAttempts = gateRates(issues, {});
  for (const g of fromReport) {
    const other = fromAttempts.find((x) => x.gate === g.gate);
    assert.deepEqual([g.first.pass, g.first.total], [other.first.pass, other.first.total], g.gate);
  }
});

test('formatting helpers', () => {
  assert.equal(formatDuration(null), '-');
  assert.equal(formatDuration(0), '0s');
  assert.equal(formatDuration(59.6), '1m');
  assert.equal(formatDuration(90), '1m 30s');
  assert.equal(formatDuration(3600), '1h');
  assert.equal(formatDuration(5400), '1h 30m');
  assert.equal(formatDuration(90000), '1d 1h');
  assert.equal(formatDuration(-5), '-');
  assert.equal(formatUsd(0.0123), '$0.0123');
  assert.equal(formatUsd(1.8515, 2), '$1.85');
  assert.equal(formatUsd(undefined), '-');
  assert.equal(formatPercent(0.8333), '83%');
  assert.equal(formatPercent(null), 'n/a');
  assert.equal(formatTimestamp('2026-10-10T12:00:00Z'), '2026-10-10 12:00 UTC');
  assert.equal(formatTimestamp('nope'), '-');
  assert.equal(stageLabel('stage:in-review'), 'In review');
  assert.equal(stageLabel('stage:some_new-thing'), 'Some new thing');
  assert.equal(truncate('abcdefghij', 5), 'abcd…');
  assert.equal(truncate('abc', 5), 'abc');
});

test('the dashboard source contains no em dashes', async () => {
  const files = ['aggregate.js', 'charts.js', 'dom.js', 'format.js', 'main.js', 'panels.js'];
  for (const f of files) {
    const body = await readFile(new URL(`../js/${f}`, import.meta.url), 'utf8');
    assert.ok(!body.includes(String.fromCharCode(0x2014)), `${f} contains an em dash`);
  }
});
