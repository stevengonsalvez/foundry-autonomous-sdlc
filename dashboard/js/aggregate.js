// Pure aggregation over metrics.json (schema version 1, docs/architecture.md "Metrics").
// No DOM, no I/O: everything here is a function of its arguments so it can be unit tested.

export const SCHEMA_VERSION = 1;
export const COST_CAP_USD = 5;
export const ISSUE_COST_LINE_USD = 1;
export const HALT_USD = 4.5;

export const STAGE_ORDER = [
  'stage:needs-refinement',
  'stage:ready',
  'stage:feasible',
  'stage:tests-written',
  'stage:building',
  'stage:in-review',
  'stage:merged',
  'stage:released',
];

export const GATE_ORDER = ['test', 'coverage', 'e2e', 'gitleaks', 'tdd-order', 'agent-scope'];

const OUTCOMES = new Set(['released', 'escalated', 'open']);
const FAIL_RESULTS = new Set(['failure', 'failed', 'error', 'timed_out', 'cancelled', 'action_required']);
const REPO_PATTERN = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

const isRecord = (v) => typeof v === 'object' && v !== null && !Array.isArray(v);
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const nonNegative = (v) => (isNum(v) && v >= 0 ? v : null);
const str = (v) => (typeof v === 'string' && v.trim() !== '' ? v : null);

const toMs = (v) => {
  if (typeof v !== 'string') return null;
  const ms = Date.parse(v);
  return Number.isNaN(ms) ? null : ms;
};

export function median(values) {
  const sorted = (values ?? []).filter(isNum).sort((a, b) => a - b);
  if (sorted.length === 0) return null;
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

const sum = (values) => values.reduce((acc, v) => acc + v, 0);

const stripPrefix = (value, prefix) => {
  const s = str(value);
  if (s === null) return null;
  return s.startsWith(prefix) ? s.slice(prefix.length) : s;
};

export function classifyResult(result) {
  if (result === 'success') return 'pass';
  if (typeof result === 'string' && FAIL_RESULTS.has(result)) return 'fail';
  return 'other';
}

function normalizeStages(rawStages) {
  const list = Array.isArray(rawStages) ? rawStages.filter(isRecord).filter((s) => str(s.stage)) : [];
  const stages = list.map((s) => ({
    stage: s.stage,
    enteredMs: toMs(s.entered_at),
    enteredAt: toMs(s.entered_at) === null ? null : s.entered_at,
    seconds: nonNegative(s.seconds),
  }));
  // A missing duration is derived from the next stage's entry time when both are known.
  stages.forEach((s, i) => {
    if (s.seconds !== null) return;
    const next = stages[i + 1];
    if (next && s.enteredMs !== null && next.enteredMs !== null && next.enteredMs >= s.enteredMs) {
      s.seconds = (next.enteredMs - s.enteredMs) / 1000;
    }
  });
  return stages;
}

function normalizeCost(raw) {
  const cost = isRecord(raw) ? raw : {};
  const model = nonNegative(cost.model_usd);
  const coder = nonNegative(cost.coder_usd);
  let usd = nonNegative(cost.usd);
  if (usd === null && (model !== null || coder !== null)) usd = (model ?? 0) + (coder ?? 0);
  const calls = isNum(cost.calls) && cost.calls >= 0 ? Math.trunc(cost.calls) : null;
  return { usd, model, coder, calls };
}

function normalizeGates(raw) {
  const gates = {};
  if (isRecord(raw)) {
    for (const [name, result] of Object.entries(raw)) {
      if (typeof result === 'string') gates[name] = result;
    }
  }
  return gates;
}

function normalizeAttempts(raw) {
  const attempts = {};
  if (isRecord(raw)) {
    for (const [name, list] of Object.entries(raw)) {
      if (Array.isArray(list)) attempts[name] = list.filter((r) => typeof r === 'string');
    }
  }
  return attempts;
}

export function normalizeIssue(raw) {
  if (!isRecord(raw) || !Number.isInteger(raw.number) || raw.number <= 0) return null;
  const stages = normalizeStages(raw.stages);
  const type = stripPrefix(raw.type, 'type:');
  const merged = stages.find((s) => s.stage === 'stage:merged');
  const openedMs = toMs(raw.opened_at);

  let resolution = nonNegative(raw.resolution_seconds);
  if (resolution === null && openedMs !== null && merged && merged.enteredMs !== null && merged.enteredMs >= openedMs) {
    resolution = (merged.enteredMs - openedMs) / 1000;
  }

  const gates = normalizeGates(raw.gates);
  const attempts = normalizeAttempts(raw.gate_attempts);
  for (const [name, list] of Object.entries(attempts)) {
    if (!(name in gates) && list.length > 0) gates[name] = list[list.length - 1];
  }

  return {
    number: raw.number,
    title: str(raw.title) ?? `Issue #${raw.number}`,
    scenario: str(raw.scenario),
    type,
    outcome: OUTCOMES.has(raw.outcome) ? raw.outcome : 'unknown',
    openedAt: openedMs === null ? null : raw.opened_at,
    closedAt: toMs(raw.closed_at) === null ? null : raw.closed_at,
    stages,
    severity: /^s[1-4]$/.test(raw.severity ?? '') ? raw.severity : null,
    owner: stripPrefix(raw.owner, 'owner:'),
    resolutionSeconds: resolution,
    pr: Number.isInteger(raw.pr) && raw.pr > 0 ? raw.pr : null,
    release: str(raw.release),
    qualityScore: isNum(raw.quality_score) ? raw.quality_score : null,
    coderEngine: str(raw.coder_engine),
    cost: normalizeCost(raw.cost),
    gates,
    gateAttempts: attempts,
  };
}

/**
 * Validate and normalise a parsed metrics document.
 * Returns one of:
 *   { status: 'ok', metrics }      at least one usable issue
 *   { status: 'empty', metrics? }  nothing published yet (null, {}, or no issues)
 *   { status: 'error', message }   wrong shape or unsupported schema version
 */
export function parseMetrics(raw) {
  if (raw === null || raw === undefined) return { status: 'empty' };
  if (!isRecord(raw)) return { status: 'error', message: 'metrics.json is not a JSON object.' };
  if (Object.keys(raw).length === 0) return { status: 'empty' };
  if (raw.version !== SCHEMA_VERSION) {
    const found = raw.version === undefined ? 'none' : JSON.stringify(raw.version);
    return {
      status: 'error',
      message: `Unsupported metrics schema version (found ${found}, this dashboard reads version ${SCHEMA_VERSION}).`,
    };
  }
  if (raw.issues !== undefined && !Array.isArray(raw.issues)) {
    return { status: 'error', message: 'metrics.json has an "issues" field that is not a list.' };
  }

  const rawIssues = raw.issues ?? [];
  const issues = rawIssues.map(normalizeIssue).filter(Boolean);
  const totals = isRecord(raw.totals) ? raw.totals : {};
  const metrics = {
    version: SCHEMA_VERSION,
    generatedAt: toMs(raw.generated_at) === null ? null : raw.generated_at,
    repo: typeof raw.repo === 'string' && REPO_PATTERN.test(raw.repo) ? raw.repo : null,
    totals: {
      usd: nonNegative(totals.usd),
      issues: Number.isInteger(totals.issues) && totals.issues >= 0 ? totals.issues : null,
      released: Number.isInteger(totals.released) && totals.released >= 0 ? totals.released : null,
    },
    issues,
    skipped: rawIssues.length - issues.length,
    gatePassRates: normalizeRunCounts(raw.gate_pass_rates),
  };
  return issues.length === 0 ? { status: 'empty', metrics } : { status: 'ok', metrics };
}

function normalizeRunCounts(raw) {
  const out = {};
  if (!isRecord(raw)) return out;
  for (const [gate, v] of Object.entries(raw)) {
    if (isRecord(v) && isNum(v.pass) && isNum(v.fail) && v.pass >= 0 && v.fail >= 0) {
      out[gate] = { pass: v.pass, fail: v.fail };
    }
  }
  return out;
}

export function headlineCounts(metrics) {
  const { issues, totals } = metrics;
  return {
    issues: totals.issues ?? issues.length,
    released: totals.released ?? issues.filter((i) => i.outcome === 'released').length,
    escalated: issues.filter((i) => i.outcome === 'escalated').length,
  };
}

export function stageKey(stage) {
  return stripPrefix(stage, 'stage:') ?? 'unknown';
}

/**
 * Cycle time per stage. Stage order follows the state machine; unknown stages are appended.
 * Repeated stages within one issue (for example a second refinement round) are summed.
 * Stages whose duration is unknown (still running, or no following timestamp) are left out
 * of the median rather than counted as zero.
 */
export function stageDurations(issues) {
  const perIssue = [];
  const byStage = new Map();

  for (const issue of issues) {
    const seconds = new Map();
    for (const s of issue.stages) {
      if (s.seconds === null) continue;
      seconds.set(s.stage, (seconds.get(s.stage) ?? 0) + s.seconds);
    }
    for (const [stage, value] of seconds) {
      if (!byStage.has(stage)) byStage.set(stage, []);
      byStage.get(stage).push(value);
    }
    const order = [...seconds.keys()].sort(compareStages);
    perIssue.push({
      number: issue.number,
      title: issue.title,
      outcome: issue.outcome,
      segments: order.map((stage) => ({ stage, seconds: seconds.get(stage) })),
      total: sum([...seconds.values()]),
      hasUnknown: issue.stages.some((s) => s.seconds === null),
    });
  }

  const stages = [...byStage.keys()].sort(compareStages).map((stage) => {
    const values = byStage.get(stage);
    return { stage, median: median(values), count: values.length, max: Math.max(...values) };
  });
  const totals = perIssue.filter((p) => p.total > 0).map((p) => p.total);
  return {
    stages,
    perIssue,
    medianTotal: median(totals),
    totalCount: totals.length,
    maxTotal: totals.length ? Math.max(...totals) : 0,
  };
}

function compareStages(a, b) {
  const ia = STAGE_ORDER.indexOf(a);
  const ib = STAGE_ORDER.indexOf(b);
  if (ia === -1 && ib === -1) return 0;
  if (ia === -1) return 1;
  if (ib === -1) return -1;
  return ia - ib;
}

export function stageIndex(stage, present) {
  const known = STAGE_ORDER.indexOf(stage);
  return known === -1 ? STAGE_ORDER.length + present.indexOf(stage) : known;
}

/**
 * Gate pass rates. First attempt comes from per-issue gate_attempts (first element);
 * eventual comes from the final gate result. Gates with no recorded attempts contribute
 * to eventual only, so first-attempt may be unavailable (null rate).
 */
export function gateRates(issues, gatePassRates = {}) {
  const names = new Set(GATE_ORDER);
  for (const issue of issues) {
    Object.keys(issue.gates).forEach((g) => names.add(g));
    Object.keys(issue.gateAttempts).forEach((g) => names.add(g));
  }
  Object.keys(gatePassRates).forEach((g) => names.add(g));

  const known = GATE_ORDER.filter((g) => names.has(g));
  const extra = [...names].filter((g) => !GATE_ORDER.includes(g)).sort();

  return [...known, ...extra].map((gate) => {
    const first = { pass: 0, total: 0 };
    const eventual = { pass: 0, total: 0 };
    const derivedRuns = { pass: 0, fail: 0 };
    let sawAttempts = false;

    for (const issue of issues) {
      const attempts = issue.gateAttempts[gate] ?? [];
      if (attempts.length > 0) {
        sawAttempts = true;
        const kind = classifyResult(attempts[0]);
        if (kind !== 'other') {
          first.total += 1;
          if (kind === 'pass') first.pass += 1;
        }
        for (const r of attempts) {
          const k = classifyResult(r);
          if (k === 'pass') derivedRuns.pass += 1;
          else if (k === 'fail') derivedRuns.fail += 1;
        }
      }
      const kind = classifyResult(issue.gates[gate]);
      if (kind !== 'other') {
        eventual.total += 1;
        if (kind === 'pass') eventual.pass += 1;
      }
    }

    const runs = gatePassRates[gate] ?? (sawAttempts ? derivedRuns : null);
    return {
      gate,
      first: { ...first, rate: first.total ? first.pass / first.total : null },
      eventual: { ...eventual, rate: eventual.total ? eventual.pass / eventual.total : null },
      runs,
    };
  });
}

export function costSummary(metrics) {
  const rows = metrics.issues
    .map((i) => ({
      number: i.number,
      title: i.title,
      outcome: i.outcome,
      usd: i.cost.usd,
      model: i.cost.model,
      coder: i.cost.coder,
      calls: i.cost.calls,
      overLine: i.cost.usd !== null && i.cost.usd > ISSUE_COST_LINE_USD,
    }))
    .sort((a, b) => a.number - b.number);

  const rowTotal = sum(rows.map((r) => r.usd ?? 0));
  const total = metrics.totals.usd ?? rowTotal;
  const scale = Math.max(ISSUE_COST_LINE_USD, ...rows.map((r) => r.usd ?? 0));
  return {
    rows,
    total,
    totalReported: metrics.totals.usd !== null,
    rowTotal,
    modelTotal: sum(rows.map((r) => r.model ?? 0)),
    coderTotal: sum(rows.map((r) => r.coder ?? 0)),
    callsTotal: sum(rows.map((r) => r.calls ?? 0)),
    cap: COST_CAP_USD,
    haltAt: HALT_USD,
    fractionOfCap: Math.min(1, total / COST_CAP_USD),
    percentOfCap: (total / COST_CAP_USD) * 100,
    remaining: Math.max(0, COST_CAP_USD - total),
    haltReached: total >= HALT_USD,
    perIssueScale: scale,
  };
}

export function defectSummary(issues) {
  const bugs = issues
    .filter((i) => i.type === 'bug')
    .sort((a, b) => a.number - b.number)
    .map((i) => ({
      number: i.number,
      title: i.title,
      outcome: i.outcome,
      severity: i.severity,
      owner: i.owner,
      resolutionSeconds: i.resolutionSeconds,
      openedAt: i.openedAt,
    }));

  const owners = new Map();
  for (const b of bugs) {
    const key = b.owner ?? 'unassigned';
    if (!owners.has(key)) owners.set(key, []);
    owners.get(key).push(b);
  }
  const byOwner = [...owners.entries()]
    .map(([owner, list]) => ({
      owner,
      count: list.length,
      resolved: list.filter((b) => b.resolutionSeconds !== null).length,
      medianResolution: median(list.map((b) => b.resolutionSeconds)),
    }))
    .sort((a, b) => b.count - a.count || a.owner.localeCompare(b.owner));

  const resolutions = bugs.map((b) => b.resolutionSeconds).filter((v) => v !== null);
  return {
    bugs,
    byOwner,
    medianResolution: median(resolutions),
    maxResolution: resolutions.length ? Math.max(...resolutions) : 0,
  };
}

/** Links derived from repo and numbers only; null when the repo slug is not a plain owner/name. */
export function issueLinks(repo, issue) {
  if (!repo || !REPO_PATTERN.test(repo)) return { repo: null, issue: null, pr: null, release: null };
  const base = `https://github.com/${repo}`;
  return {
    repo: base,
    issue: `${base}/issues/${issue.number}`,
    pr: issue.pr === null ? null : `${base}/pull/${issue.pr}`,
    release: issue.release === null ? null : `${base}/releases/tag/${encodeURIComponent(issue.release)}`,
  };
}
