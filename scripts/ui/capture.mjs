#!/usr/bin/env node
import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, "../..");
const APP_DIR = path.resolve(REPO_ROOT, "app");
const WEB_DIST_DIR = path.resolve(APP_DIR, "web/dist");

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

const ROUTES = [
  {
    name: "home",
    path: "/#/",
    waitFor: async (page) => {
      await page.waitForSelector("table", { state: "visible" });
    },
  },
  {
    name: "parcel-found",
    path: "/#/parcel/PK1000000001",
    waitFor: async (page) => {
      await page.waitForSelector("h1#page-title", { state: "visible" });
      await page.waitForSelector(".timeline", { state: "visible" });
    },
  },
  {
    name: "not-found",
    path: "/#/parcel/PK9999999999",
    waitFor: async (page) => {
      await page.waitForSelector(".notice--error", { state: "visible" });
    },
  },
  {
    name: "invalid-input",
    path: "/#/parcel/12345",
    waitFor: async (page) => {
      await page.waitForSelector(".notice--error", { state: "visible" });
    },
  },
];

const VIEWPORTS = [
  { name: "desktop", width: 1280, height: 800 },
  { name: "mobile", width: 390, height: 844 },
];

function parseArgs() {
  const args = process.argv.slice(2);
  let outDir = path.resolve(REPO_ROOT, "ui-screenshots");
  let skipBuild = false;
  let headSha = process.env.HEAD_SHA || "";

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === "--out-dir" && i + 1 < args.length) {
      outDir = path.resolve(process.cwd(), args[++i]);
    } else if (arg === "--skip-build") {
      skipBuild = true;
    } else if (arg === "--head-sha" && i + 1 < args.length) {
      headSha = args[++i];
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

  return { outDir, skipBuild, headSha };
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

async function capture() {
  const { outDir, skipBuild, headSha } = parseArgs();

  if (!skipBuild || !fs.existsSync(WEB_DIST_DIR)) {
    buildWeb();
  }

  fs.mkdirSync(outDir, { recursive: true });

  const server = createStaticServer(WEB_DIST_DIR);
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });

  const { port } = server.address();
  const serverOrigin = `http://127.0.0.1:${port}`;
  console.log(`Local web preview running at ${serverOrigin}`);

  const browser = await chromium.launch({ headless: true });
  const manifestScreenshots = [];

  try {
    for (const vp of VIEWPORTS) {
      console.log(`Setting up context for viewport ${vp.name} (${vp.width}x${vp.height})...`);
      const context = await browser.newContext({
        viewport: { width: vp.width, height: vp.height },
        deviceScaleFactor: 1,
        reducedMotion: "reduce",
        locale: "en-GB",
        timezoneId: "UTC",
      });

      // Strict network intercept: mock carrier API and allow only local static server
      await context.route("**", async (route) => {
        const req = route.request();
        const url = new URL(req.url());

        if (url.pathname === "/api/parcels") {
          return route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ parcels: MOCK_PARCELS }),
          });
        }

        const parcelMatch = url.pathname.match(/^\/api\/parcels\/([^/]+)$/);
        if (parcelMatch) {
          const id = decodeURIComponent(parcelMatch[1]);
          if (id === "PK1000000001") {
            return route.fulfill({
              status: 200,
              contentType: "application/json",
              body: JSON.stringify(MOCK_PARCEL_FOUND),
            });
          }
          if (id === "PK9999999999") {
            return route.fulfill({
              status: 404,
              contentType: "application/json",
              body: JSON.stringify({ error: "not_found" }),
            });
          }
          if (!/^PK\d{10}$/.test(id)) {
            return route.fulfill({
              status: 400,
              contentType: "application/json",
              body: JSON.stringify({ error: "invalid_tracking_number" }),
            });
          }
          return route.fulfill({
            status: 404,
            contentType: "application/json",
            body: JSON.stringify({ error: "not_found" }),
          });
        }

        if (url.origin === serverOrigin) {
          return route.continue();
        }

        // Abort all other external network traffic
        return route.abort();
      });

      const page = await context.newPage();

      for (const route of ROUTES) {
        const targetUrl = `${serverOrigin}${route.path}`;
        console.log(`Capturing route: ${route.name} (${vp.name}) -> ${targetUrl}`);
        await page.goto(targetUrl, { waitUntil: "domcontentloaded" });

        // Ensure fonts and DOM are ready
        await page.evaluate(() => document.fonts.ready);
        await route.waitFor(page);

        // Enforce reduced motion and eliminate animation delay/duration
        await page.addStyleTag({
          content: `
            *, *::before, *::after {
              animation-duration: 0s !important;
              animation-delay: 0s !important;
              transition-duration: 0s !important;
              transition-delay: 0s !important;
            }
          `,
        });

        // Small settled delay for rendering stability
        await page.waitForTimeout(100);

        const filename = `${route.name}-${vp.name}.png`;
        const filePath = path.join(outDir, filename);

        await page.screenshot({ path: filePath, fullPage: false });

        const buffer = fs.readFileSync(filePath);
        const sha256 = crypto.createHash("sha256").update(buffer).digest("hex");
        const size = buffer.length;

        manifestScreenshots.push({
          filename,
          route: route.name,
          viewport: vp.name,
          sha256,
          size,
        });

        console.log(`Saved ${filename} (${size} bytes, sha256: ${sha256.slice(0, 12)}...)`);
      }

      await page.close();
      await context.close();
    }

    const manifest = {
      version: 1,
      head_sha: headSha || undefined,
      screenshots: manifestScreenshots,
    };

    const manifestPath = path.join(outDir, "manifest.json");
    fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + "\n");
    console.log(`Wrote manifest to ${manifestPath} with ${manifestScreenshots.length} screenshots.`);
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
