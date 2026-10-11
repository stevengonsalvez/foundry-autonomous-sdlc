import { defineConfig, devices } from "@playwright/test";

// Smoke tests run against an already deployed site: no web server is started here.
// SMOKE_URL is the full URL of the deployed app, path prefix included, for example
// https://stevengonsalvez.github.io/foundry-autonomous-sdlc/staging/
const smokeUrl = process.env["SMOKE_URL"];
if (!smokeUrl) {
  throw new Error("SMOKE_URL is required, for example SMOKE_URL=https://example.github.io/repo/staging/");
}

export default defineConfig({
  testDir: "./smoke",
  fullyParallel: true,
  forbidOnly: Boolean(process.env["CI"]),
  retries: 1,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report/smoke" }]],
  outputDir: "test-results/smoke",
  use: {
    // The trailing slash matters: relative paths in the specs resolve below the prefix.
    baseURL: smokeUrl.endsWith("/") ? smokeUrl : `${smokeUrl}/`,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
