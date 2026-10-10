import { describe, expect, it } from "vitest";
import { parseTrackingNumber } from "../src";

describe("parseTrackingNumber normalization", () => {
  it("accepts lowercase tracking numbers by normalising to uppercase", () => {
    expect(parseTrackingNumber("pk1000000001")).toBe("PK1000000001");
  });

  it("trims surrounding whitespace and uppercases before validation", () => {
    expect(parseTrackingNumber("  pk1000000001  ")).toBe("PK1000000001");
  });
});
