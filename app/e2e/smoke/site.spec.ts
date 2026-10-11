import { randomUUID } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";

// Every path below is relative on purpose: the same build is served at the site root and under /staging/.
// Every request for a page or for build.json carries a query nobody has used before: the CDN ignores the
// browser's no-cache headers and can serve a copy that is minutes old.
const home = (hash = "") => `./?cb=${randomUUID()}${hash}`;

function watch(page: Page) {
  const problems: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(`console error: ${message.text()}`);
  });
  page.on("pageerror", (error) => problems.push(`page error: ${error.message}`));
  page.on("requestfailed", (request) => problems.push(`request failed: ${request.url()}`));
  page.on("response", (response) => {
    if (response.status() >= 400) problems.push(`HTTP ${response.status()}: ${response.url()}`);
  });
  return problems;
}

test.describe("deployed site", () => {
  test("home page shows the heading", async ({ page }) => {
    await page.goto(home());
    await expect(page.getByRole("heading", { level: 1, name: "Track a parcel", exact: true })).toBeVisible();
  });

  test("tracking PK1000000001 shows a timeline of 5 events", async ({ page }) => {
    await page.goto(home());
    await page.getByLabel("Tracking number").fill("PK1000000001");
    await page.getByRole("button", { name: "Track" }).click();

    await expect(page).toHaveURL(/#\/parcel\/PK1000000001$/);
    await expect(page.getByRole("heading", { level: 1, name: "PK1000000001" })).toBeVisible();
    const events = page.getByRole("list", { name: "Shipment history" }).getByRole("listitem");
    await expect(events).toHaveCount(5);
  });

  test("an unknown tracking number shows the not-found alert", async ({ page }) => {
    await page.goto(home());
    await page.getByLabel("Tracking number").fill("PK9999999999");
    await page.keyboard.press("Enter");

    const alert = page.getByRole("alert");
    await expect(alert).toContainText("Parcel not found");
    await expect(alert).toContainText("PK9999999999");
  });

  test("build.json names the commit that was deployed", async ({ request }) => {
    const expected = process.env["EXPECTED_SHA"];
    expect(expected, "EXPECTED_SHA must be set to the sha this run deployed").toBeTruthy();

    const response = await request.get(`build.json?cb=${randomUUID()}`);
    expect(response.status()).toBe(200);
    const build = (await response.json()) as { sha?: string };
    expect(build.sha).toBe(expected);
  });

  test("the page loads and navigates without console errors", async ({ page }) => {
    const problems = watch(page);
    await page.goto(home());
    await expect(page.getByRole("heading", { level: 1, name: "Track a parcel", exact: true })).toBeVisible();
    await page.goto(home("#/parcel/PK1000000002"));
    await expect(page.getByRole("heading", { level: 1, name: "PK1000000002" })).toBeVisible();
    expect(problems).toEqual([]);
  });

  test("it loads from a path prefix, so its assets are relative", async ({ page, baseURL }) => {
    const prefix = new URL(baseURL ?? "").pathname;
    expect(prefix, "SMOKE_URL must include the site path prefix").not.toBe("/");

    const loaded = new Map<string, number>();
    page.on("response", (response) => loaded.set(response.url(), response.status()));
    await page.goto(home());
    await expect(page.getByRole("heading", { level: 1, name: "Track a parcel", exact: true })).toBeVisible();

    const assets = await page.evaluate(() =>
      [
        ...Array.from(document.querySelectorAll<HTMLScriptElement>("script[src]"), (s) => s.src),
        ...Array.from(document.querySelectorAll<HTMLLinkElement>("link[rel=stylesheet]"), (l) => l.href),
      ],
    );
    expect(assets.length).toBeGreaterThanOrEqual(2);
    for (const asset of assets) {
      expect(new URL(asset).pathname.startsWith(prefix), `${asset} is outside ${prefix}`).toBe(true);
      expect(loaded.get(asset), asset).toBe(200);
    }
  });
});
