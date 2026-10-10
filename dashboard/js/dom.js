// Minimal element builders. Data is only ever attached as text nodes or validated attributes,
// never parsed as markup.

const SVG_NS = 'http://www.w3.org/2000/svg';

function apply(el, attrs) {
  for (const [key, value] of Object.entries(attrs ?? {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? '' : String(value));
  }
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  apply(el, attrs);
  append(el, children);
  return el;
}

export function s(tag, attrs, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  apply(el, attrs);
  append(el, children);
  return el;
}

/**
 * Keep an SVG chart in step with its container width. `draw(width)` returns an SVG element
 * and must be a pure function of its argument, so a resize simply redraws.
 */
export function responsiveSvg(host, draw) {
  let drawn = 0;
  const render = () => {
    const width = Math.floor(host.clientWidth);
    if (width <= 0 || width === drawn) return;
    drawn = width;
    host.replaceChildren(draw(width));
  };
  new ResizeObserver(render).observe(host);
  render();
}
