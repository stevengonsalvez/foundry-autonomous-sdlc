// Declarative UI states for scripts/ui/capture.mjs (see scripts/ui/states.json).
//
// loadStates/parseStates validate the config. runState drives one state on a page and
// reports "captured" or "skipped". A state is skipped, never failed, when the feature it
// shows does not exist in the build under test (its `requires` is absent, or a step
// needed to reach it cannot run), so old releases and old PRs still capture cleanly.
import fs from "node:fs";

export const VIEWPORT_NAMES = ["desktop", "mobile"];

/**
 * Chromium launch options. UI_CHROMIUM_ARGS (space separated) is an escape hatch for
 * sandboxes whose headless Chromium never produces frames, e.g.
 * UI_CHROMIUM_ARGS="--disable-gpu --disable-software-rasterizer". CI needs nothing.
 */
export function chromiumLaunchOptions(env = process.env) {
  const args = (env.UI_CHROMIUM_ARGS ?? "").split(/\s+/).filter((a) => a.startsWith("--"));
  return { headless: true, ...(args.length > 0 ? { args } : {}) };
}

const ID_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
// Mirrors validate_artifact.TEXT_RE: captions and titles end up in PR comments.
const TEXT_RE = /^[A-Za-z0-9 .,:;'()/+-]+$/;
const MAX_ID = 40;
const MAX_TITLE = 60;
const MAX_CAPTION = 160;
const MAX_SELECTOR = 200;

const DEFAULTS = { stepTimeoutMs: 5000, requiresTimeoutMs: 2000, waitTimeoutMs: 10000 };

function fail(where, message) {
  throw new Error(`states.json ${where}: ${message}`);
}

function str(value, where, max) {
  if (typeof value !== "string" || value.length === 0 || value.length > max) {
    fail(where, `must be a non-empty string of at most ${max} characters`);
  }
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(value)) fail(where, "must not contain control characters");
  return value;
}

function cond(value, where) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(where, "must be {selector} or {text}");
  const keys = Object.keys(value);
  if (keys.length !== 1 || !["selector", "text"].includes(keys[0])) fail(where, "must have exactly one of selector or text");
  return { [keys[0]]: str(value[keys[0]], `${where}.${keys[0]}`, MAX_SELECTOR) };
}

function condList(value, where, required) {
  if (value === undefined) {
    if (required) fail(where, "is required");
    return [];
  }
  const list = Array.isArray(value) ? value : [value];
  if (required && list.length === 0) fail(where, "must not be empty");
  return list.map((c, i) => cond(c, `${where}[${i}]`));
}

function pair(value, where, label) {
  if (!Array.isArray(value) || value.length !== 2) fail(where, `${label} takes [selector, value]`);
  return [str(value[0], `${where}[0]`, MAX_SELECTOR), str(value[1], `${where}[1]`, MAX_SELECTOR)];
}

function step(value, where) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(where, "step must be an object");
  const keys = Object.keys(value);
  if (keys.length !== 1) fail(where, "step must have exactly one action");
  const [action] = keys;
  const arg = value[action];
  switch (action) {
    case "click":
      return { click: str(arg, `${where}.click`, MAX_SELECTOR) };
    case "fill":
      return { fill: pair(arg, `${where}.fill`, "fill") };
    case "press":
      return { press: pair(arg, `${where}.press`, "press") };
    case "select":
      return { select: pair(arg, `${where}.select`, "select") };
    case "waitFor":
      return { waitFor: cond(arg, `${where}.waitFor`) };
    default:
      return fail(where, `unknown step action: ${action}`);
  }
}

function setup(value, where) {
  if (value === undefined) return { localStorage: {} };
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(where, "must be an object");
  for (const key of Object.keys(value)) {
    if (key !== "localStorage") fail(where, `unknown setup key: ${key}`);
  }
  const ls = value.localStorage ?? {};
  if (!ls || typeof ls !== "object" || Array.isArray(ls)) fail(`${where}.localStorage`, "must be an object");
  const out = {};
  for (const [k, v] of Object.entries(ls)) {
    str(k, `${where}.localStorage key`, 64);
    // Objects and arrays are stored as JSON, scalars as their string form.
    out[k] = typeof v === "string" ? v : JSON.stringify(v);
    if (out[k].length > 2000) fail(`${where}.localStorage.${k}`, "value too long");
  }
  return { localStorage: out };
}

export function parseStates(raw) {
  if (!raw || typeof raw !== "object" || raw.version !== 1) fail("root", "version must be 1");
  const routes = raw.routes;
  if (!routes || typeof routes !== "object" || Object.keys(routes).length === 0) fail("routes", "must be a non-empty object");
  for (const [name, route] of Object.entries(routes)) {
    if (!ID_RE.test(name)) fail(`routes.${name}`, "route names are kebab-case");
    str(route, `routes.${name}`, MAX_SELECTOR);
    if (!route.startsWith("/")) fail(`routes.${name}`, "path must start with /");
  }
  if (!Array.isArray(raw.states) || raw.states.length === 0) fail("states", "must be a non-empty array");

  const seen = new Set();
  const states = raw.states.map((s, i) => {
    const where = `states[${i}]`;
    if (!s || typeof s !== "object") fail(where, "must be an object");
    const id = str(s.id, `${where}.id`, MAX_ID);
    if (!ID_RE.test(id)) fail(`${where}.id`, "id must be kebab-case a-z0-9");
    if (seen.has(id)) fail(`${where}.id`, `duplicate id ${id}`);
    seen.add(id);
    const title = str(s.title, `${where}.title`, MAX_TITLE);
    if (!TEXT_RE.test(title)) fail(`${where}.title`, "title contains characters outside the allowed set");
    const caption = str(s.caption, `${where}.caption`, MAX_CAPTION);
    if (!TEXT_RE.test(caption)) fail(`${where}.caption`, "caption contains characters outside the allowed set");
    if (typeof s.route !== "string" || !(s.route in routes)) fail(`${where}.route`, `unknown route: ${s.route}`);
    const viewports = s.viewports === undefined ? [...VIEWPORT_NAMES] : s.viewports;
    if (!Array.isArray(viewports) || viewports.length === 0 || viewports.some((v) => !VIEWPORT_NAMES.includes(v))) {
      fail(`${where}.viewports`, `unknown viewport, expected a non-empty subset of ${VIEWPORT_NAMES.join(", ")}`);
    }
    if (s.steps !== undefined && !Array.isArray(s.steps)) fail(`${where}.steps`, "must be an array");
    return {
      id,
      title,
      caption,
      route: s.route,
      viewports,
      setup: setup(s.setup, `${where}.setup`),
      steps: (s.steps ?? []).map((st, j) => step(st, `${where}.steps[${j}]`)),
      requires: condList(s.requires, `${where}.requires`, false),
      waitFor: condList(s.waitFor, `${where}.waitFor`, true),
    };
  });
  return { version: 1, routes: { ...routes }, states };
}

export async function loadStates(file) {
  return parseStates(JSON.parse(await fs.promises.readFile(file, "utf-8")));
}

function locate(page, c) {
  return "selector" in c ? page.locator(c.selector).first() : page.getByText(c.text).first();
}

const describe = (c) => ("selector" in c ? `selector ${c.selector}` : `text "${c.text}"`);

async function runStep(page, st, timeout) {
  if ("click" in st) return page.locator(st.click).first().click({ timeout });
  if ("fill" in st) return page.locator(st.fill[0]).first().fill(st.fill[1], { timeout });
  if ("press" in st) return page.locator(st.press[0]).first().press(st.press[1], { timeout });
  if ("select" in st) return page.locator(st.select[0]).first().selectOption(st.select[1], { timeout });
  return locate(page, st.waitFor).waitFor({ state: "visible", timeout });
}

/**
 * Drive one state to its capture-ready condition.
 * Returns {status: "captured"} or {status: "skipped", reason}. Throws for real failures.
 */
export async function runState(page, context, state, opts) {
  const { origin, routes } = opts;
  const t = { ...DEFAULTS, ...opts };

  const presets = state.setup.localStorage;
  if (Object.keys(presets).length > 0) {
    await context.addInitScript((entries) => {
      try {
        for (const [k, v] of entries) window.localStorage.setItem(k, v);
      } catch {
        // storage unavailable: the state will simply not show its preset
      }
    }, Object.entries(presets));
  }

  await page.goto(`${origin}${routes[state.route]}`, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => document.fonts.ready);

  const optional = state.requires.length > 0;
  for (const st of state.steps) {
    try {
      await runStep(page, st, t.stepTimeoutMs);
    } catch (err) {
      if (optional) {
        return { status: "skipped", reason: `step ${JSON.stringify(st)} could not run: ${String(err.message).split("\n")[0]}` };
      }
      throw err;
    }
  }

  for (const c of state.requires) {
    try {
      await locate(page, c).waitFor({ state: "attached", timeout: t.requiresTimeoutMs });
    } catch {
      return { status: "skipped", reason: `requires ${describe(c)} not present` };
    }
  }

  for (const c of state.waitFor) {
    await locate(page, c).waitFor({ state: "visible", timeout: t.waitTimeoutMs });
  }

  // Stop animations so captures are deterministic, then let layout settle.
  await page.addStyleTag({
    content: `*, *::before, *::after { animation-duration: 0s !important; animation-delay: 0s !important; transition-duration: 0s !important; transition-delay: 0s !important; }`,
  });
  await page.waitForTimeout(100);
  return { status: "captured" };
}
