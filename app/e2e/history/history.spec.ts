import { execSync } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, "../../..");

const MIME_TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
};

let tempScreenshotsDir: string;
let tempHistoryDir: string;
let server: http.Server;
let historyUrl: string;

test.beforeAll(async () => {
  // 1. Create temporary mock screenshots fixture
  tempScreenshotsDir = fs.mkdtempSync(path.join(os.tmpdir(), "history-e2e-screenshots-"));
  const stubPng = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
    "base64"
  );
  const routes = ["home", "parcel-found", "not-found", "invalid-input"];
  const viewports = ["desktop", "mobile"];

  for (const tag of ["v0.1.0", "v0.4.0", "v0.5.0"]) {
    const tagDir = path.join(tempScreenshotsDir, tag);
    fs.mkdirSync(tagDir, { recursive: true });
    const screenshots = [];
    for (const r of routes) {
      for (const vp of viewports) {
        const fn = `${r}-${vp}.png`;
        fs.writeFileSync(path.join(tagDir, fn), stubPng);
        screenshots.push({
          route: r,
          viewport: vp,
          filename: fn,
          sha256: "stub",
          size_bytes: stubPng.length,
        });
      }
    }
    fs.writeFileSync(
      path.join(tagDir, "manifest.json"),
      JSON.stringify({
        version: 1,
        tag,
        commit_sha: "a1b2c3d4e5f60718",
        reproducible: true,
        screenshots,
      })
    );
  }

  // 2. Create temporary output directory and generate history site dynamically
  tempHistoryDir = fs.mkdtempSync(path.join(os.tmpdir(), "history-e2e-output-"));
  const generatorScript = path.join(REPO_ROOT, "scripts/ui/generate_history.py");
  execSync(
    `python3 "${generatorScript}" --output-dir "${tempHistoryDir}" --screenshots-dir "${tempScreenshotsDir}"`,
    { cwd: REPO_ROOT, stdio: "pipe" }
  );

  // 3. Serve dynamically generated site
  await new Promise<void>((resolve, reject) => {
    server = http.createServer((req, res) => {
      const parsedUrl = new URL(req.url ?? "/", "http://127.0.0.1");
      let relPath = decodeURIComponent(parsedUrl.pathname);
      if (relPath === "/" || relPath === "") {
        relPath = "/index.html";
      }
      const filePath = path.join(tempHistoryDir, relPath);
      if (!filePath.startsWith(tempHistoryDir)) {
        res.writeHead(403);
        res.end("Forbidden");
        return;
      }
      if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
        const ext = path.extname(filePath).toLowerCase();
        const contentType = MIME_TYPES[ext] ?? "application/octet-stream";
        const content = fs.readFileSync(filePath);
        res.writeHead(200, {
          "Content-Type": contentType,
          "Content-Length": content.length,
        });
        res.end(content);
      } else {
        res.writeHead(404);
        res.end("Not Found");
      }
    });

    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      if (addr && typeof addr === "object") {
        historyUrl = `http://127.0.0.1:${addr.port}/`;
        resolve();
      } else {
        reject(new Error("Failed to bind ephemeral port for history server"));
      }
    });
  });
});

test.afterAll(async () => {
  await new Promise<void>((resolve) => {
    if (server) {
      server.close(() => resolve());
    } else {
      resolve();
    }
  });

  if (tempHistoryDir && fs.existsSync(tempHistoryDir)) {
    fs.rmSync(tempHistoryDir, { recursive: true, force: true });
  }
  if (tempScreenshotsDir && fs.existsSync(tempScreenshotsDir)) {
    fs.rmSync(tempScreenshotsDir, { recursive: true, force: true });
  }
});

test.describe("App Evolution Showcase (/history/)", () => {
  test("renders with no console errors and no external requests", async ({ page }) => {
    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    const outgoingRequests: string[] = [];

    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text());
      }
    });

    page.on("pageerror", (err) => {
      pageErrors.push(err.message);
    });

    page.on("request", (req) => {
      outgoingRequests.push(req.url());
    });

    await page.goto(historyUrl);

    // Verify main landmarks
    await expect(page.getByRole("heading", { level: 1, name: "App Evolution" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: "Then vs Now" })).toBeVisible();
    await expect(page.getByRole("toolbar", { name: "Timeline view controls" })).toBeVisible();

    // Zero console errors and zero uncaught page errors
    expect(consoleErrors).toEqual([]);
    expect(pageErrors).toEqual([]);

    // Zero external requests: every outgoing request MUST originate from the local server
    expect(outgoingRequests.length).toBeGreaterThan(0);
    for (const reqUrl of outgoingRequests) {
      expect(
        reqUrl.startsWith(historyUrl) || reqUrl.startsWith("data:"),
        `External network request detected: ${reqUrl}`
      ).toBe(true);
    }
  });

  test("passes accessibility quality bar (axe-clean, wcag2a, wcag2aa, wcag21aa)", async ({ page }) => {
    await page.goto(historyUrl);
    await expect(page.getByRole("heading", { level: 1, name: "App Evolution" })).toBeVisible();

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();

    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });

  test("interactive viewport toggle switches between desktop and mobile", async ({ page }) => {
    await page.goto(historyUrl);

    const desktopBtn = page.getByRole("button", { name: "Desktop (1280px)" });
    const mobileBtn = page.getByRole("button", { name: "Mobile (390px)" });

    await expect(desktopBtn).toHaveAttribute("aria-pressed", "true");
    await expect(mobileBtn).toHaveAttribute("aria-pressed", "false");

    // Click mobile toggle
    await mobileBtn.click();
    await expect(mobileBtn).toHaveAttribute("aria-pressed", "true");
    await expect(desktopBtn).toHaveAttribute("aria-pressed", "false");

    // Click desktop toggle to revert
    await desktopBtn.click();
    await expect(desktopBtn).toHaveAttribute("aria-pressed", "true");
    await expect(mobileBtn).toHaveAttribute("aria-pressed", "false");
  });

  test("interactive route switcher switches routes across timeline comparisons", async ({ page }) => {
    await page.goto(historyUrl);

    const homeBtn = page.getByRole("button", { name: "Home" });
    const parcelFoundBtn = page.getByRole("button", { name: "Parcel Found" });
    const notFoundBtn = page.getByRole("button", { name: "Not Found" });
    const invalidInputBtn = page.getByRole("button", { name: "Invalid Input" });

    await expect(homeBtn).toHaveAttribute("aria-pressed", "true");

    await parcelFoundBtn.click();
    await expect(parcelFoundBtn).toHaveAttribute("aria-pressed", "true");
    await expect(homeBtn).toHaveAttribute("aria-pressed", "false");

    await notFoundBtn.click();
    await expect(notFoundBtn).toHaveAttribute("aria-pressed", "true");

    await invalidInputBtn.click();
    await expect(invalidInputBtn).toHaveAttribute("aria-pressed", "true");
  });

  test("renders then-vs-now strip and side-by-side timeline comparisons dynamically from data.json", async ({ page }) => {
    const dataJson = JSON.parse(
      fs.readFileSync(path.join(tempHistoryDir, "data.json"), "utf-8")
    );
    const entries = dataJson.entries || [];
    const latestEntry = entries[0];
    const oldestEntry = entries[entries.length - 1];
    const beforeTag = latestEntry?.before?.tag ?? "Initial";

    await page.goto(historyUrl);

    // Then vs Now section
    const thenVsNowSection = page.locator(".then-vs-now");
    await expect(thenVsNowSection).toBeVisible();
    if (oldestEntry) {
      await expect(thenVsNowSection.getByText(`First Release (${oldestEntry.tag})`)).toBeVisible();
    }
    if (latestEntry) {
      await expect(thenVsNowSection.getByText(`Current Release (${latestEntry.tag})`)).toBeVisible();
    }

    // Timeline items count dynamically asserted
    const timelineItems = page.locator(".timeline-item");
    const count = await timelineItems.count();
    expect(count).toBe(entries.length);

    // Latest release card header
    if (latestEntry) {
      await expect(page.locator(".tag-badge").first()).toContainText(latestEntry.tag);
      await expect(page.locator(".compare-col-header").first()).toContainText(`Before (${beforeTag})`);
      await expect(page.locator(".compare-col-header").nth(1)).toContainText(`After (${latestEntry.tag})`);
    }
  });

  test("keyboard navigation supports skip-link to main content", async ({ page }) => {
    await page.goto(historyUrl);

    // Focus skip link
    await page.keyboard.press("Tab");
    const skipLink = page.getByRole("link", { name: "Skip to content" });
    await expect(skipLink).toBeFocused();

    await page.keyboard.press("Enter");
    const mainHeading = page.getByRole("heading", { level: 1, name: "App Evolution" });
    await expect(mainHeading).toBeVisible();
  });
});
