import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, "../../..");
const HISTORY_DIR = path.resolve(REPO_ROOT, "history");

const MIME_TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
};

let server: http.Server;
let historyUrl: string;

test.beforeAll(async () => {
  await new Promise<void>((resolve, reject) => {
    server = http.createServer((req, res) => {
      const parsedUrl = new URL(req.url ?? "/", "http://127.0.0.1");
      let relPath = decodeURIComponent(parsedUrl.pathname);
      if (relPath === "/" || relPath === "") {
        relPath = "/index.html";
      }
      const filePath = path.join(HISTORY_DIR, relPath);
      if (!filePath.startsWith(HISTORY_DIR)) {
        res.writeHead(403);
        res.end("Forbidden");
        return;
      }
      if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
        const ext = path.extname(filePath).toLowerCase();
        const contentType = MIME_TYPES[ext] ?? "application/octet-stream";
        res.writeHead(200, { "Content-Type": contentType });
        fs.createReadStream(filePath).pipe(res);
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

  test("passes accessibility quality bar (axe-clean, wcag2aa, wcag21aa)", async ({ page }) => {
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

  test("renders then-vs-now strip and side-by-side timeline comparisons", async ({ page }) => {
    await page.goto(historyUrl);

    // Then vs Now section
    const thenVsNowSection = page.locator(".then-vs-now");
    await expect(thenVsNowSection).toBeVisible();
    await expect(thenVsNowSection.getByText("First Release (v0.1.0)")).toBeVisible();
    await expect(thenVsNowSection.getByText("Current Release (v0.4.0)")).toBeVisible();

    // Timeline items
    const timelineItems = page.locator(".timeline-item");
    const count = await timelineItems.count();
    expect(count).toBeGreaterThanOrEqual(5);

    // Latest release card header
    await expect(page.locator(".tag-badge").first()).toContainText("v0.4.0");

    // Side by side comparisons
    await expect(page.locator(".compare-col-header").first()).toContainText("Before (v0.3.1)");
    await expect(page.locator(".compare-col-header").nth(1)).toContainText("After (v0.4.0)");
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
