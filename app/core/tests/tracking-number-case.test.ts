import { describe, expect, it } from "vitest";
import type { TrackingNumber } from "../src";
import { parseTrackingNumber } from "../src";

describe("parseTrackingNumber case-insensitivity", () => {
  it("accepts lowercase input and normalises to uppercase", () => {
    const input = "pk1000000001";
    const parsed = parseTrackingNumber(input);
    // The canonical form returned must be uppercase
    expect(parsed).toBe("PK1000000001" as TrackingNumber);
  });

  it("still rejects genuinely malformed numbers even if letters are lowercase", () => {
    expect(parseTrackingNumber("pk123")).toBeNull(); // too few digits
    expect(parseTrackingNumber("xx1000000001")).toBeNull(); // wrong prefix
  });
});
