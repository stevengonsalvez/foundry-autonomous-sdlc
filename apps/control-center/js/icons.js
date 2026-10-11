// Small stroke icons, drawn inline (no icon font, no image requests). Paths are constants of this
// file, never data.

import { s } from './dom.js';

const PATHS = Object.freeze({
  check: 'M3.5 8.5l3 3 6-7',
  cross: 'M4 4l8 8M12 4l-8 8',
  dash: 'M4 8h8',
  clock: 'M8 4.5V8l2.5 1.5M8 14a6 6 0 1 0 0-12 6 6 0 0 0 0 12z',
  external: 'M9 3h4v4M13 3L7.5 8.5M11 9.5V12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h2.5',
  back: 'M9.5 3.5L5 8l4.5 4.5',
  refresh: 'M13 3.5V7h-3.5M3 12.5V9h3.5M12.4 7A4.7 4.7 0 0 0 3.6 6M3.6 9a4.7 4.7 0 0 0 8.8 1',
  plus: 'M8 3.5v9M3.5 8h9',
  bug: 'M6 5a2 2 0 0 1 4 0M5 7.5h6M8 6v7M5 7.5v2a3 3 0 0 0 6 0v-2M3 7l2 1M13 7l-2 1M3 12l2-1.5M13 12l-2-1.5',
  alert: 'M8 2.5l6 10.5H2L8 2.5zM8 6.5v3M8 11.2v.1',
  sun: 'M8 10.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM8 1.5v1.2M8 13.3v1.2M1.5 8h1.2M13.3 8h1.2M3.4 3.4l.85.85M11.75 11.75l.85.85M3.4 12.6l.85-.85M11.75 4.25l.85-.85',
  moon: 'M13 9.2A5.5 5.5 0 0 1 6.8 3 5.5 5.5 0 1 0 13 9.2z',
  auto: 'M2.5 3.5h11v7.5h-11zM6 13.5h4M8 11v2.5',
  search: 'M7 11.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9zM10.3 10.3L13.5 13.5',
  rollback: 'M4 6.5H9a3.5 3.5 0 0 1 0 7H6M6.5 3.5L3.5 6.5l3 3',
  dot: 'M8 8.01v-.02',
});

export function icon(name, { size = 16, className = '' } = {}) {
  const d = PATHS[name];
  if (d === undefined) throw new Error(`icon: unknown icon "${name}"`);
  return s(
    'svg',
    { class: `icon ${className}`.trim(), width: size, height: size, viewBox: '0 0 16 16', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.5, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', focusable: 'false' },
    s('path', { d }),
  );
}
