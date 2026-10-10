// SVG chart drawing. Every function is pure: (width, data) -> SVG element.
// Colours come from CSS classes (theme tokens), never from inline values, so a theme switch
// needs no redraw. Each chart has an HTML table twin in panels.js.

import { s } from './dom.js';
import { formatDuration, formatPercent, stageLabel, truncate } from './format.js';
import { stageIndex } from './aggregate.js';

const STAGE_COLORS = 8;
const COMPACT_BELOW = 520;

export const stageClass = (stage, present) => `seg-${stageIndex(stage, present) % STAGE_COLORS}`;

function svgRoot(width, height, label) {
  return s('svg', {
    class: 'chart',
    width,
    height,
    viewBox: `0 0 ${width} ${height}`,
    role: 'img',
    'aria-label': label,
  });
}

const text = (x, y, cls, content, anchor) =>
  s('text', { x, y, class: cls, 'text-anchor': anchor }, content);

/** Median duration per stage as horizontal bars with direct value labels. */
export function medianChart(width, stages, label) {
  const compact = width < COMPACT_BELOW;
  const labelW = compact ? 0 : 128;
  const valueW = compact ? 0 : 104;
  const rowH = compact ? 44 : 34;
  const barH = 10;
  const barX = labelW;
  const barW = Math.max(40, width - labelW - valueW);
  const max = Math.max(...stages.map((st) => st.median ?? 0), 1);
  const present = stages.map((st) => st.stage);

  const svg = svgRoot(width, rowH * stages.length, label);
  stages.forEach((st, i) => {
    const top = i * rowH;
    const barY = compact ? top + 22 : top + (rowH - barH) / 2;
    const w = st.median === null ? 0 : Math.max(2, (st.median / max) * barW);
    const valueText = formatDuration(st.median);

    svg.append(
      s('rect', { x: barX, y: barY, width: barW, height: barH, rx: 3, class: 'rail' }),
      s('rect', { x: barX, y: barY, width: w, height: barH, rx: 3, class: stageClass(st.stage, present) }, s('title', {}, `${stageLabel(st.stage)}: median ${valueText} across ${st.count}`)),
    );
    if (compact) {
      svg.append(
        text(0, top + 14, 'c-label', stageLabel(st.stage)),
        s('text', { x: width, y: top + 14, class: 'c-value', 'text-anchor': 'end' }, valueText, s('tspan', { class: 'c-sub', dx: 6 }, `n=${st.count}`)),
      );
    } else {
      svg.append(
        text(0, barY + barH - 1, 'c-label', stageLabel(st.stage)),
        s('text', { x: barX + barW + 10, y: barY + barH - 1, class: 'c-value' }, valueText, s('tspan', { class: 'c-sub', dx: 6 }, `n=${st.count}`)),
      );
    }
  });
  return svg;
}

/** One stacked bar per issue, segments scaled on a shared axis. */
export function stackedChart(width, perIssue, maxTotal, presentStages, label) {
  const compact = width < COMPACT_BELOW;
  const labelW = compact ? 0 : 200;
  const valueW = compact ? 0 : 64;
  const rowH = compact ? 44 : 30;
  const barH = 14;
  const barX = labelW;
  const barW = Math.max(40, width - labelW - valueW);
  const scale = maxTotal > 0 ? barW / maxTotal : 0;

  const svg = svgRoot(width, rowH * perIssue.length, label);
  perIssue.forEach((issue, i) => {
    const top = i * rowH;
    const barY = compact ? top + 20 : top + (rowH - barH) / 2;
    const caption = `${issue.label} ${issue.title}`;

    svg.append(s('rect', { x: barX, y: barY, width: barW, height: barH, rx: 3, class: 'rail' }));

    let x = barX;
    for (const seg of issue.segments) {
      const w = Math.max(1.5, seg.seconds * scale);
      svg.append(
        s('rect', { x, y: barY, width: w, height: barH, class: `${stageClass(seg.stage, presentStages)} seg${seg.open ? ' seg-open' : ''}` },
          s('title', {}, `${issue.label} ${stageLabel(seg.stage)}: ${formatDuration(seg.seconds)}${seg.open ? ' so far' : ''}`)),
      );
      x += w;
    }
    if (issue.segments.length === 0) {
      svg.append(text(barX + 8, barY + barH - 3, 'c-sub', 'no durations recorded'));
    }

    if (compact) {
      svg.append(
        text(0, top + 13, 'c-label', truncate(caption, Math.floor((width - 70) / 6.3))),
        text(width, top + 13, 'c-value', issue.total > 0 ? formatDuration(issue.total) : '', 'end'),
      );
    } else {
      svg.append(
        text(0, barY + barH - 2, 'c-label', truncate(caption, Math.floor((labelW - 12) / 6.3))),
        text(barX + barW + 10, barY + barH - 2, 'c-value', issue.total > 0 ? formatDuration(issue.total) : ''),
      );
    }
  });
  return svg;
}

/** Per gate: first-attempt and eventual pass rate as paired bars. */
export function gateChart(width, gates, label) {
  const compact = width < COMPACT_BELOW;
  const labelW = compact ? 0 : 96;
  const valueW = compact ? 88 : 112;
  const barH = 9;
  const gap = 5;
  const rowH = compact ? 18 + 2 * barH + gap + 16 : 2 * barH + gap + 18;
  const barX = labelW;
  const barW = Math.max(40, width - labelW - valueW);

  const svg = svgRoot(width, rowH * gates.length, label);
  gates.forEach((g, i) => {
    const top = i * rowH;
    const y1 = compact ? top + 20 : top + 9;
    const y2 = y1 + barH + gap;
    svg.append(compact ? text(0, top + 12, 'c-label c-gate', g.gate) : text(0, y1 + barH + 1, 'c-label c-gate', g.gate));

    [
      [y1, g.first, 'bar-first', 'First attempt'],
      [y2, g.eventual, 'bar-eventual', 'Eventually'],
    ].forEach(([y, part, cls, name]) => {
      svg.append(s('rect', { x: barX, y, width: barW, height: barH, rx: 3, class: 'rail' }));
      if (part.rate !== null) {
        svg.append(
          s('rect', { x: barX, y, width: Math.max(part.rate > 0 ? 2 : 0, part.rate * barW), height: barH, rx: 3, class: cls },
            s('title', {}, `${g.gate} ${name.toLowerCase()}: ${part.pass} of ${part.total}`)),
        );
      }
      const valueText = part.rate === null ? 'n/a' : `${formatPercent(part.rate)}`;
      const sub = part.rate === null ? '' : ` ${part.pass}/${part.total}`;
      svg.append(s('text', { x: barX + barW + 10, y: y + barH - 0.5, class: part.rate === null ? 'c-sub' : 'c-value' }, valueText, s('tspan', { class: 'c-sub' }, sub)));
    });
  });
  return svg;
}
