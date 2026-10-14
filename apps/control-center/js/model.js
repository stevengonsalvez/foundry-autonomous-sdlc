// Selectors: everything the views show, derived from a normalised state (see schema.js).
// Pure functions of (state, now): no DOM, no clock reads, so they are unit tested directly.

import { formatRatio, formatUsdWords, parseTime, titleCase } from './format.js';

export const TYPES = Object.freeze(['feature', 'bug', 'maintenance']);
export const GATES = Object.freeze(['test', 'coverage', 'e2e', 'gitleaks', 'tdd-order', 'agent-scope', 'evals', 'review', 'smoke', 'soak']);
export const OLD_AFTER_DAYS = 7;
export const STALE_AFTER_S = 600;

export const STAGE_LABELS = Object.freeze({
  backlog: 'Backlog',
  refining: 'Refining',
  feasible: 'Feasible',
  tests: 'Tests',
  building: 'Building',
  review: 'Review',
  staging: 'Staging',
  prod: 'Production',
  escalated: 'Escalated',
});

export const stageLabel = (stage) => STAGE_LABELS[stage] ?? titleCase(stage);

const DAY_MS = 86_400_000;
const seconds = (fromIso, toMs) => Math.max(0, (toMs - parseTime(fromIso)) / 1000);

// ------------------------------------------------------------------ stage timeline

/**
 * Chronological stage entries for a ticket. The ledger's history follows the issue labels; the
 * last two board stages (prod, escalated) come from the deploy record and the escalation, so they
 * are added here when the history stops short of the ticket's current stage.
 */
export function stageEntries(ticket, nowMs) {
  const rows = ticket.stage_history
    .map((e) => ({ stage: e.stage, at: e.at, seconds: e.seconds, synthetic: false }))
    .sort((a, b) => parseTime(a.at) - parseTime(b.at));
  if (rows.length === 0 && ticket.opened_at) rows.push({ stage: 'backlog', at: ticket.opened_at, seconds: null, synthetic: true });
  const last = rows.at(-1);
  if (last && last.stage !== ticket.stage) {
    const at = enteredFromRecords(ticket);
    // A deploy record can predate the last label change (clock skew, synthetic data): never go backwards.
    if (at) rows.push({ stage: ticket.stage, at: parseTime(at) >= parseTime(last.at) ? at : last.at, seconds: null, synthetic: true });
  }
  rows.forEach((row, i) => {
    const next = rows[i + 1];
    row.open = next === undefined;
    if (row.seconds === null && next) row.seconds = seconds(row.at, parseTime(next.at));
    if (row.open) row.seconds = Math.max(0, nowMs - parseTime(row.at)) / 1000;
  });
  return rows;
}

function enteredFromRecords(ticket) {
  if (ticket.stage === 'prod') {
    const hop = ticket.hops.find((h) => h.env === 'prod' && h.status === 'success' && h.at);
    return hop?.at ?? ticket.closed_at ?? ticket.updated_at;
  }
  if (ticket.stage === 'escalated') return ticket.escalation?.at ?? ticket.updated_at;
  return ticket.updated_at;
}

/** How long the ticket has been in its current board stage (a run of consecutive entries counts once). */
export function timeInStage(ticket, nowMs) {
  const rows = stageEntries(ticket, nowMs);
  let i = rows.length - 1;
  if (i < 0 || rows[i].stage !== ticket.stage) {
    const since = ticket.updated_at ?? ticket.opened_at;
    return { stage: ticket.stage, since, seconds: since ? seconds(since, nowMs) : null };
  }
  while (i > 0 && rows[i - 1].stage === ticket.stage) i -= 1;
  return { stage: ticket.stage, since: rows[i].at, seconds: seconds(rows[i].at, nowMs) };
}

/** Per board stage: total time, visits (a loop back counts again), first entry, still running. */
export function stageDurations(ticket, nowMs) {
  const rows = stageEntries(ticket, nowMs);
  const byStage = new Map();
  rows.forEach((row, i) => {
    const acc = byStage.get(row.stage) ?? { stage: row.stage, seconds: 0, visits: 0, at: row.at, open: false, synthetic: row.synthetic };
    if (i === 0 || rows[i - 1].stage !== row.stage) acc.visits += 1;
    acc.seconds += row.seconds ?? 0;
    acc.open = acc.open || row.open;
    byStage.set(row.stage, acc);
  });
  return [...byStage.values()];
}

// ------------------------------------------------------------------ gates and environments

export const GATE_STATUSES = Object.freeze(['pass', 'fail', 'running', 'skipped', 'none']);

const GATE_PASS = ['success', 'passed', 'pass'];
const GATE_FAIL = ['failure', 'failed', 'error', 'timed_out', 'cancelled', 'rolled_back'];
const GATE_RUN = ['in_progress', 'pending', 'queued', 'running', 'waiting'];

export function gateOutcome(raw) {
  if (GATE_PASS.includes(raw)) return GATE_STATUSES[0];
  if (GATE_FAIL.includes(raw)) return GATE_STATUSES[1];
  if (GATE_RUN.includes(raw)) return GATE_STATUSES[2];
  if (raw === 'skipped') return GATE_STATUSES[3];
  return GATE_STATUSES[4];
}

/**
 * Status of one gate on a ticket. `review` falls back to the reviewer's last verdict when the gate
 * itself was not recorded, and says so (`derived`).
 */
export function gateStatus(ticket, gate) {
  let status = gateOutcome(ticket.gates[gate]);
  let derived = false;
  if (status === 'none' && gate === 'review' && ticket.reviews.length > 0) {
    const verdict = ticket.reviews.at(-1).verdict;
    status = verdict === 'approve' ? 'pass' : verdict === 'unknown' ? 'none' : 'fail';
    derived = status !== 'none';
  }
  const tries = ticket.gate_history.filter((entry) => gate in entry.results);
  return {
    gate,
    status,
    derived,
    attempts: tries.length,
    firstPass: tries.length ? gateOutcome(tries[0].results[gate]) === 'pass' : null,
  };
}

const HOP_OUTCOME = { success: 'pass', skipped: 'skipped', failed: 'fail', rolled_back: 'fail', in_progress: 'running' };

/** staging -> smoke -> soak -> prod, each with where it stands. */
export function pipelineChain(ticket) {
  const hopsIn = (env) => ticket.hops.filter((h) => h.env === env);
  const lastIn = (env) => hopsIn(env).at(-1);
  const staging = lastIn('staging');
  const prod = hopsIn('prod').filter((h) => h.status === 'success').at(-1);
  const legacy = ticket.hops.some((h) => h.action === 'legacy-publish');
  return [
    { key: 'staging', label: 'Staging', status: staging ? (HOP_OUTCOME[staging.status] ?? 'none') : 'none', note: legacy && !staging ? 'not used' : '' },
    { key: 'smoke', label: 'Smoke', status: gateStatus(ticket, 'smoke').status, note: '' },
    { key: 'soak', label: 'Soak', status: gateStatus(ticket, 'soak').status, note: '' },
    { key: 'prod', label: 'Production', status: prod ? 'pass' : 'none', note: legacy ? 'legacy publish' : '' },
  ];
}

// ------------------------------------------------------------------ board

export const emptyFilters = () => ({ types: new Set(), query: '', hideOld: false });

export function isOpenEscalation(ticket) {
  if (!ticket || !ticket.escalation) return false;
  if (ticket.escalation.resolved != null) return false;
  return ticket.escalation.open ?? true;
}

export function isFinished(ticket) {
  return ticket.stage === 'prod' || (ticket.stage === 'escalated' && !isOpenEscalation(ticket));
}

function isOld(ticket, nowMs) {
  const at = parseTime(ticket.closed_at ?? ticket.updated_at ?? '');
  return at !== null && nowMs - at > OLD_AFTER_DAYS * DAY_MS;
}

export function matchesFilters(ticket, filters, nowMs) {
  if (filters.types.size > 0 && !filters.types.has(ticket.type)) return false;
  if (filters.hideOld && isFinished(ticket) && isOld(ticket, nowMs)) return false;
  const query = filters.query.trim().toLowerCase();
  if (query === '') return true;
  const digits = query.replace(/^#/, '');
  if (/^\d+$/.test(digits) && String(ticket.issue).startsWith(digits)) return true;
  return ticket.title.toLowerCase().includes(query);
}

const byRecent = (a, b) =>
  (parseTime(b.updated_at ?? b.opened_at ?? '') ?? 0) - (parseTime(a.updated_at ?? a.opened_at ?? '') ?? 0) || b.issue - a.issue;

/** Tickets the ledger has not seen yet, merged into the ones it has. Anything the ledger knows wins. */
export function withPending(tickets, pending) {
  const known = new Set(tickets.map((t) => t.issue));
  return [...pending.filter((p) => !known.has(p.issue)), ...tickets];
}

export function boardColumns(state, pending, filters, nowMs) {
  const all = withPending(state.tickets, pending);
  const stages = state.board_stages;
  return stages.map((stage) => {
    const inStage = all.filter((t) => (stage === 'escalated' ? t.stage === stage && isOpenEscalation(t) : t.stage === stage));
    const shown = inStage.filter((t) => matchesFilters(t, filters, nowMs)).sort(byRecent);
    return { stage, label: stageLabel(stage), tickets: shown, total: inStage.length };
  });
}

export function typesPresent(state, pending) {
  const found = new Set(TYPES);
  for (const t of withPending(state.tickets, pending)) found.add(t.type);
  return [...found];
}

export function boardSummary(state, pending) {
  const all = withPending(state.tickets, pending);
  const count = (pred) => all.filter(pred).length;
  return {
    total: all.length,
    inFlight: count((t) => !['prod', 'escalated'].includes(t.stage)),
    prod: count((t) => t.stage === 'prod'),
    escalated: count((t) => t.stage === 'escalated' && isOpenEscalation(t)),
    waiting: count((t) => t.pending),
  };
}

// ------------------------------------------------------------------ cost

export const COST_BANDS = Object.freeze(['ok', 'high', 'over']);

export function costBand(pct) {
  if (pct > 100) return COST_BANDS[2];
  if (pct >= 75) return COST_BANDS[1];
  return COST_BANDS[0];
}

export function costRows(state) {
  return state.tickets.map((t) => ({
    issue: t.issue,
    title: t.title,
    type: t.type,
    stage: t.stage,
    usd: t.cost.usd,
    model: t.cost.model_usd,
    coder: t.cost.coder_usd + t.cost.coder_model_usd,
    ledger: t.cost.ledger_usd,
    pct: t.cost.cap_used_pct,
    over: t.cost.cap_used_pct > 100 || t.flags.includes('over-cap'),
  }));
}

export function sortRows(rows, key, direction = 'desc') {
  const sign = direction === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => sign * (a[key] - b[key]) || a.issue - b.issue);
}

/**
 * The billed-versus-estimated story, as data plus one plain sentence.
 * `billed` is null until the ledger has read Azure's bill; nothing is invented in that case.
 */
export function billingSummary(cost) {
  const estimate = cost.totals.usd;
  const billed = cost.billing?.billed_usd ?? null;
  const base = { estimate, billed, caps: cost.caps, asOf: cost.billing?.as_of ?? null, halted: cost.totals.halted };
  if (billed === null) {
    return { ...base, read: false, gap: null, ratio: null, tone: 'info', overHalt: false, overCap: false, sentence: 'Billed spend not read yet. The ledger estimate is the only number available.' };
  }
  const ratio = cost.gap?.ratio ?? (estimate > 0 ? billed / estimate : null);
  const gap = cost.gap?.gap_usd ?? billed - estimate;
  const overCap = billed >= cost.caps.total_usd;
  const overHalt = billed >= cost.caps.halt_usd;
  const head = `Azure billed ${formatUsdWords(billed)}; the ledger estimated ${formatUsdWords(estimate)}`;
  const sentence =
    billed > estimate && ratio !== null
      ? `${head}; the ledger undercounts hosted compute by ${formatRatio(ratio)}.`
      : `${head}; the estimate is at or above what Azure has billed so far.`;
  return { ...base, read: true, gap, ratio, tone: overHalt ? 'danger' : 'info', overHalt, overCap, sentence };
}

// ------------------------------------------------------------------ escalations, trail, flow

export function escalationList(state) {
  return state.tickets
    .filter((t) => t.escalation !== null)
    .sort((a, b) => (parseTime(b.escalation.at ?? '') ?? 0) - (parseTime(a.escalation.at ?? '') ?? 0) || b.issue - a.issue);
}

export function openEscalations(state) {
  return escalationList(state).filter(isOpenEscalation);
}

export function resolvedEscalations(state) {
  return escalationList(state)
    .filter((t) => !isOpenEscalation(t))
    .sort((a, b) => (parseTime(b.escalation?.resolved?.at ?? '') ?? 0) - (parseTime(a.escalation?.resolved?.at ?? '') ?? 0) || b.issue - a.issue);
}

const REFINING = new Set(['refining']);

function firstEntryAt(ticket, stages) {
  return ticket.stage_history.find((e) => stages.has(e.stage))?.at ?? null;
}

/** Questions, reviews and CI triage per ticket. Times are the start of the stage each came from. */
export function trailGroups(state, { kind = 'all', issue = null } = {}) {
  const groups = [];
  for (const t of state.tickets) {
    if (issue !== null && t.issue !== issue) continue;
    const items = [];
    const refinementAt = firstEntryAt(t, REFINING);
    if ((kind === 'all' || kind === 'qa') && t.qa.length > 0) {
      items.push({ kind: 'qa', at: refinementAt, atNote: 'refinement started', data: t.qa });
    }
    const reviewStarts = t.stage_history.filter((e) => e.stage === 'review').map((e) => e.at);
    if (kind === 'all' || kind === 'review') {
      t.reviews.forEach((r, i) =>
        items.push({ kind: 'review', at: reviewStarts[Math.min(i, reviewStarts.length - 1)] ?? t.updated_at, atNote: reviewStarts.length ? 'review started' : 'ticket last updated', data: r }),
      );
    }
    if ((kind === 'all' || kind === 'ci') && t.ci_triage) {
      items.push({ kind: 'ci', at: reviewStarts[0] ?? t.updated_at, atNote: reviewStarts.length ? 'review started' : 'ticket last updated', data: t.ci_triage });
    }
    if (items.length === 0) continue;
    const latest = Math.max(...items.map((i) => parseTime(i.at ?? '') ?? 0));
    groups.push({ ticket: t, items, latest });
  }
  return groups.sort((a, b) => b.latest - a.latest || b.ticket.issue - a.ticket.issue);
}

export function trailIssues(state) {
  return trailGroups(state).map((g) => g.ticket);
}

export const SCENARIO_NOTES = Object.freeze({
  a: 'Clear feature',
  b: 'Vague feature, needs refinement',
  c: 'Not suited to an agent, escalates',
  d: 'Bug fix',
  'd-maintenance': 'Maintenance change',
});

export function scenarioRows(state) {
  const groups = new Map();
  for (const t of state.tickets) {
    const key = t.scenario ?? 'unlabelled';
    const row = groups.get(key) ?? { scenario: key, tickets: [], prod: 0, escalated: 0, inFlight: 0, usd: 0 };
    row.tickets.push(t);
    row[t.stage === 'prod' ? 'prod' : t.stage === 'escalated' ? 'escalated' : 'inFlight'] += 1;
    row.usd += t.cost.usd;
    groups.set(key, row);
  }
  return [...groups.values()].sort((a, b) => a.scenario.localeCompare(b.scenario));
}

// ------------------------------------------------------------------ environments

export function failedGate(reason) {
  const r = String(reason ?? '').toLowerCase();
  if (r.includes('soak')) return 'soak';
  if (r.includes('smoke')) return 'smoke';
  if (r.includes('promot')) return 'promote step';
  return null;
}

/** The ticket an environment event is about: its own issue, else the first included issue. */
export function flaggedIssue(entry) {
  return entry.issue ?? entry.includes.find((i) => i.issue !== null)?.issue ?? null;
}

export const newestFirst = (rows) => [...rows].sort((a, b) => (parseTime(b.at ?? '') ?? 0) - (parseTime(a.at ?? '') ?? 0));

export function rollbackRows(state) {
  return newestFirst(state.environments.history.filter((e) => e.action === 'rollback' || e.action === 'fail'));
}

export function releaseRows(state) {
  const history = state.environments.history;
  return [...state.flow.change_failure.per_release]
    .sort((a, b) => (parseTime(b.at ?? '') ?? 0) - (parseTime(a.at ?? '') ?? 0))
    .map((r) => {
      const entries = history.filter((e) => e.sha !== null && e.sha === r.sha);
      const issues = new Set();
      for (const e of entries) {
        if (e.issue !== null) issues.add(e.issue);
        for (const i of e.includes) if (i.issue !== null) issues.add(i.issue);
      }
      return { ...r, issues: [...issues].sort((a, b) => a - b), run_url: entries.find((e) => e.run_url)?.run_url ?? null };
    });
}

// ------------------------------------------------------------------ freshness

export function freshness(state, nowMs, staleAfterS = STALE_AFTER_S) {
  const generated = parseTime(state.generated_at ?? '');
  const age = generated === null ? null : Math.max(0, (nowMs - generated) / 1000);
  return { ageSeconds: age, stale: age === null || age > staleAfterS };
}

/** Build order for comparing two documents: the newest `generated_at` wins, `seq` breaks a tie. */
export function isNewer(candidate, current) {
  if (current === null) return true;
  const a = parseTime(candidate.generated_at ?? '');
  const b = parseTime(current.generated_at ?? '');
  if (a !== b) return (a ?? -Infinity) > (b ?? -Infinity);
  return candidate.seq > current.seq;
}

// ------------------------------------------------------------------ commits

const IMPLEMENTATION_KINDS = new Set(['feat', 'fix', 'refactor']);

/** Did the first `test:` commit come before the first `feat:` or `fix:` one? Oldest commit first. */
export function tddOrder(commits) {
  const testIndex = commits.findIndex((c) => c.kind === 'test');
  const implIndex = commits.findIndex((c) => IMPLEMENTATION_KINDS.has(c.kind));
  if (testIndex === -1 || implIndex === -1) return { status: 'unknown', testIndex, implIndex };
  return { status: testIndex < implIndex ? 'tests-first' : 'impl-first', testIndex, implIndex };
}
