// Tests for scripts/ui/states.mjs. Run: node --test scripts/tests/ui/
// Loader tests are pure. Runner tests drive real Chromium against a tiny fixture app,
// proving that a state whose feature is absent is skipped (not an error) and that a
// present feature is captured with its setup and steps applied.
import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import { createRequire } from "node:module";
import path from "node:path";
import { after, before, describe, test } from "node:test";
import { fileURLToPath } from "node:url";

import { chromiumLaunchOptions, loadStates, parseStates, runState } from "../../ui/states.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "../../..");
const STATES_JSON = path.join(REPO_ROOT, "scripts/ui/states.json");

const base = () => ({
  version: 1,
  routes: { home: "/#/" },
  states: [
    {
      id: "home-default",
      title: "Home",
      route: "home",
      waitFor: { selector: "h1" },
      caption: "Home page.",
    },
  ],
});

function withState(patch) {
  const cfg = base();
  cfg.states[0] = { ...cfg.states[0], ...patch };
  return cfg;
}

describe("parseStates", () => {
  test("the shipped states.json parses and has the initial states", async () => {
    const cfg = await loadStates(STATES_JSON);
    const ids = cfg.states.map((s) => s.id);
    for (const id of [
      "home-default",
      "home-dark",
      "home-recent-searches",
      "home-left-nav",
      "parcel-timeline",
      "parcel-copy-link",
    ]) {
      assert.ok(ids.includes(id), `missing state ${id}`);
    }
    assert.equal(new Set(ids).size, ids.length);
  });

  test("defaults viewports to desktop and mobile and normalises requires/waitFor to lists", () => {
    const cfg = parseStates(withState({ requires: { selector: "h1" } }));
    assert.deepEqual(cfg.states[0].viewports, ["desktop", "mobile"]);
    assert.deepEqual(cfg.states[0].requires, [{ selector: "h1" }]);
    assert.deepEqual(cfg.states[0].waitFor, [{ selector: "h1" }]);
    assert.deepEqual(cfg.states[0].steps, []);
  });

  for (const [name, patch, re] of [
    ["unsafe id", { id: "../etc" }, /id/],
    ["uppercase id", { id: "Home" }, /id/],
    ["unknown route", { route: "nope" }, /route/],
    ["unknown viewport", { viewports: ["tablet"] }, /viewport/],
    ["caption with markup", { caption: "<img src=x>" }, /caption/],
    ["title with backtick", { title: "a`b" }, /title/],
    ["missing waitFor", { waitFor: undefined }, /waitFor/],
    ["step with two actions", { steps: [{ click: "a", fill: ["b", "c"] }] }, /step/],
    ["unknown step", { steps: [{ evaluate: "alert(1)" }] }, /step/],
    ["fill with wrong arity", { steps: [{ fill: ["#x"] }] }, /fill/],
    ["localStorage non-string key", { setup: { localStorage: { "": "x" } } }, /localStorage/],
    ["setup with unknown key", { setup: { cookies: {} } }, /setup/],
  ]) {
    test(`rejects ${name}`, () => {
      assert.throws(() => parseStates(withState(patch)), re);
    });
  }

  test("rejects duplicate ids", () => {
    const cfg = base();
    cfg.states.push({ ...cfg.states[0] });
    assert.throws(() => parseStates(cfg), /duplicate/i);
  });

  test("rejects unsupported version", () => {
    assert.throws(() => parseStates({ ...base(), version: 2 }), /version/);
  });
});

// ---- runner against a fixture app -------------------------------------------------

const requireFromApp = createRequire(path.join(REPO_ROOT, "app", "package.json"));
const { chromium } = requireFromApp("@playwright/test");

const OLD_APP = `<!doctype html><title>old</title><h1>Old app</h1>
<button id="go" onclick="document.getElementById('out').textContent='went'">Go</button><p id="out"></p>`;

const NEW_APP = `<!doctype html><title>new</title><h1>New app</h1>
<button data-testid="theme-toggle">toggle</button>
<script>
  document.documentElement.dataset.theme = localStorage.getItem("theme") || "light";
</script>
<button id="go" onclick="document.getElementById('out').textContent='went'">Go</button><p id="out"></p>`;

function serve(html) {
  return new Promise((resolve) => {
    const server = http.createServer((_req, res) => {
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(html);
    });
    server.listen(0, "127.0.0.1", () => resolve({ server, origin: `http://127.0.0.1:${server.address().port}` }));
  });
}

describe("runState", () => {
  let browser;
  let oldApp;
  let newApp;

  before(async () => {
    browser = await chromium.launch(chromiumLaunchOptions());
    oldApp = await serve(OLD_APP);
    newApp = await serve(NEW_APP);
  });

  after(async () => {
    await browser.close();
    oldApp.server.close();
    newApp.server.close();
  });

  async function run(app, patch, vp = { width: 800, height: 600 }) {
    const cfg = parseStates(withState(patch));
    const state = cfg.states[0];
    const context = await browser.newContext({ viewport: vp });
    try {
      const page = await context.newPage();
      return await runState(page, context, state, {
        origin: app.origin,
        routes: cfg.routes,
        stepTimeoutMs: 1500,
        requiresTimeoutMs: 600,
        waitTimeoutMs: 1500,
      });
    } finally {
      await context.close();
    }
  }

  test("captures a state with no requirements", async () => {
    const res = await run(oldApp, {});
    assert.equal(res.status, "captured");
  });

  test("skips (does not fail) when requires is absent", async () => {
    const res = await run(oldApp, {
      requires: { selector: "[data-testid='theme-toggle']" },
      waitFor: { selector: "h1" },
    });
    assert.equal(res.status, "skipped");
    assert.match(res.reason, /theme-toggle/);
  });

  test("skips when a step cannot run and the state declares requires", async () => {
    const res = await run(oldApp, {
      steps: [{ click: ".copy-link-btn" }],
      requires: { selector: ".copy-link-btn.is-copied" },
    });
    assert.equal(res.status, "skipped");
  });

  test("a failing step without requires is a real error", async () => {
    await assert.rejects(run(oldApp, { steps: [{ click: ".nope" }] }));
  });

  test("a failing waitFor after requires passed is a real error", async () => {
    await assert.rejects(run(newApp, { requires: { selector: "h1" }, waitFor: { selector: ".never" } }));
  });

  test("applies localStorage setup before load and honours requires + waitFor", async () => {
    const res = await run(newApp, {
      setup: { localStorage: { theme: "dark" } },
      requires: { selector: "[data-testid='theme-toggle']" },
      waitFor: { selector: "html[data-theme='dark']" },
    });
    assert.equal(res.status, "captured");
  });

  test("runs click steps and waits for text", async () => {
    const res = await run(oldApp, {
      steps: [{ click: "#go" }],
      requires: { text: "went" },
      waitFor: { text: "went" },
    });
    assert.equal(res.status, "captured");
  });
});

test("chromiumLaunchOptions only forwards --flags from UI_CHROMIUM_ARGS", () => {
  assert.deepEqual(chromiumLaunchOptions({}), { headless: true });
  assert.deepEqual(chromiumLaunchOptions({ UI_CHROMIUM_ARGS: "--disable-gpu  rm --x" }), {
    headless: true,
    args: ["--disable-gpu", "--x"],
  });
});

test("states.json is consistent with the artifact validator regexes", () => {
  const cfg = JSON.parse(fs.readFileSync(STATES_JSON, "utf-8"));
  for (const s of cfg.states) {
    assert.match(s.id, /^[a-z0-9]+(?:-[a-z0-9]+)*$/);
    assert.ok(s.id.length <= 40);
    assert.ok(s.caption.length <= 160);
    assert.ok(s.title.length <= 60);
  }
});
