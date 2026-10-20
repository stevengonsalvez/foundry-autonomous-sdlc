#!/usr/bin/env node
import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromiumLaunchOptions, loadStates, runState } from "./states.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, "../..");
const APP_DIR = path.resolve(REPO_ROOT, "app");
const DEFAULT_WEB_DIST_DIR = path.resolve(APP_DIR, "web/dist");
const DEFAULT_STATES_FILE = path.resolve(__dirname, "states.json");

// Resolve Playwright from app dependencies
const requireFromApp = createRequire(path.resolve(APP_DIR, "package.json"));
const { chromium } = requireFromApp("@playwright/test");

const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
};

const MOCK_PARCELS = [
  {
    trackingNumber: "PK1000000004",
    status: "label_created",
    estimatedDelivery: "2026-10-15",
    lastUpdate: "2026-10-10T09:12:00Z",
  },
  {
    trackingNumber: "PK1000000002",
    status: "out_for_delivery",
    estimatedDelivery: "2026-10-10",
    lastUpdate: "2026-10-10T07:55:00Z",
  },
  {
    trackingNumber: "PK1000000001",
    status: "in_transit",
    estimatedDelivery: "2026-10-13",
    lastUpdate: "2026-10-10T06:42:00Z",
  },
  {
    trackingNumber: "PK1000000006",
    status: "in_transit",
    estimatedDelivery: "2026-10-12",
    lastUpdate: "2026-10-09T23:58:00Z",
  },
  {
    trackingNumber: "PK1000000005",
    status: "exception",
    estimatedDelivery: null,
    lastUpdate: "2026-10-09T12:48:00Z",
  },
  {
    trackingNumber: "PK1000000008",
    status: "exception",
    estimatedDelivery: null,
    lastUpdate: "2026-10-08T15:10:00Z",
  },
  {
    trackingNumber: "PK1000000003",
    status: "delivered",
    estimatedDelivery: "2026-10-08",
    lastUpdate: "2026-10-08T11:32:00Z",
  },
  {
    trackingNumber: "PK1000000007",
    status: "delivered",
    estimatedDelivery: "2026-10-05",
    lastUpdate: "2026-10-05T16:20:00Z",
  },
];

const MOCK_PARCEL_FOUND = {
  trackingNumber: "PK1000000001",
  status: "in_transit",
  estimatedDelivery: "2026-10-13",
  events: [
    {
      timestamp: "2026-10-08T16:30:00Z",
      location: "Rotterdam, NL",
      description: "Shipping label created",
    },
    {
      timestamp: "2026-10-09T09:05:00Z",
      location: "Rotterdam, NL",
      description: "Picked up from sender",
    },
    {
      timestamp: "2026-10-09T13:20:00Z",
      location: "Rotterdam, NL",
      description: "Departed origin facility",
    },
    {
      timestamp: "2026-10-09T21:15:00Z",
      location: "Hamburg, DE",
      description: "Arrived at sorting hub",
    },
    {
      timestamp: "2026-10-10T06:42:00Z",
      location: "Hamburg, DE",
      description: "Departed sorting hub",
    },
  ],
};

const MOCK_PARCEL_OUT_FOR_DELIVERY = {
  trackingNumber: "PK1000000002",
  status: "out_for_delivery",
  estimatedDelivery: "2026-10-10",
  events: [
    {
      timestamp: "2026-10-08T10:10:00Z",
      location: "Antwerp, BE",
      description: "Shipping label created",
    },
    {
      timestamp: "2026-10-09T08:45:00Z",
      location: "Antwerp, BE",
      description: "Picked up from sender",
    },
    {
      timestamp: "2026-10-09T22:30:00Z",
      location: "Cologne, DE",
      description: "Arrived at sorting hub",
    },
    {
      timestamp: "2026-10-10T07:55:00Z",
      location: "Cologne, DE",
      description: "Out for delivery",
    },
  ],
};

const SKIP_ATTEMPTS = 2;

const VIEWPORTS = [
  { name: "desktop", width: 1280, height: 800 },
  { name: "mobile", width: 390, height: 844 },
];

function parseArgs() {
  const args = process.argv.slice(2);
  let outDir = path.resolve(REPO_ROOT, "ui-screenshots");
  let skipBuild = false;
  let headSha = process.env.HEAD_SHA || "";
  let statesFile = DEFAULT_STATES_FILE;
  let distDir = process.env.UI_WEB_DIST_DIR
    ? path.resolve(process.env.UI_WEB_DIST_DIR)
    : DEFAULT_WEB_DIST_DIR;

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === "--out-dir" && i + 1 < args.length) {
      outDir = path.resolve(process.cwd(), args[++i]);
    } else if (arg === "--dist" && i + 1 < args.length) {
      distDir = path.resolve(process.cwd(), args[++i]);
      skipBuild = true;
    } else if (arg === "--skip-build") {
      skipBuild = true;
    } else if (arg === "--states" && i + 1 < args.length) {
      statesFile = path.resolve(process.cwd(), args[++i]);
    } else if (arg === "--head-sha" && i + 1 < args.length) {
      headSha = args[++i];
    } else {
      console.error(`capture.mjs: unknown or invalid argument: ${arg}`);
      process.exit(1);
    }
  }

  if (!headSha) {
    try {
      headSha = execFileSync("git", ["rev-parse", "HEAD"], {
        cwd: REPO_ROOT,
        encoding: "utf-8",
      }).trim();
    } catch {
      headSha = "";
    }
  }

  return { outDir, skipBuild, headSha, distDir, statesFile };
}

function buildWeb() {
  console.log("Building app/web for screenshot capture...");
  execFileSync("npm", ["run", "build", "--workspace", "@parcel/web"], {
    cwd: APP_DIR,
    stdio: "inherit",
  });
}

function createStaticServer(distDir) {
  const server = http.createServer((req, res) => {
    const parsedUrl = new URL(req.url ?? "/", "http://127.0.0.1");
    let relativePath = decodeURIComponent(parsedUrl.pathname);
    if (relativePath === "/" || relativePath === "") {
      relativePath = "/index.html";
    }

    const filePath = path.resolve(distDir, "." + relativePath);
    const rel = path.relative(distDir, filePath);
    // Security: avoid path traversal
    if (rel === ".." || rel.startsWith(".." + path.sep) || path.isAbsolute(rel)) {
      res.writeHead(403);
      res.end("Forbidden");
      return;
    }

    if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
      const ext = path.extname(filePath).toLowerCase();
      const contentType = MIME_TYPES[ext] ?? "application/octet-stream";
      res.writeHead(200, {
        "content-type": contentType,
        "cache-control": "no-store",
      });
      fs.createReadStream(filePath).pipe(res);
      return;
    }

    // SPA fallback to index.html
    const indexPath = path.join(distDir, "index.html");
    if (fs.existsSync(indexPath)) {
      res.writeHead(200, {
        "content-type": "text/html; charset=utf-8",
        "cache-control": "no-store",
      });
      fs.createReadStream(indexPath).pipe(res);
      return;
    }

    res.writeHead(404);
    res.end("Not Found");
  });

  return server;
}

function mockResponse(url) {
  if (url.pathname === "/api/parcels") {
    return { status: 200, body: { parcels: MOCK_PARCELS } };
  }
  const parcelMatch = url.pathname.match(/^\/api\/parcels\/([^/]+)$/);
  if (!parcelMatch) return null;
  const id = decodeURIComponent(parcelMatch[1]);
  if (id === "PK1000000001") return { status: 200, body: MOCK_PARCEL_FOUND };
  if (id === "PK1000000002") return { status: 200, body: MOCK_PARCEL_OUT_FOR_DELIVERY };
  if (id === "PK9999999999") return { status: 404, body: { error: "not_found" } };
  if (!/^PK\d{10}$/.test(id)) return { status: 400, body: { error: "invalid_tracking_number" } };
  return { status: 404, body: { error: "not_found" } };
}

// Strict network intercept: mock carrier API and allow only the local static server.
async function installNetworkMocks(context, serverOrigin) {
  await context.route("**", async (route) => {
    const url = new URL(route.request().url());
    const mock = mockResponse(url);
    if (mock) {
      return route.fulfill({
        status: mock.status,
        contentType: "application/json",
        body: JSON.stringify(mock.body),
      });
    }
    if (url.origin === serverOrigin) return route.continue();
    return route.abort();
  });
}

async function capture() {
  const { outDir, skipBuild, headSha, distDir, statesFile } = parseArgs();
  const config = await loadStates(statesFile);

  if (!skipBuild || !fs.existsSync(distDir)) {
    buildWeb();
  }

  fs.mkdirSync(outDir, { recursive: true });

  const server = createStaticServer(distDir);
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });

  const { port } = server.address();
  const serverOrigin = `http://127.0.0.1:${port}`;
  console.log(`Local web preview running at ${serverOrigin}`);

  const browser = await chromium.launch(chromiumLaunchOptions());
  const manifestScreenshots = [];
  const skippedStates = new Set();

  try {
    for (const vp of VIEWPORTS) {
      for (const state of config.states) {
        if (!state.viewports.includes(vp.name)) continue;

        // A fresh context per attempt keeps localStorage presets and searches from leaking.
        // A skip is only accepted after a second fresh attempt, so a slow runner cannot
        // silently hide a feature that is really there.
        let shot = null;
        let skipReason = "";
        // A state already confirmed skipped at another viewport gets a single attempt.
        const attempts = skippedStates.has(state.id) ? 1 : SKIP_ATTEMPTS;
        for (let attempt = 1; attempt <= attempts && !shot; attempt++) {
          const context = await browser.newContext({
            viewport: { width: vp.width, height: vp.height },
            deviceScaleFactor: 1,
            reducedMotion: "reduce",
            locale: "en-GB",
            timezoneId: "UTC",
            permissions: ["clipboard-read", "clipboard-write"],
          });
          try {
            await installNetworkMocks(context, serverOrigin);
            const page = await context.newPage();
            console.log(`Capturing state: ${state.id} (${vp.name})${attempt > 1 ? ` retry ${attempt}` : ""}`);
            const result = await runState(page, context, state, {
              origin: serverOrigin,
              routes: config.routes,
            });
            if (result.status === "skipped") {
              skipReason = result.reason;
              continue;
            }
            const filename = `${state.id}-${vp.name}.png`;
            const filePath = path.join(outDir, filename);
            await page.screenshot({ path: filePath, fullPage: false });
            shot = { filename, filePath };
          } finally {
            await context.close();
          }
        }

        if (!shot) {
          skippedStates.add(state.id);
          console.log(`  skipped ${state.id} (${vp.name}): ${skipReason}`);
          continue;
        }

        const buffer = fs.readFileSync(shot.filePath);
        const sha256 = crypto.createHash("sha256").update(buffer).digest("hex");
        manifestScreenshots.push({
          filename: shot.filename,
          state: state.id,
          route: state.route,
          viewport: vp.name,
          title: state.title,
          caption: state.caption,
          sha256,
          size: buffer.length,
        });
        console.log(`  saved ${shot.filename} (${buffer.length} bytes, sha256: ${sha256.slice(0, 12)}...)`);
      }
    }

    // A state counts as skipped only when no viewport captured it.
    const captured = new Set(manifestScreenshots.map((s) => s.state));
    const skipped = config.states.map((s) => s.id).filter((id) => !captured.has(id));

    const manifest = {
      version: 1,
      head_sha: headSha || undefined,
      screenshots: manifestScreenshots,
      skipped,
    };

    const manifestPath = path.join(outDir, "manifest.json");
    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + "\n");
    console.log(
      `Wrote manifest to ${manifestPath}: ${manifestScreenshots.length} screenshots, ` +
        `${captured.size} states captured, ${skipped.length} skipped (${skipped.join(", ") || "none"}).`,
    );
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
    console.log("Cleaned up browser and static server.");
  }
}

capture().catch((err) => {
  console.error("Capture failed:", err);
  process.exit(1);
});
