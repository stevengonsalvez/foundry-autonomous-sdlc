// SVG chart drawing. Every function is pure: (width, data) -> SVG element.
// Colours come from CSS classes (theme tokens), never from inline values, so a theme switch needs
// no redraw and the page needs no inline styles. Each chart has an HTML table twin in its view.

import { s } from './dom.js';
import { formatDuration, formatPercent, formatShortTime, formatUsd } from './format.js';
import { limitText } from './safe.js';

const COMPACT_BELOW = 520;
const CHAR_W = 6.4;

function svgRoot(width, height, label) {
  const safeLabel = limitText(label, 240);
  return s(
    'svg',
    {
      class: 'chart',
      width,
      height,
      viewBox: `0 0 ${width} ${height}`,
      role: 'img',
      'aria-label': safeLabel,
    },
    s('title', {}, safeLabel),
  );
}

const text = (x, y, cls, content, anchor) => s('text', { x, y, class: cls, 'text-anchor': anchor }, content);
const clip = (value, chars) => limitText(value, Math.max(4, Math.floor(chars)));

// ------------------------------------------------------------------ money

/**
 * Ledger estimate and Azure billed side by side, against the halt line and the cap.
 * `billed` is null until the bill has been read; the row then says so instead of drawing a bar.
 */
export function billingChart(width, { estimate, billed, halt, cap }) {
  const compact = width < COMPACT_BELOW;
  const labelW = compact ? 0 : 124;
  const rightPad = 76;
  const top = 30;
  const rowH = compact ? 48 : 40;
  const barH = 18;
  const barX = labelW;
  const barW = Math.max(60, width - labelW - rightPad);
  const max = Math.max(estimate, billed ?? 0, cap) * 1.04;
  const x = (v) => barX + (v / max) * barW;
  const rows = [
    { label: 'Ledger estimate', value: estimate, cls: 'fill-accent' },
    { label: 'Azure billed', value: billed, cls: billed !== null && billed >= halt ? 'fill-bad' : 'fill-info' },
  ];
  const height = top + rows.length * rowH + 6;
  const svg = svgRoot(
    width,
    height,
    `Ledger estimate ${formatUsd(estimate)}, Azure billed ${billed === null ? 'not read yet' : formatUsd(billed)}, halt line ${formatUsd(halt)}, cap ${formatUsd(cap)}`,
  );

  rows.forEach((row, i) => {
    const y = top + i * rowH + (compact ? 20 : (rowH - barH) / 2);
    svg.append(s('rect', { x: barX, y, width: barW, height: barH, rx: 4, class: 'rail' }));
    if (compact) svg.append(text(0, y - 6, 'c-label', row.label));
    else svg.append(text(0, y + barH - 5, 'c-label', row.label));
    if (row.value === null) {
      svg.append(text(barX + 10, y + barH - 5, 'c-sub', 'not read yet'));
      return;
    }
    const w = Math.max(3, x(row.value) - barX);
    svg.append(
      s('rect', { x: barX, y, width: w, height: barH, rx: 4, class: row.cls }, s('title', {}, `${row.label}: ${formatUsd(row.value)}`)),
      text(barX + w + 8, y + barH - 5, 'c-value', formatUsd(row.value)),
    );
  });

  const lineBottom = height - 2;
  svg.append(
    s('line', { x1: x(halt), x2: x(halt), y1: top - 8, y2: lineBottom, class: 'c-line c-halt' }),
    s('line', { x1: x(cap), x2: x(cap), y1: top - 8, y2: lineBottom, class: 'c-line c-cap' }),
    text(x(halt) - 5, top - 14, 'c-sub c-marker', `Halt ${formatUsd(halt)}`, 'end'),
    text(x(cap) + 5, top - 14, 'c-sub c-marker', `Cap ${formatUsd(cap)}`, 'start'),
  );
  return svg;
}

// ------------------------------------------------------------------ generic bars

/**
 * Horizontal bars with a label, a direct value and an optional marker line (for example the cap).
 * rows: [{ label, value, text, sub?, cls?, title? }]
 */
export function barChart(width, rows, { label, marker = null, labelChars = 22 } = {}) {
  const compact = width < COMPACT_BELOW;
  const labelW = compact ? 0 : Math.min(190, Math.max(96, labelChars * 6.6));
  const valueW = compact ? 0 : 110;
  const rowH = compact ? 46 : 30;
  const barH = 10;
  const barX = labelW;
  const barW = Math.max(40, width - labelW - valueW);
  const max = Math.max(...rows.map((r) => r.value ?? 0), marker?.value ?? 0, Number.MIN_VALUE) * (marker ? 1.1 : 1);
  const headroom = marker ? 14 : 0;
  const svg = svgRoot(width, headroom + rowH * rows.length, label ?? 'Bar chart');

  rows.forEach((row, i) => {
    const top = headroom + i * rowH;
    const barY = compact ? top + 24 : top + (rowH - barH) / 2;
    const w = row.value === null || row.value <= 0 ? 0 : Math.max(2, (row.value / max) * barW);
    svg.append(
      s('rect', { x: barX, y: barY, width: barW, height: barH, rx: 3, class: 'rail' }),
      w > 0 ? s('rect', { x: barX, y: barY, width: w, height: barH, rx: 3, class: row.cls ?? 'fill-accent' }, s('title', {}, limitText(row.title ?? `${row.label}: ${row.text}`, 200))) : null,
    );
    const valueNode = (x, y, anchor) => s('text', { x, y, class: 'c-value', 'text-anchor': anchor }, row.text, row.sub ? s('tspan', { class: 'c-sub', dx: 6 }, row.sub) : null);
    if (compact) {
      svg.append(text(0, top + 15, 'c-label', clip(row.label, (width - 100) / CHAR_W)), valueNode(width, top + 15, 'end'));
    } else {
      svg.append(text(0, barY + barH - 1, 'c-label', clip(row.label, labelW / CHAR_W)), valueNode(barX + barW + 10, barY + barH - 1, 'start'));
    }
  });

  if (marker) {
    const mx = barX + (marker.value / max) * barW;
    svg.append(
      s('line', { x1: mx, x2: mx, y1: 12, y2: headroom + rowH * rows.length, class: 'c-line c-cap' }),
      text(mx, 9, 'c-sub c-marker', marker.label, 'middle'),
    );
  }
  return svg;
}

/** One bar per ticket, split by stage, on a shared time axis. rows: [{ label, segments: [{stage, seconds, open}], total }] */
export function stackedStageChart(width, rows, { label, maxTotal, stageClass }) {
  const compact = width < COMPACT_BELOW;
  const labelW = compact ? 0 : 210;
  const valueW = compact ? 0 : 70;
  const rowH = compact ? 44 : 28;
  const barH = 14;
  const barX = labelW;
  const barW = Math.max(40, width - labelW - valueW);
  const scale = maxTotal > 0 ? barW / maxTotal : 0;
  const svg = svgRoot(width, rowH * rows.length, label);

  rows.forEach((row, i) => {
    const top = i * rowH;
    const barY = compact ? top + 20 : top + (rowH - barH) / 2;
    svg.append(s('rect', { x: barX, y: barY, width: barW, height: barH, rx: 3, class: 'rail' }));
    let x = barX;
    for (const seg of row.segments) {
      const w = Math.max(1.5, seg.seconds * scale);
      svg.append(
        s('rect', { x, y: barY, width: w, height: barH, class: `${stageClass(seg.stage)} seg${seg.open ? ' seg-open' : ''}` }, s('title', {}, `${row.label} ${seg.stage}: ${formatDuration(seg.seconds)}${seg.open ? ' so far' : ''}`)),
      );
      x += w;
    }
    if (row.segments.length === 0) svg.append(text(barX + 8, barY + barH - 3, 'c-sub', 'no durations recorded'));
    const total = row.total > 0 ? formatDuration(row.total) : '';
    if (compact) {
      svg.append(text(0, top + 13, 'c-label', clip(row.label, (width - 70) / CHAR_W)), text(width, top + 13, 'c-value', total, 'end'));
    } else {
      svg.append(text(0, barY + barH - 2, 'c-label', clip(row.label, (labelW - 12) / CHAR_W)), text(barX + barW + 10, barY + barH - 2, 'c-value', total));
    }
  });
  return svg;
}

/** Pass rate per gate. rows: [{ gate, pass, total }] */
export function rateChart(width, rows, { label }) {
  return barChart(
    width,
    rows.map((r) => {
      const rate = r.total > 0 ? r.pass / r.total : null;
      let cls = 'fill-accent';
      if (rate !== null) {
        if (rate >= 0.9) cls = 'fill-auto';
        else if (rate >= 0.7) cls = 'fill-dit';
        else if (rate >= 0.5) cls = 'fill-assist';
        else cls = 'fill-gate';
      }
      return {
        label: r.gate,
        value: rate,
        text: rate !== null ? formatPercent(rate) : 'n/a',
        sub: r.total > 0 ? `${r.pass}/${r.total}` : '',
        cls,
        title: `${r.gate}: ${r.pass} of ${r.total} passed on the first attempt`,
      };
    }),
    { label, labelChars: 12 },
  );
}

/**
 * Bug count by owner and resolution time.
 * rows: [{ owner, count, open, resolved, median }]
 */
export function defectsChart(width, rows, { label }) {
  const compact = width < COMPACT_BELOW;
  const labelW = compact ? 0 : 110;
  const valueW = compact ? 0 : 140;
  const rowH = compact ? 48 : 32;
  const barH = 12;
  const barX = labelW;
  const barW = Math.max(40, width - labelW - valueW);
  const max = Math.max(...rows.map((r) => r.count ?? 0), 1);
  const headroom = 20;
  const svg = svgRoot(width, headroom + rowH * rows.length + 6, label ?? 'Defects by owner');

  svg.append(
    s('rect', { x: barX, y: 5, width: 8, height: 8, rx: 2, class: 'fill-gate' }),
    text(barX + 12, 12, 'c-sub', 'open'),
    s('rect', { x: barX + 56, y: 5, width: 8, height: 8, rx: 2, class: 'fill-auto' }),
    text(barX + 68, 12, 'c-sub', 'resolved'),
  );

  rows.forEach((row, i) => {
    const top = headroom + i * rowH;
    const barY = compact ? top + 22 : top + (rowH - barH) / 2;
    svg.append(s('rect', { x: barX, y: barY, width: barW, height: barH, rx: 3, class: 'rail' }));

    const openW = row.open > 0 ? Math.max(2, (row.open / max) * barW) : 0;
    const resW = row.resolved > 0 ? Math.max(2, (row.resolved / max) * barW) : 0;

    let curX = barX;
    if (openW > 0) {
      svg.append(
        s(
          'rect',
          { x: curX, y: barY, width: openW, height: barH, rx: resW > 0 ? 0 : 3, class: 'fill-gate' },
          s('title', {}, `${row.owner}: ${row.open} open bug${row.open === 1 ? '' : 's'}`),
        ),
      );
      curX += openW;
    }
    if (resW > 0) {
      svg.append(
        s(
          'rect',
          { x: curX, y: barY, width: resW, height: barH, rx: openW > 0 ? 0 : 3, class: 'fill-auto' },
          s('title', {}, `${row.owner}: ${row.resolved} resolved bug${row.resolved === 1 ? '' : 's'}`),
        ),
      );
    }

    const valueStr = `${row.count} ${row.count === 1 ? 'bug' : 'bugs'}`;
    const subStr = row.median !== null ? `median ${formatDuration(row.median)}` : (row.open > 0 ? 'all open' : 'none');
    const valueNode = (x, y, anchor) =>
      s('text', { x, y, class: 'c-value', 'text-anchor': anchor }, valueStr, s('tspan', { class: 'c-sub', dx: 6 }, subStr));

    if (compact) {
      svg.append(text(0, top + 15, 'c-label', clip(row.owner, (width - 120) / CHAR_W)), valueNode(width, top + 15, 'end'));
    } else {
      svg.append(text(0, barY + barH - 1, 'c-label', clip(row.owner, labelW / CHAR_W)), valueNode(barX + barW + 10, barY + barH - 1, 'start'));
    }
  });

  return svg;
}

// ------------------------------------------------------------------ strips

/**
 * Lead times as dots on one axis, with the median marked. Dots that would overlap stack in rows.
 * points: [{ label, value }]
 */
export function dotStrip(width, points, { median, label }) {
  const padL = 8;
  const padR = 16;
  const top = 26;
  const r = 6;
  const barW = Math.max(40, width - padL - padR);
  const max = Math.max(...points.map((p) => p.value), median ?? 0, 1);
  const x = (v) => padL + (v / max) * barW;
  const sorted = [...points].sort((a, b) => a.value - b.value);
  const lastX = [];
  const placed = sorted.map((p) => {
    const px = x(p.value);
    let row = lastX.findIndex((lx) => px - lx >= r * 2 + 1);
    if (row === -1) row = lastX.length;
    lastX[row] = px;
    return { ...p, px, row };
  });
  const rows = Math.max(1, lastX.length);
  const axisY = top + rows * (r * 2 + 3) + 6;
  const svg = svgRoot(width, axisY + 24, label);

  svg.append(s('line', { x1: padL, x2: padL + barW, y1: axisY, y2: axisY, class: 'c-axis' }));
  for (const t of [0, max]) {
    svg.append(
      s('line', { x1: x(t), x2: x(t), y1: axisY, y2: axisY + 4, class: 'c-axis' }),
      text(x(t), axisY + 17, 'c-sub', formatDuration(t), t === 0 ? 'start' : 'end'),
    );
  }
  for (const p of placed) {
    svg.append(s('circle', { cx: p.px, cy: top + r + p.row * (r * 2 + 3), r, class: 'dot' }, s('title', {}, `${p.label}: ${formatDuration(p.value)}`)));
  }
  if (median !== null && median !== undefined) {
    svg.append(
      s('line', { x1: x(median), x2: x(median), y1: 14, y2: axisY, class: 'c-line c-median' }),
      text(x(median), 10, 'c-sub c-marker', `median ${formatDuration(median)}`, x(median) > width - 90 ? 'end' : 'middle'),
    );
  }
  return svg;
}

const OUTCOME_GLYPH = { ok: 'M-4 0.5l3 3 5.5-6.5', failed: 'M-4-4l8 8M4-4l-8 8', skipped: 'M-4 0h8', pending: 'M0 0.01v-.02' };

/** One cell per release, newest last, coloured and marked by outcome. releases: [{ version, outcome, at }] */
export function releaseStrip(width, releases, { label }) {
  const cellW = 64;
  const cellH = 58;
  const perRow = Math.max(1, Math.floor(width / cellW));
  const rows = Math.max(1, Math.ceil(releases.length / perRow));
  const svg = svgRoot(width, rows * cellH, label);
  releases.forEach((rel, i) => {
    const col = i % perRow;
    const row = Math.floor(i / perRow);
    const cx = col * cellW + cellW / 2;
    const cy = row * cellH + 16;
    const outcome = OUTCOME_GLYPH[rel.outcome] ? rel.outcome : 'pending';
    svg.append(
      s('g', { class: `release release-${outcome}` },
        s('rect', { x: cx - 15, y: cy - 14, width: 30, height: 28, rx: 7, class: 'release-box' }, s('title', {}, `${rel.version ?? 'unversioned'}: ${rel.outcome}${rel.at ? `, ${formatShortTime(rel.at)}` : ''}`)),
        s('path', { d: OUTCOME_GLYPH[outcome], transform: `translate(${cx} ${cy})`, class: 'release-glyph' }),
      ),
      text(cx, cy + 30, 'c-sub', clip(rel.version ?? '-', 9), 'middle'),
    );
  });
  return svg;
}

// ------------------------------------------------------------------ stage stepper

/**
 * The ticket's path across the board columns. steps: [{ stage, label, state, at, seconds, visits, open }]
 * state: done | current | todo | bad. Wide: a row of nodes; narrow: a column.
 */
export function stepper(width, steps, { label, stageClass }) {
  const wide = width >= 700;
  const r = 10;
  const mark = (step, cx, cy) => {
    const nodes = [];
    const cls = `node node-${step.state} ${stageClass(step.stage)}`;
    nodes.push(s('circle', { cx, cy, r, class: cls }));
    if (step.state === 'current') nodes.push(s('circle', { cx, cy, r: 4, class: 'node-core' }), s('circle', { cx, cy, r, class: 'node-pulse' }));
    if (step.state === 'done') nodes.push(s('path', { d: 'M-4 .5l3 3 5.5-6.5', transform: `translate(${cx} ${cy})`, class: 'node-glyph' }));
    if (step.state === 'bad') nodes.push(s('path', { d: 'M0-4.5v5M0 4v.01', transform: `translate(${cx} ${cy})`, class: 'node-glyph' }));
    return nodes;
  };
  const dateOf = (iso) => (iso ? formatShortTime(iso).replace(/, (\d\d:\d\d) UTC$/, '|$1').split('|') : ['', '']);
  const detail = (step) => (step.state === 'todo' ? '' : `${formatDuration(step.seconds)}${step.open && step.state === 'current' && !step.terminal ? ' so far' : ''}`);

  if (wide) {
    const padX = 44;
    const gap = (width - padX * 2) / (steps.length - 1);
    const cy = 20;
    const svg = svgRoot(width, 130, label);
    steps.forEach((step, i) => {
      if (i > 0) {
        const reached = step.state !== 'todo';
        svg.append(s('line', { x1: padX + (i - 1) * gap + r, x2: padX + i * gap - r, y1: cy, y2: cy, class: reached ? 'link link-done' : 'link' }));
      }
    });
    steps.forEach((step, i) => {
      const cx = padX + i * gap;
      const [date, time] = dateOf(step.at);
      svg.append(
        ...mark(step, cx, cy),
        text(cx, 52, step.state === 'todo' ? 'c-sub' : 'c-label c-strong', step.label, 'middle'),
        step.state === 'todo' ? null : text(cx, 70, 'c-sub', date, 'middle'),
        step.state === 'todo' ? null : text(cx, 85, 'c-sub', time, 'middle'),
        step.state === 'todo' ? null : text(cx, 104, 'c-value', detail(step), 'middle'),
        step.visits > 1 ? text(cx, 120, 'c-sub', `${step.visits} visits`, 'middle') : null,
      );
    });
    return svg;
  }

  const rowH = 52;
  const svg = svgRoot(width, rowH * steps.length + 4, label);
  steps.forEach((step, i) => {
    const cy = 22 + i * rowH;
    if (i > 0) svg.append(s('line', { x1: 16, x2: 16, y1: cy - rowH + r, y2: cy - r, class: step.state !== 'todo' ? 'link link-done' : 'link' }));
  });
  steps.forEach((step, i) => {
    const cy = 22 + i * rowH;
    svg.append(
      ...mark(step, 16, cy),
      text(40, cy - 2, step.state === 'todo' ? 'c-sub' : 'c-label c-strong', step.label),
      step.state === 'todo' ? null : text(40, cy + 14, 'c-sub', formatShortTime(step.at)),
      step.state === 'todo' ? null : text(width - 4, cy - 2, 'c-value', detail(step), 'end'),
      step.visits > 1 ? text(width - 4, cy + 14, 'c-sub', `${step.visits} visits`, 'end') : null,
    );
  });
  return svg;
}
