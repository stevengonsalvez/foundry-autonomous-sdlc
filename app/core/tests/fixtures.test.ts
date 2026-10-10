import { describe, expect, it } from "vitest";
import {
  FixtureCarrierClient,
  PARCEL_STATUSES,
  SAMPLE_SHIPMENTS,
  createParcelService,
  parseTrackingNumber,
} from "../src";

describe("sample shipments", () => {
  it("provides eight shipments with unique, valid tracking numbers", () => {
    expect(SAMPLE_SHIPMENTS).toHaveLength(8);
    const ids = SAMPLE_SHIPMENTS.map((s) => s.id);
    expect(new Set(ids).size).toBe(8);
    for (const id of ids) expect(parseTrackingNumber(id)).toBe(id);
  });

  it("covers every parcel status once mapped", async () => {
    const parcels = await createParcelService(new FixtureCarrierClient()).listParcels();
    expect(new Set(parcels.map((p) => p.status))).toEqual(new Set(PARCEL_STATUSES));
  });

  it("lists history newest first with at least one entry", () => {
    for (const s of SAMPLE_SHIPMENTS) {
      expect(s.history.length).toBeGreaterThan(0);
      const times = s.history.map((h) => Date.parse(h.ts));
      expect(times).toEqual([...times].sort((a, b) => b - a));
    }
  });
});

describe("FixtureCarrierClient", () => {
  const client = new FixtureCarrierClient();

  it("finds a shipment by id", async () => {
    expect((await client.getShipment("PK1000000001"))?.id).toBe("PK1000000001");
  });

  it("returns null for an unknown id", async () => {
    expect(await client.getShipment("PK9999999999")).toBeNull();
  });

  it("lists every shipment", async () => {
    expect(await client.listShipments()).toHaveLength(8);
  });

  it("hands out copies so callers cannot alter the fixtures", async () => {
    const first = await client.getShipment("PK1000000001");
    first?.history.pop();
    expect((await client.getShipment("PK1000000001"))?.history.length).toBeGreaterThan(first?.history.length ?? 0);
  });
});
