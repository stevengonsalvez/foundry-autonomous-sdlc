import { test } from 'node:test';
import assert from 'node:assert/strict';

import { escalationLabel, formatDuration, formatDurationCompact, formatInteger, formatPercent, formatRatio, formatRelative, formatShortTime, formatTimestamp, formatUsd, formatUsdWords, shortSha, truncate } from '../js/format.js';

test('money: two decimals, four under a cent, never invented', () => {
  assert.equal(formatUsd(13.0194), '$13.02');
  assert.equal(formatUsd(1.866893), '$1.87');
  assert.equal(formatUsd(0), '$0.00');
  assert.equal(formatUsd(0.0015), '$0.0015');
  assert.equal(formatUsd(0.006), '$0.0060');
  assert.equal(formatUsd(0.01), '$0.01');
  assert.equal(formatUsd(1234.5), '$1,234.50');
  assert.equal(formatUsd(-2), '-$2.00');
  assert.equal(formatUsd(null), '-');
  assert.equal(formatUsd(NaN), '-');
  assert.equal(formatUsd('3'), '-');
  assert.equal(formatUsdWords(13.0194), '13.02 USD');
});

test('durations read the way people say them', () => {
  assert.equal(formatDuration(0), '0s');
  assert.equal(formatDuration(59.6), '1m');
  assert.equal(formatDuration(167), '2m 47s');
  assert.equal(formatDuration(3600), '1h');
  assert.equal(formatDuration(5400), '1h 30m');
  assert.equal(formatDuration(93600), '1d 2h');
  assert.equal(formatDuration(-1), '-');
  assert.equal(formatDuration(null), '-');

  assert.equal(formatDurationCompact(0), '0s');
  assert.equal(formatDurationCompact(59), '59s');
  assert.equal(formatDurationCompact(167), '2m');
  assert.equal(formatDurationCompact(3600), '1h');
  assert.equal(formatDurationCompact(80460), '22h');
  assert.equal(formatDurationCompact(93600), '1d');
  assert.equal(formatDurationCompact(-1), '-');
  assert.equal(formatDurationCompact(null), '-');
});

test('relative and absolute times are UTC and tolerate bad input', () => {
  const now = Date.parse('2026-10-11T20:07:00Z');
  assert.equal(formatRelative('2026-10-11T20:07:00Z', now), 'just now');
  assert.equal(formatRelative('2026-10-11T20:07:30Z', now), 'just now', 'future is not negative');
  assert.equal(formatRelative('2026-10-11T20:06:15Z', now), '45 s ago');
  assert.equal(formatRelative('2026-10-11T20:04:00Z', now), '3 min ago');
  assert.equal(formatRelative('2026-10-11T17:07:00Z', now), '3 h ago');
  assert.equal(formatRelative('2026-10-08T20:07:00Z', now), '3 d ago');
  assert.equal(formatRelative('nope', now), '-');
  assert.equal(formatTimestamp('2026-10-10T17:46:00Z'), '2026-10-10 17:46 UTC');
  assert.equal(formatShortTime('2026-10-10T17:46:00Z'), 'Oct 10, 17:46 UTC');
  assert.equal(formatTimestamp(undefined), '-');
});

test('small helpers', () => {
  assert.equal(formatRatio(6.97), '7.0x');
  assert.equal(formatPercent(0.333), '33%');
  assert.equal(formatPercent(null), 'n/a');
  assert.equal(formatInteger(140043), '140,043');
  assert.equal(shortSha('f677ba5a3f621dda89a35333e38249622bd7f8bd'), 'f677ba5');
  assert.equal(shortSha('<img>'), '-');
  assert.equal(truncate('abcdef', 4), 'abc\u2026');
  assert.equal(escalationLabel('escalated:build-failed'), 'Build failed');
  assert.equal(escalationLabel('escalated:merge-conflict'), 'Merge conflict');
  assert.equal(escalationLabel('escalated:agent-quota'), 'Agent quota');
  assert.equal(escalationLabel(undefined), 'Escalated');
});
