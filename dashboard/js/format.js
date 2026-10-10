// Display formatting. Pure, locale independent so output is stable across machines.

export const NO_VALUE = '-';

export function formatDuration(seconds) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return NO_VALUE;
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  if (s < 3600) {
    const m = Math.floor(s / 60);
    const rest = s % 60;
    return rest === 0 ? `${m}m` : `${m}m ${rest}s`;
  }
  if (s < 86400) {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return m === 0 ? `${h}h` : `${h}h ${m}m`;
  }
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  return h === 0 ? `${d}d` : `${d}d ${h}h`;
}

export function formatUsd(value, decimals = 4) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return NO_VALUE;
  return `$${value.toFixed(decimals)}`;
}

export function formatPercent(rate) {
  if (typeof rate !== 'number' || !Number.isFinite(rate)) return 'n/a';
  return `${Math.round(rate * 100)}%`;
}

export function formatInteger(value) {
  return typeof value === 'number' && Number.isFinite(value) ? String(Math.trunc(value)) : NO_VALUE;
}

/** "2026-10-10 12:00 UTC" from an ISO timestamp. */
export function formatTimestamp(iso) {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return NO_VALUE;
  return `${new Date(ms).toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

const STAGE_LABELS = {
  'stage:needs-refinement': 'Needs refinement',
  'stage:ready': 'Ready',
  'stage:feasible': 'Feasible',
  'stage:tests-written': 'Tests written',
  'stage:building': 'Building',
  'stage:in-review': 'In review',
  'stage:merged': 'Merged',
  'stage:released': 'Released',
};

export function stageLabel(stage) {
  if (STAGE_LABELS[stage]) return STAGE_LABELS[stage];
  const bare = String(stage).replace(/^stage:/, '').replace(/[-_]+/g, ' ');
  return bare.charAt(0).toUpperCase() + bare.slice(1);
}

export function truncate(text, max) {
  if (max < 2) return '';
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}

export function plural(n, one, many = `${one}s`) {
  return n === 1 ? one : many;
}
