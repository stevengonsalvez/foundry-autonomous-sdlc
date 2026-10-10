import { describe, expect, it } from "vitest";
import { loadCarrierContract } from "../src";

const contract = loadCarrierContract();

const shipment = {
  id: "PK1000000001",
  state: "TRANSIT",
  eta: "2026-10-13",
  history: [{ ts: "2026-10-10T06:42:00Z", place: "Hamburg, DE", note: "Departed sorting hub" }],
};

describe("findOperation", () => {
  it("matches a path template and reports the operation id", () => {
    expect(contract.findOperation("GET", "/v1/shipments/PK1000000001")?.operationId).toBe("getShipment");
    expect(contract.findOperation("get", "/v1/shipments")?.operationId).toBe("listShipments");
  });

  it("does not match undocumented paths or methods", () => {
    expect(contract.findOperation("GET", "/v2/shipments")).toBeUndefined();
    expect(contract.findOperation("POST", "/v1/shipments")).toBeUndefined();
    expect(contract.findOperation("GET", "/v1/shipments/a/b")).toBeUndefined();
  });
});

describe("validateResponse", () => {
  it("accepts conforming bodies", () => {
    expect(contract.validateResponse("GET", "/v1/shipments/PK1000000001", 200, shipment)).toEqual({ valid: true, errors: [] });
    expect(contract.validateResponse("GET", "/v1/shipments", 200, { items: [shipment, { ...shipment, eta: null }] }).valid).toBe(true);
    expect(contract.validateResponse("GET", "/v1/shipments/PK9999999999", 404, { code: "UNKNOWN_SHIPMENT" }).valid).toBe(true);
  });

  it.each([
    ["a missing field", { ...shipment, eta: undefined }],
    ["an undocumented field", { ...shipment, carrier: "acme" }],
    ["an unknown state", { ...shipment, state: "LOST" }],
    ["a malformed date", { ...shipment, eta: "13/10/2026" }],
    ["a malformed timestamp", { ...shipment, history: [{ ...shipment.history[0], ts: "yesterday" }] }],
    ["an empty history", { ...shipment, history: [] }],
    ["a bad id", { ...shipment, id: "pk1" }],
  ])("rejects %s", (_name, body) => {
    const result = contract.validateResponse("GET", "/v1/shipments/PK1000000001", 200, JSON.parse(JSON.stringify(body)));
    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThan(0);
  });

  it("rejects an undocumented status code", () => {
    const result = contract.validateResponse("GET", "/v1/shipments/PK1000000001", 500, {});
    expect(result.valid).toBe(false);
    expect(result.errors[0]).toMatch(/500/);
  });

  it("rejects a response for an undocumented operation", () => {
    const result = contract.validateResponse("DELETE", "/v1/shipments/PK1000000001", 200, {});
    expect(result.valid).toBe(false);
    expect(result.errors[0]).toMatch(/DELETE/);
  });
});
