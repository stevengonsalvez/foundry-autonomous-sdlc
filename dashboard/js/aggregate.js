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

export const isTerminalStage = (stage) => stage === 'stage:released' || String(stage).startsWith('escalated:');

/**
 * Stage seconds come from the orchestrator. The stage an object is in right now arrives with
 * `in_progress: true` and 0 seconds; it is measured here up to the time the file was generated.
 * A missing duration is derived from the next stage's entry time when both are known.
 */
function normalizeStages(rawStages, nowMs) {
  const list = Array.isArray(rawStages) ? rawStages.filter(isRecord).filter((s) => str(s.stage)) : [];
  const stages = list.map((s) => ({
    stage: s.stage,
    enteredMs: toMs(s.entered_at),
    enteredAt: toMs(s.entered_at) === null ? null : s.entered_at,
    seconds: nonNegative(s.seconds),
    inProgress: s.in_progress === true,
    terminal: isTerminalStage(s.stage),
  }));
  stages.forEach((s, i) => {
    if (s.inProgress) {
      s.seconds = s.enteredMs !== null && nowMs !== null && nowMs >= s.enteredMs ? (nowMs - s.enteredMs) / 1000 : null;
      return;
    }
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
  const coderRuntime = nonNegative(cost.coder_usd);
  const coderModel = nonNegative(cost.coder_model_usd);
  // "Coder" is the coder runtime plus the model spend of its fallback loop.
  const coder = coderRuntime === null && coderModel === null ? null : (coderRuntime ?? 0) + (coderModel ?? 0);
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

const positiveInt = (v) => (Number.isInteger(v) && v > 0 ? v : null);

/**
 * `number` is null for an entry that is a pull request on its own (the maintenance PR,
 * `kind: "pr"`); such an entry is identified by its `pr`.
 */
export function normalizeIssue(raw, nowMs = null) {
  if (!isRecord(raw)) return null;
  const number = positiveInt(raw.number);
  const pr = positiveInt(raw.pr);
  const isPr = raw.kind === 'pr' || number === null;
  const ref = number ?? pr;
  if (ref === null) return null;

  const stages = normalizeStages(raw.stages, nowMs);
  const type = stripPrefix(raw.type, 'type:');
  const endStage = stages.find((s) => s.stage === 'stage:released') ?? stages.find((s) => s.stage === 'stage:merged');
  const openedMs = toMs(raw.opened_at);

  let resolution = nonNegative(raw.resolution_seconds);
  if (resolution === null && openedMs !== null && endStage && endStage.enteredMs !== null && endStage.enteredMs >= openedMs) {
    resolution = (endStage.enteredMs - openedMs) / 1000;
  }

  const gates = normalizeGates(raw.gates);
  const attempts = normalizeAttempts(raw.gate_attempts);
  for (const [name, list] of Object.entries(attempts)) {
    if (!(name in gates) && list.length > 0) gates[name] = list[list.length - 1];
  }

  const label = number === null ? `PR #${ref}` : `#${ref}`;
  return {
    number,
    ref,
    kind: isPr ? 'pr' : 'issue',
    label,
    title: str(raw.title) ?? (number === null ? `Pull request #${ref}` : `Issue #${ref}`),
    scenario: str(raw.scenario),
    type,
    outcome: OUTCOMES.has(raw.outcome) ? raw.outcome : 'unknown',
    openedAt: openedMs === null ? null : raw.opened_at,
    closedAt: toMs(raw.closed_at) === null ? null : raw.closed_at,
    stages,
    severity: /^s[1-4]$/.test(raw.severity ?? '') ? raw.severity : null,
    owner: stripPrefix(raw.owner, 'owner:'),
    resolutionSeconds: resolution,
    pr,
    escalation: stripPrefix(raw.escalation, 'escalated:'),
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
  const nowMs = toMs(raw.generated_at);
  const issues = rawIssues.map((i) => normalizeIssue(i, nowMs)).filter(Boolean);
  const totals = isRecord(raw.totals) ? raw.totals : {};
  const metrics = {
    version: SCHEMA_VERSION,
    generatedAt: toMs(raw.generated_at) === null ? null : raw.generated_at,
    repo: typeof raw.repo === 'string' && REPO_PATTERN.test(raw.repo) ? raw.repo : null,
    totals: {
      usd: nonNegative(totals.usd),
      orchestratorUsd: nonNegative(totals.orchestrator_usd),
      escalated: Number.isInteger(totals.escalated) && totals.escalated >= 0 ? totals.escalated : null,
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
  const count = (v) => (isNum(v) && v >= 0 ? v : null);
  for (const [gate, v] of Object.entries(raw)) {
    if (!isRecord(v)) continue;
    const pass = count(v.pass);
    const fail = count(v.fail);
    if (pass === null || fail === null) continue;
    out[gate] = { pass, fail, firstPass: count(v.first_pass), firstFail: count(v.first_fail) };
  }
  return out;
}

export function headlineCounts(metrics) {
  const { issues, totals } = metrics;
  return {
    issues: totals.issues ?? issues.length,
    released: totals.released ?? issues.filter((i) => i.outcome === 'released').length,
    escalated: totals.escalated ?? issues.filter((i) => i.outcome === 'escalated').length,
  };
}

export function stageKey(stage) {
  return stripPrefix(stage, 'stage:') ?? 'unknown';
}

/**
 * Cycle time per stage. Stage order follows the state machine; unknown stages are appended.
 * Repeated stages within one issue (for example a second refinement round) are summed.
 * Terminal stages (released, escalated) have no duration and are not charted.
 * The stage an object is in right now is drawn up to the time the data was generated but
 * stays out of the medians, as does any stage whose duration is unknown.
 */
export function stageDurations(issues) {
  const perIssue = [];
  const byStage = new Map();

  for (const issue of issues) {
    const seconds = new Map();
    const open = new Set();
    for (const s of issue.stages) {
      if (s.terminal || s.seconds === null) continue;
      seconds.set(s.stage, (seconds.get(s.stage) ?? 0) + s.seconds);
      if (s.inProgress) open.add(s.stage);
    }
    for (const [stage, value] of seconds) {
      if (open.has(stage)) continue;
      if (!byStage.has(stage)) byStage.set(stage, []);
      byStage.get(stage).push(value);
    }
    const order = [...seconds.keys()].sort(compareStages);
    perIssue.push({
      ref: issue.ref,
      label: issue.label,
      title: issue.title,
      outcome: issue.outcome,
      segments: order.map((stage) => ({ stage, seconds: seconds.get(stage), open: open.has(stage) })),
      total: sum([...seconds.values()]),
      hasOpen: open.size > 0,
      hasUnknown: issue.stages.some((s) => !s.terminal && s.seconds === null),
    });
  }

  const stages = [...byStage.keys()].sort(compareStages).map((stage) => {
    const values = byStage.get(stage);
    return { stage, median: median(values), count: values.length, max: Math.max(...values) };
  });
  // End to end only counts issues that are done with every stage.
  const finished = perIssue.filter((p) => p.total > 0 && !p.hasOpen && !p.hasUnknown).map((p) => p.total);
  const totals = perIssue.filter((p) => p.total > 0).map((p) => p.total);
  return {
    stages,
    perIssue,
    medianTotal: median(finished),
    totalCount: finished.length,
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
 * Gate pass rates. Eventual is the final gate result per issue. First attempt comes from the
 * orchestrator's gate_pass_rates (first_pass, first_fail) when given, otherwise from the first
 * element of each issue's gate_attempts. With neither, first attempt is unknown (null rate).
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
    const derivedFirst = { pass: 0, total: 0 };
    const eventual = { pass: 0, total: 0 };
    const derivedRuns = { pass: 0, fail: 0 };
    let sawAttempts = false;

    for (const issue of issues) {
      const attempts = issue.gateAttempts[gate] ?? [];
      if (attempts.length > 0) {
        sawAttempts = true;
        const kind = classifyResult(attempts[0]);
        if (kind !== 'other') {
          derivedFirst.total += 1;
          if (kind === 'pass') derivedFirst.pass += 1;
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

    const reported = gatePassRates[gate] ?? null;
    const first =
      reported && reported.firstPass !== null && reported.firstFail !== null
        ? { pass: reported.firstPass, total: reported.firstPass + reported.firstFail }
        : derivedFirst;
    const runs = reported ? { pass: reported.pass, fail: reported.fail } : sawAttempts ? derivedRuns : null;
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
      ref: i.ref,
      label: i.label,
      title: i.title,
      outcome: i.outcome,
      usd: i.cost.usd,
      model: i.cost.model,
      coder: i.cost.coder,
      calls: i.cost.calls,
      overLine: i.cost.usd !== null && i.cost.usd > ISSUE_COST_LINE_USD,
    }))
    .sort((a, b) => a.ref - b.ref);

  const orchestrator = metrics.totals.orchestratorUsd ?? 0;
  const rowTotal = sum(rows.map((r) => r.usd ?? 0));
  const accounted = rowTotal + orchestrator;
  const total = metrics.totals.usd ?? accounted;
  const scale = Math.max(ISSUE_COST_LINE_USD, ...rows.map((r) => r.usd ?? 0));
  return {
    rows,
    total,
    totalReported: metrics.totals.usd !== null,
    rowTotal,
    orchestrator,
    accounted,
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
    .sort((a, b) => a.ref - b.ref)
    .map((i) => ({
      ref: i.ref,
      label: i.label,
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
  const release = issue.release ?? null;
  return {
    repo: base,
    issue: issue.number === null || issue.number === undefined ? null : `${base}/issues/${issue.number}`,
    pr: issue.pr === null ? null : `${base}/pull/${issue.pr}`,
    release: release === null ? null : `${base}/releases/tag/${encodeURIComponent(release)}`,
  };
}
