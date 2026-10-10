import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test.describe("tracking a parcel", () => {
  test("search for a parcel and read its timeline", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1, name: "Track your parcel" })).toBeVisible();

    await page.getByLabel("Tracking number").fill("PK1000000001");
    await page.getByRole("button", { name: "Track" }).click();

    await expect(page).toHaveURL(/#\/parcel\/PK1000000001$/);
    const heading = page.getByRole("heading", { level: 1, name: "PK1000000001" });
    await expect(heading).toBeVisible();
    await expect(heading).toBeFocused();
    await expect(page.locator(".badge", { hasText: "In transit" })).toBeVisible();

    const events = page.getByRole("list", { name: "Shipment history" }).getByRole("listitem");
    await expect(events).toHaveCount(5);
    await expect(events.first()).toContainText("Shipping label created");
    await expect(events.first()).toContainText("Rotterdam, NL");
    await expect(events.last()).toContainText("Departed sorting hub");
    await expect(events.last()).toContainText("Latest");
  });

  test("open a recent parcel from the home page", async ({ page }) => {
    await page.goto("/");
    const table = page.getByRole("table", { name: "Recent parcels" });
    await expect(table.getByRole("row")).toHaveCount(9);

    await table.getByRole("link", { name: "PK1000000003" }).click();

    await expect(page.getByRole("heading", { level: 1, name: "PK1000000003" })).toBeVisible();
    await expect(page.locator(".badge", { hasText: "Delivered" })).toBeVisible();
    await expect(page.getByRole("listitem").last()).toContainText("Delivered, signed for by recipient");
  });

  test("tell the visitor when the parcel is unknown", async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Tracking number").fill("PK9999999999");
    await page.keyboard.press("Enter");

    const alert = page.getByRole("alert");
    await expect(alert).toContainText("Parcel not found");
    await expect(alert).toContainText("PK9999999999");
    await page.getByRole("link", { name: /Track another parcel/ }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Track your parcel" })).toBeVisible();
  });

  test("tell the visitor when the number is malformed", async ({ page }) => {
    await page.goto("/#/parcel/12345");
    await expect(page.getByRole("alert")).toContainText("That isn't a valid tracking number");
  });
});

test.describe("quality bar", () => {
  const pages = [
    ["home", "/", "table"],
    ["parcel", "/#/parcel/PK1000000002", "list"],
    ["unknown parcel", "/#/parcel/PK9999999999", "alert"],
  ] as const;

  for (const [name, path, loadedRole] of pages) {
    test(`the ${name} page has no accessibility violations`, async ({ page }) => {
      await page.goto(path);
      await expect(page.getByRole(loadedRole)).toBeVisible();
      const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
    });

    test(`the ${name} page fits a 360px wide screen`, async ({ page }) => {
      await page.setViewportSize({ width: 360, height: 740 });
      await page.goto(path);
      await expect(page.getByRole(loadedRole)).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(0);
    });
  }
});
