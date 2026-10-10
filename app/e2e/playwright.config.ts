import { defineConfig, devices } from "@playwright/test";

const mockPort = Number(process.env["MOCK_PORT"] ?? 4010);
const apiPort = Number(process.env["API_PORT"] ?? 4000);
const webPort = Number(process.env["WEB_PORT"] ?? 4173);
const host = "127.0.0.1";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: Boolean(process.env["CI"]),
  retries: process.env["CI"] ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://${host}:${webPort}`,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  // The whole stack starts here: carrier mock, API against the mock, then the built web app proxying to the API.
  webServer: [
    {
      command: "npm run start --workspace @parcel/carrier-mock",
      cwd: "..",
      env: { PORT: String(mockPort) },
      url: `http://${host}:${mockPort}/v1/shipments`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "npm run start --workspace @parcel/api",
      cwd: "..",
      env: { PORT: String(apiPort), CARRIER_URL: `http://${host}:${mockPort}` },
      url: `http://${host}:${apiPort}/api/parcels`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npm run build --workspace @parcel/web && npm run preview --workspace @parcel/web -- --host ${host} --port ${webPort} --strictPort`,
      cwd: "..",
      env: { API_URL: `http://${host}:${apiPort}` },
      url: `http://${host}:${webPort}/`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
