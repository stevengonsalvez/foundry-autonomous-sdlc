import { describe, expect, it } from "vitest";
import { parseTrackingNumber } from "../src";

describe("parseTrackingNumber whitespace handling", () => {
  it("ignores leading and trailing whitespace including spaces, tabs, and line breaks", () => {
    expect(parseTrackingNumber(" PK1000000001 ")).toBe("PK1000000001");
    expect(parseTrackingNumber("\tPK1000000001\t")).toBe("PK1000000001");
    expect(parseTrackingNumber("\nPK1000000001\n")).toBe("PK1000000001");
    expect(parseTrackingNumber("\r\nPK1000000001\r\n")).toBe("PK1000000001");
  });
});
