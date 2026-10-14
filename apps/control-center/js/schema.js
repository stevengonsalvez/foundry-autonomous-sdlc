// state.json (schema version 1) -> a document the views can trust.
//
// The file is written by the ledger (agents/sdlc_agents/ledger) and every optional field may be
// missing or null, so this is the one place that coerces. After `parseState`, collections are
// arrays, numbers are finite numbers, and unknown shapes are dropped instead of thrown on.
// Views never need to guard against a missing field. The field names are the contract's own.

import { positiveInt } from './safe.js';

export const SCHEMA_VERSION = 1;
export const BOARD_STAGES = Object.freeze(['backlog', 'refining', 'feasible', 'tests', 'building', 'review', 'staging', 'prod', 'escalated']);
export const ENVS = Object.freeze(['none', 'staging', 'prod', 'rolled-back']);
export const AGENT_STATES = Object.freeze(['running', 'idle', 'error', 'stale', 'unknown']);
export const DEFAULT_CAPS = Object.freeze({ issue_usd: 3, halt_usd: 22, total_usd: 25 });

// ------------------------------------------------------------------ coercers

export const isRecord = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
export const list = (v) => (Array.isArray(v) ? v : []);
export const record = (v) => (isRecord(v) ? v : {});
export const num = (v, fallback = 0) => (typeof v === 'number' && Number.isFinite(v) ? v : fallback);
export const numOrNull = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
export const text = (v, fallback = '') => (typeof v === 'string' ? v : typeof v === 'number' && Number.isFinite(v) ? String(v) : fallback);
export const textOrNull = (v) => (typeof v === 'string' && v !== '' ? v : null);
export const iso = (v) => (typeof v === 'string' && !Number.isNaN(Date.parse(v)) ? v : null);
const texts = (v) => list(v).filter((x) => typeof x === 'string');

const RESOLVED_BY = ['simulated-human', 'human', 'system'];
const RESOLVED_HOW = ['closed', 'answered', 'superseded'];

export function normalizeResolved(v) {
  if (!isRecord(v)) return null;
  const by = RESOLVED_BY.includes(v.by) ? v.by : null;
  const how = RESOLVED_HOW.includes(v.how) ? v.how : null;
  const at = iso(v.at);
  if (!by || !how || !at) return null;
  return { at, by, how };
}

// ------------------------------------------------------------------ tickets

function normalizeEscalation(v) {
  if (!isRecord(v)) return null;
  const res = normalizeResolved(v.resolved);
  return {
    label: text(v.label, 'escalated'),
    reasons: texts(v.reasons),
    at: iso(v.at),
    attempts: num(v.attempts),
    tried: texts(v.tried),
    evidence_url: textOrNull(v.evidence_url),
    resolved: res,
    open: typeof v.open === 'boolean' ? v.open : res === null,
  };
}

function normalizeHistory(v) {
  return list(v)
    .filter(isRecord)
    .map((e) => ({ stage: text(e.stage), sdlc_stage: textOrNull(e.sdlc_stage), at: iso(e.at), seconds: numOrNull(e.seconds) }))
    .filter((e) => e.stage !== '' && e.at !== null);
}

function normalizeHops(v) {
  return list(v)
    .filter(isRecord)
    .map((e) => ({
      env: text(e.env, 'staging'),
      status: text(e.status),
      action: text(e.action),
      at: iso(e.at),
      sha: textOrNull(e.sha),
      version: textOrNull(e.version),
      run_url: textOrNull(e.run_url),
      detail: textOrNull(e.detail),
    }));
}

function normalizeTicketCost(v) {
  const c = record(v);
  return {
    usd: num(c.usd),
    model_usd: num(c.model_usd),
    coder_usd: num(c.coder_usd),
    coder_model_usd: num(c.coder_model_usd),
    ledger_usd: num(c.ledger_usd),
    tokens_in: num(c.tokens_in),
    tokens_out: num(c.tokens_out),
    calls: num(c.calls),
    coder_seconds: num(c.coder_seconds),
    cap_usd: num(c.cap_usd, DEFAULT_CAPS.issue_usd) || DEFAULT_CAPS.issue_usd,
    cap_used_pct: num(c.cap_used_pct, num(c.usd) * 100),
    by_agent: list(c.by_agent)
      .filter(isRecord)
      .map((a) => ({ agent: text(a.agent, 'unknown'), calls: num(a.calls), in: num(a.in), out: num(a.out), usd: num(a.usd) })),
  };
}

function normalizeReviews(v) {
  return list(v)
    .filter(isRecord)
    .map((r) => ({
      verdict: text(r.verdict, 'unknown'),
      head: textOrNull(r.head),
      round: num(r.round),
      findings: list(r.findings)
        .filter(isRecord)
        .map((f) => ({ severity: text(f.severity, 'info'), area: text(f.area), detail: text(f.detail) })),
    }));
}

function normalizeQa(v) {
  return list(v)
    .filter(isRecord)
    .map((q) => ({
      round: num(q.round),
      score: numOrNull(q.score),
      question: text(q.question),
      answer: textOrNull(q.answer),
      answered_by: textOrNull(q.answered_by),
    }));
}

function normalizeCommits(v) {
  return list(v)
    .filter(isRecord)
    .map((c) => ({
      sha: textOrNull(c.sha),
      message: text(c.message),
      kind: text(c.kind, 'other'),
      files: Array.isArray(c.files) ? c.files.length : num(c.files),
    }));
}

function normalizeCiTriage(v) {
  if (!isRecord(v)) return null;
  return {
    cause: text(v.cause),
    explanation: text(v.explanation),
    test_files: texts(v.test_files),
    revise_rounds: num(v.revise_rounds),
    check: text(v.check),
  };
}

function normalizePr(v) {
  if (!isRecord(v)) return null;
  const number = positiveInt(v.number);
  if (number === null) return null;
  return {
    number,
    url: textOrNull(v.url),
    branch: textOrNull(v.branch),
    head: textOrNull(v.head),
    merge_sha: textOrNull(v.merge_sha),
    title: textOrNull(v.title),
  };
}

function normalizeRelease(v) {
  return isRecord(v) && typeof v.tag === 'string' && v.tag !== '' ? { tag: v.tag, url: textOrNull(v.url) } : null;
}

function normalizeCoder(v) {
  if (!isRecord(v)) return null;
  return {
    job_id: textOrNull(v.job_id),
    engine: textOrNull(v.engine),
    status: textOrNull(v.status),
    iterations: num(v.iterations),
    attempts: num(v.attempts),
    elapsed_s: num(v.elapsed_s),
    started_at: iso(v.started_at),
    mode: textOrNull(v.mode),
  };
}

function normalizeGates(v) {
  const out = {};
  for (const [name, status] of Object.entries(record(v))) if (typeof status === 'string') out[name] = status;
  return out;
}

function normalizeGateHistory(v) {
  return list(v)
    .filter(isRecord)
    .map((g) => ({ head: textOrNull(g.head), results: normalizeGates(g.results) }));
}

export function normalizeTicket(raw, boardStages = BOARD_STAGES) {
  if (!isRecord(raw)) return null;
  const issue = positiveInt(raw.issue);
  if (issue === null) return null;
  const flags = texts(raw.flags);
  const knownStage = boardStages.includes(raw.stage);
  if (!knownStage) flags.push('unknown-stage');
  const quality = isRecord(raw.quality) ? raw.quality : null;
  const triage = isRecord(raw.triage) ? raw.triage : null;
  const feasibility = isRecord(raw.feasibility) ? raw.feasibility : null;
  return {
    issue,
    kind: raw.kind === 'pr' ? 'pr' : 'issue',
    title: text(raw.title),
    type: text(raw.type, 'feature'),
    scenario: textOrNull(raw.scenario),
    author: textOrNull(raw.author),
    url: textOrNull(raw.url),
    opened_at: iso(raw.opened_at),
    closed_at: iso(raw.closed_at),
    updated_at: iso(raw.updated_at),
    stage: knownStage ? raw.stage : 'backlog',
    sdlc_stage: textOrNull(raw.sdlc_stage),
    env: ENVS.includes(raw.env) ? raw.env : 'none',
    escalation: normalizeEscalation(raw.escalation),
    stage_history: normalizeHistory(raw.stage_history),
    pr: normalizePr(raw.pr),
    commits: normalizeCommits(raw.commits),
    release: normalizeRelease(raw.release),
    hops: normalizeHops(raw.hops),
    gates: normalizeGates(raw.gates),
    gate_history: normalizeGateHistory(raw.gate_history),
    cost: normalizeTicketCost(raw.cost),
    agent_runs: list(raw.agent_runs)
      .filter(isRecord)
      .map((r) => ({ agent: text(r.agent, 'unknown'), in: num(r.in), out: num(r.out), usd: num(r.usd) })),
    coder: normalizeCoder(raw.coder),
    qa: normalizeQa(raw.qa),
    reviews: normalizeReviews(raw.reviews),
    ci_triage: normalizeCiTriage(raw.ci_triage),
    quality: quality ? { score: numOrNull(quality.score), rounds: num(quality.rounds), summary: textOrNull(quality.summary) } : null,
    triage: triage ? { severity: textOrNull(triage.severity), owner: textOrNull(triage.owner), summary: textOrNull(triage.summary) } : null,
    feasibility: feasibility
      ? { suitable: feasibility.suitable === true, risk: textOrNull(feasibility.risk), reasons: texts(feasibility.reasons) }
      : null,
    summary: textOrNull(raw.summary),
    flags,
    pending: false,
  };
}

// ------------------------------------------------------------------ environments, agents, cost, flow

function normalizeIncludes(v) {
  return list(v)
    .filter(isRecord)
    .map((i) => ({ issue: positiveInt(i.issue), pr: positiveInt(i.pr), sha: textOrNull(i.sha) }));
}

function normalizeEnvRow(v, name) {
  if (!isRecord(v)) return null;
  return {
    name,
    version: textOrNull(v.version),
    sha: textOrNull(v.sha),
    short: textOrNull(v.short),
    at: name === 'staging' ? (iso(v.deployed_at) ?? iso(v.promoted_at)) : (iso(v.promoted_at) ?? iso(v.deployed_at)),
    run_url: textOrNull(v.run_url),
    status: textOrNull(v.status),
    gates_cleared: texts(v.gates_cleared ?? v.gates),
    includes: normalizeIncludes(v.includes),
    pr: positiveInt(v.pr),
    issue: positiveInt(v.issue),
    tag: textOrNull(v.tag),
  };
}

function normalizeEnvironments(v) {
  const e = record(v);
  return {
    source: text(e.source, 'none'),
    staging: normalizeEnvRow(e.staging, 'staging'),
    prod: normalizeEnvRow(e.prod, 'prod'),
    previous_prod: normalizeEnvRow(e.previous_prod, 'prod'),
    rollbacks: num(e.rollbacks),
    history: list(e.history)
      .filter(isRecord)
      .map((x) => ({
        action: text(x.action),
        at: iso(x.at),
        env: text(x.env, 'staging'),
        includes: normalizeIncludes(x.includes),
        issue: positiveInt(x.issue),
        pr: positiveInt(x.pr),
        reason: textOrNull(x.reason),
        run_url: textOrNull(x.run_url),
        sha: textOrNull(x.sha),
        version: textOrNull(x.version),
      }))
      .filter((x) => x.at !== null),
  };
}

function normalizeAgent(v) {
  if (!isRecord(v) || typeof v.name !== 'string') return null;
  const lastError = v.last_error;
  return {
    name: v.name,
    kind: text(v.kind),
    role: text(v.role),
    state: AGENT_STATES.includes(v.state) ? v.state : 'unknown',
    last_active_at: iso(v.last_active_at),
    calls_total: num(v.calls_total),
    calls_last_tick: num(v.calls_last_tick),
    tokens_in: num(v.tokens_in),
    tokens_out: num(v.tokens_out),
    usd: num(v.usd),
    current_object: positiveInt(v.current_object),
    lock_holder: textOrNull(v.lock_holder),
    errors: num(v.errors),
    retries: num(v.retries),
    last_error: isRecord(lastError)
      ? { at: iso(lastError.at), detail: text(lastError.detail), object: positiveInt(lastError.object), result: textOrNull(lastError.result) }
      : typeof lastError === 'string' && lastError !== ''
        ? { at: null, detail: lastError, object: null, result: null }
        : null,
  };
}

function normalizeBilling(v) {
  if (!isRecord(v) || numOrNull(v.billed_usd) === null) return null;
  return {
    billed_usd: v.billed_usd,
    as_of: iso(v.as_of),
    currency: text(v.currency, 'USD'),
    scope: textOrNull(v.scope),
    source: textOrNull(v.source),
    by_meter: list(v.by_meter)
      .filter(isRecord)
      .map((m) => ({ name: text(m.name, 'unnamed'), usd: num(m.usd) })),
  };
}

function normalizeTotalsCost(v) {
  const c = record(v);
  const totals = record(c.totals);
  const caps = record(c.caps);
  const gap = isRecord(c.gap) && numOrNull(c.gap.billed_usd) !== null ? c.gap : null;
  const ledger = record(c.ledger);
  return {
    caps: {
      issue_usd: num(caps.issue_usd, DEFAULT_CAPS.issue_usd),
      halt_usd: num(caps.halt_usd, DEFAULT_CAPS.halt_usd),
      total_usd: num(caps.total_usd, DEFAULT_CAPS.total_usd),
    },
    totals: {
      usd: num(totals.usd),
      issues_usd: num(totals.issues_usd),
      orchestrator_usd: num(totals.orchestrator_usd),
      ledger_usd: num(totals.ledger_usd),
      billed_usd: numOrNull(totals.billed_usd),
      halted: totals.halted === true,
      over_cap: totals.over_cap === true,
    },
    billing: normalizeBilling(c.billing),
    gap: gap
      ? { billed_usd: gap.billed_usd, ledger_usd: num(gap.ledger_usd), gap_usd: num(gap.gap_usd), ratio: numOrNull(gap.ratio), note: textOrNull(gap.note) }
      : null,
    ledger: {
      invocations: num(ledger.invocations),
      seconds: num(ledger.seconds),
      usd: num(ledger.usd),
      last_at: iso(ledger.last_at),
    },
  };
}

function normalizeFlow(v) {
  const f = record(v);
  const lead = record(f.lead_time);
  const cf = record(f.change_failure);
  const gates = {};
  for (const [name, g] of Object.entries(record(f.gate_first_pass))) {
    if (isRecord(g)) gates[name] = { pass: num(g.pass), total: num(g.total) };
  }
  const medians = {};
  for (const [stage, secs] of Object.entries(record(f.stage_medians_s))) if (numOrNull(secs) !== null) medians[stage] = secs;
  const counts = {};
  for (const [stage, n] of Object.entries(record(f.counts))) counts[stage] = num(n);
  return {
    stage_medians_s: medians,
    counts,
    gate_first_pass: gates,
    lead_time: {
      median_s: numOrNull(lead.median_s),
      by_ticket: list(lead.by_ticket)
        .filter(isRecord)
        .map((x) => ({ issue: positiveInt(x.issue), seconds: numOrNull(x.seconds) }))
        .filter((x) => x.issue !== null && x.seconds !== null),
    },
    defects: list(f.defects)
      .filter(isRecord)
      .map((d) => ({ issue: positiveInt(d.issue), owner: textOrNull(d.owner), severity: textOrNull(d.severity), seconds: numOrNull(d.seconds) }))
      .filter((d) => d.issue !== null),
    change_failure: {
      releases: num(cf.releases),
      failed: num(cf.failed),
      rate: numOrNull(cf.rate),
      per_release: list(cf.per_release)
        .filter(isRecord)
        .map((r) => ({ at: iso(r.at), last_at: iso(r.last_at), outcome: text(r.outcome, 'pending'), sha: textOrNull(r.sha), version: textOrNull(r.version) })),
    },
  };
}

function normalizeLedger(v) {
  const l = record(v);
  const tick = isRecord(l.last_tick) ? l.last_tick : null;
  return {
    events: num(l.events),
    last_ingest_at: iso(l.last_ingest_at),
    mode: text(l.mode, 'hosted'),
    errors: list(l.errors)
      .map((e) => (isRecord(e) ? { at: iso(e.at), message: text(e.message) } : typeof e === 'string' ? { at: null, message: e } : null))
      .filter((e) => e !== null && e.message !== ''),
    last_tick: tick
      ? {
          started_at: iso(tick.started_at),
          finished_at: iso(tick.finished_at),
          lock: textOrNull(tick.lock),
          model_calls: num(tick.model_calls),
          usd_this_tick: num(tick.usd_this_tick),
          orchestrator_usd: num(tick.orchestrator_usd),
          objects: list(tick.objects)
            .filter(isRecord)
            .map((o) => ({ number: positiveInt(o.number), kind: text(o.kind), action: text(o.action), result: text(o.result) })),
        }
      : null,
  };
}

// ------------------------------------------------------------------ document

/**
 * Validate and normalise a parsed state.json.
 * Returns { status: 'ok', state } or { status: 'error', message }.
 */
export function parseState(raw) {
  if (!isRecord(raw)) return { status: 'error', message: 'state.json is not a JSON object.' };
  if (raw.version !== SCHEMA_VERSION) {
    const found = raw.version === undefined ? 'none' : JSON.stringify(raw.version);
    return { status: 'error', message: `Unsupported state.json version (found ${found}). This page reads version ${SCHEMA_VERSION}.` };
  }
  if (raw.tickets !== undefined && raw.tickets !== null && !Array.isArray(raw.tickets)) {
    return { status: 'error', message: 'state.json has a malformed "tickets" field (expected a list).' };
  }
  const declared = texts(raw.board_stages);
  const boardStages = declared.length > 0 ? declared : [...BOARD_STAGES];
  const tickets = [];
  let dropped = 0;
  const seen = new Set();
  for (const entry of list(raw.tickets)) {
    const t = normalizeTicket(entry, boardStages);
    if (t === null || seen.has(t.issue)) dropped += 1;
    else {
      seen.add(t.issue);
      tickets.push(t);
    }
  }
  return {
    status: 'ok',
    state: {
      version: SCHEMA_VERSION,
      repo: text(raw.repo),
      generated_at: iso(raw.generated_at),
      updated_at: iso(raw.updated_at),
      seq: num(raw.seq),
      board_stages: boardStages,
      tickets,
      dropped,
      archived: num(raw.archived),
      environments: normalizeEnvironments(raw.environments),
      agents: list(raw.agents).map(normalizeAgent).filter((a) => a !== null),
      cost: normalizeTotalsCost(raw.cost),
      flow: normalizeFlow(raw.flow),
      ledger: normalizeLedger(raw.ledger),
    },
  };
}
