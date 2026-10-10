import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    projects: [
      { test: { name: "core", root: "core", include: ["tests/**/*.test.ts"] } },
      { test: { name: "contracts", root: "contracts", include: ["tests/**/*.test.ts"] } },
      { test: { name: "carrier-mock", root: "carrier-mock", include: ["tests/**/*.test.ts"] } },
      { test: { name: "api", root: "api", include: ["tests/**/*.test.ts"] } },
      "web",
    ],
    coverage: {
      provider: "v8",
      include: ["core/src/**", "carrier-mock/src/**", "api/src/**", "web/src/**"],
      exclude: ["**/main.ts", "**/main.tsx", "**/index.ts", "**/*.d.ts"],
      reporter: ["text", "json-summary", "lcov"],
      reportsDirectory: "coverage",
      thresholds: { lines: 80 },
    },
  },
});
