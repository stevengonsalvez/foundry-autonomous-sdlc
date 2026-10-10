import { describe, expect, it } from "vitest";
import { parseTrackingNumber } from "../src";

describe("parseTrackingNumber", () => {
  it("accepts PK followed by exactly ten digits", () => {
    expect(parseTrackingNumber("PK1000000001")).toBe("PK1000000001");
    expect(parseTrackingNumber("PK0000000000")).toBe("PK0000000000");
  });

  it.each([
    ["empty", ""],
    ["too few digits", "PK123456789"],
    ["too many digits", "PK10000000011"],
    ["wrong prefix", "XX1000000001"],
    ["letters among the digits", "PK10000000AB"],
    ["leading whitespace", " PK1000000001"],
    ["trailing newline", "PK1000000001\n"],
    ["embedded in text", "see PK1000000001 here"],
  ])("rejects %s", (_name, input) => {
    expect(parseTrackingNumber(input)).toBeNull();
  });
});
