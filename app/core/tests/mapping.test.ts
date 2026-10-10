import { describe, expect, it } from "vitest";
import { CarrierUnavailableError, toParcel, toParcelSummary, type CarrierShipment, type CarrierState } from "../src";

const shipment: CarrierShipment = {
  id: "PK1000000042",
  state: "TRANSIT",
  eta: "2026-10-14",
  history: [
    { ts: "2026-10-10T08:30:00Z", place: "Hamburg, DE", note: "Departed sorting hub" },
    { ts: "2026-10-09T17:05:00Z", place: "Hamburg, DE", note: "Arrived at sorting hub" },
    { ts: "2026-10-09T09:00:00Z", place: "Rotterdam, NL", note: "Picked up from sender" },
  ],
};

describe("toParcel", () => {
  it("renames carrier fields to domain fields and puts events oldest first", () => {
    expect(toParcel(shipment)).toEqual({
      trackingNumber: "PK1000000042",
      status: "in_transit",
      estimatedDelivery: "2026-10-14",
      events: [
        { timestamp: "2026-10-09T09:00:00Z", location: "Rotterdam, NL", description: "Picked up from sender" },
        { timestamp: "2026-10-09T17:05:00Z", location: "Hamburg, DE", description: "Arrived at sorting hub" },
        { timestamp: "2026-10-10T08:30:00Z", location: "Hamburg, DE", description: "Departed sorting hub" },
      ],
    });
  });

  it.each<[CarrierState, string]>([
    ["CREATED", "label_created"],
    ["TRANSIT", "in_transit"],
    ["OFD", "out_for_delivery"],
    ["DELIVERED", "delivered"],
    ["EXCEPTION", "exception"],
  ])("maps carrier state %s to status %s", (state, status) => {
    expect(toParcel({ ...shipment, state }).status).toBe(status);
  });

  it("keeps a missing estimate as null", () => {
    expect(toParcel({ ...shipment, eta: null }).estimatedDelivery).toBeNull();
  });

  it("does not mutate the carrier payload", () => {
    const before = structuredClone(shipment);
    toParcel(shipment);
    expect(shipment).toEqual(before);
  });
});

describe("toParcelSummary", () => {
  it("reports the newest event time as the last update", () => {
    expect(toParcelSummary(shipment)).toEqual({
      trackingNumber: "PK1000000042",
      status: "in_transit",
      estimatedDelivery: "2026-10-14",
      lastUpdate: "2026-10-10T08:30:00Z",
    });
  });

  it("refuses a shipment that has no history to date it by", () => {
    expect(() => toParcelSummary({ ...shipment, history: [] })).toThrow(CarrierUnavailableError);
  });
});
