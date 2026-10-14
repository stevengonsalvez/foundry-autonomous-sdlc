import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const webRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const viteBin = join(dirname(createRequire(import.meta.url).resolve("vite/package.json")), "bin", "vite.js");

function build(mode: string, outDir: string): string {
  execFileSync(process.execPath, [viteBin, "build", "--mode", mode, "--outDir", outDir, "--emptyOutDir"], {
    cwd: webRoot,
    stdio: "pipe",
  });
  return readFileSync(join(outDir, "index.html"), "utf8");
}

describe("vite build base", () => {
  let dir: string;
  beforeAll(() => {
    dir = mkdtempSync(join(tmpdir(), "vite-base-"));
  });
  afterAll(() => rmSync(dir, { recursive: true, force: true }));

  it("pages mode references its assets relatively, so one artifact serves prod and /staging/", () => {
    const html = build("pages", join(dir, "pages"));
    const assets = [...html.matchAll(/(?:src|href)="([^"]*assets\/[^"]+)"/g)].map((m) => m[1]);
    expect(assets.length).toBeGreaterThanOrEqual(2);
    for (const asset of assets) expect(asset).toMatch(/^\.\/assets\//);
  }, 15000);

  it("keeps absolute asset paths for the normal build", () => {
    const html = build("production", join(dir, "normal"));
    expect(html).toMatch(/(?:src|href)="\/assets\//);
  }, 15000);
});
