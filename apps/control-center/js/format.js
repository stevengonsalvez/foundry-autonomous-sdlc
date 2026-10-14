// Display formatting. Pure and locale independent so output is the same on every machine.
// All times are UTC.

export const NO_VALUE = '-';

const finite = (v) => typeof v === 'number' && Number.isFinite(v);

export function formatDuration(seconds) {
  if (!finite(seconds) || seconds < 0) return NO_VALUE;
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

export function formatDurationCompact(seconds) {
  if (!finite(seconds) || seconds < 0) return NO_VALUE;
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

/** Money: 2 decimals, 4 under a cent (so a $0.0015 call is not shown as $0.00). Zero is $0.00. */
export function formatUsd(value) {
  if (!finite(value)) return NO_VALUE;
  const abs = Math.abs(value);
  const digits = abs > 0 && abs < 0.01 ? 4 : 2;
  const fixed = abs.toFixed(digits);
  const [whole, frac] = fixed.split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${value < 0 ? '-' : ''}$${grouped}.${frac}`;
}

/** "13.02 USD" for running sentences. */
export function formatUsdWords(value) {
  return finite(value) ? `${formatUsd(value).replace('$', '')} USD` : NO_VALUE;
}

export function formatPercent(rate) {
  return finite(rate) ? `${Math.round(rate * 100)}%` : 'n/a';
}

export function formatInteger(value) {
  if (!finite(value)) return NO_VALUE;
  return String(Math.trunc(value)).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

/** "7.0x" */
export function formatRatio(value) {
  return finite(value) ? `${value.toFixed(1)}x` : NO_VALUE;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function parseTime(iso) {
  if (typeof iso !== 'string') return null;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : ms;
}

/** "2026-10-10 17:46 UTC" */
export function formatTimestamp(iso) {
  const ms = parseTime(iso);
  return ms === null ? NO_VALUE : `${new Date(ms).toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

/** "Oct 10, 17:46 UTC" */
export function formatShortTime(iso) {
  const ms = parseTime(iso);
  if (ms === null) return NO_VALUE;
  const d = new Date(ms);
  const hh = String(d.getUTCHours()).padStart(2, '0');
  const mm = String(d.getUTCMinutes()).padStart(2, '0');
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ${hh}:${mm} UTC`;
}

/** "3 min ago". Future times (clock skew) read as "just now". */
export function formatRelative(iso, nowMs) {
  const ms = parseTime(iso);
  if (ms === null || !finite(nowMs)) return NO_VALUE;
  const s = Math.max(0, Math.round((nowMs - ms) / 1000));
  if (s < 10) return 'just now';
  if (s < 60) return `${s} s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} h ago`;
  const d = Math.floor(h / 24);
  return d < 60 ? `${d} d ago` : formatShortTime(iso);
}

/** Age in seconds, or null when the timestamp is unusable. */
export function ageSeconds(iso, nowMs) {
  const ms = parseTime(iso);
  return ms === null || !finite(nowMs) ? null : Math.max(0, (nowMs - ms) / 1000);
}

export function shortSha(sha) {
  return typeof sha === 'string' && /^[0-9a-f]{7,40}$/i.test(sha) ? sha.slice(0, 7).toLowerCase() : NO_VALUE;
}

export function truncate(text, max) {
  if (max < 2) return '';
  const s = String(text ?? '');
  return s.length <= max ? s : `${s.slice(0, max - 1).trimEnd()}…`;
}

export function plural(n, one, many = `${one}s`) {
  return n === 1 ? one : many;
}

export function titleCase(value) {
  const s = String(value ?? '').replace(/[-_:]+/g, ' ').trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** "escalated:build-failed" -> "Build failed" */
export function escalationLabel(label) {
  return titleCase(String(label ?? '').replace(/^escalated:/, '')) || 'Escalated';
}
