import { describe, expect, it } from "vitest";
import { formatDateTime } from "../src/format";

describe("formatDateTime", () => {
  it("renders an instant in UTC, day first", () => {
    expect(formatDateTime("2026-10-10T06:42:00Z")).toBe("10 Oct 2026, 06:42 UTC");
    expect(formatDateTime("2026-10-09T23:58:00Z")).toBe("9 Oct 2026, 23:58 UTC");
  });

  it("falls back to the raw text when it is not a date", () => {
    expect(formatDateTime("later")).toBe("later");
  });
});
