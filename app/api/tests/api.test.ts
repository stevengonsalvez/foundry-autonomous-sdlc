import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { startCarrierMock, type RunningServer as MockServer } from "@parcel/carrier-mock";
import {
  CarrierUnavailableError,
  FixtureCarrierClient,
  createParcelService,
  type CarrierClient,
} from "@parcel/core";
import { HttpCarrierClient, startApi, type RunningServer } from "../src";

async function call(server: RunningServer, path: string, init?: RequestInit) {
  const response = await fetch(`${server.url}${path}`, init);
  return { response, body: (await response.json()) as Record<string, unknown> };
}

describe("API over the in-memory carrier", () => {
  let api: RunningServer;

  beforeAll(async () => {
    api = await startApi({ port: 0, service: createParcelService(new FixtureCarrierClient()) });
  });
  afterAll(() => api.close());

  describe("GET /api/parcels/{trackingNumber}", () => {
    it("returns the parcel with events oldest first", async () => {
      const { response, body } = await call(api, "/api/parcels/PK1000000001");
      expect(response.status).toBe(200);
      expect(response.headers.get("content-type")).toMatch(/^application\/json/);
      expect(body).toMatchObject({ trackingNumber: "PK1000000001", status: "in_transit", estimatedDelivery: "2026-10-13" });
      const events = body["events"] as { timestamp: string; location: string; description: string }[];
      expect(events).toHaveLength(5);
      expect(events[0]).toEqual({
        timestamp: "2026-10-08T16:30:00Z",
        location: "Rotterdam, NL",
        description: "Shipping label created",
      });
      expect(events.map((e) => e.timestamp)).toEqual([...events.map((e) => e.timestamp)].sort());
    });

    it("returns a null estimate when the carrier has none", async () => {
      const { body } = await call(api, "/api/parcels/PK1000000005");
      expect(body["estimatedDelivery"]).toBeNull();
      expect(body["status"]).toBe("exception");
    });

    it.each(["PK123", "PK10000000011", "XX1000000001", "PK10000000AB", "%20PK1000000001"])(
      "answers 400 invalid_tracking_number for %s",
      async (input) => {
        const { response, body } = await call(api, `/api/parcels/${input}`);
        expect(response.status).toBe(400);
        expect(body).toEqual({ error: "invalid_tracking_number" });
      },
    );

    it("answers 400 for an undecodable path segment", async () => {
      const { response, body } = await call(api, "/api/parcels/%E0%A4%A");
      expect(response.status).toBe(400);
      expect(body).toEqual({ error: "invalid_tracking_number" });
    });

    it("answers 404 not_found for a well-formed number the carrier does not know", async () => {
      const { response, body } = await call(api, "/api/parcels/PK9999999999");
      expect(response.status).toBe(404);
      expect(body).toEqual({ error: "not_found" });
    });
  });

  describe("GET /api/parcels", () => {
    it("lists every parcel, newest update first", async () => {
      const { response, body } = await call(api, "/api/parcels");
      expect(response.status).toBe(200);
      const parcels = body["parcels"] as { trackingNumber: string; lastUpdate: string }[];
      expect(parcels).toHaveLength(8);
      expect(parcels[0]).toEqual({
        trackingNumber: "PK1000000004",
        status: "label_created",
        estimatedDelivery: "2026-10-15",
        lastUpdate: "2026-10-10T09:12:00Z",
      });
      const updates = parcels.map((p) => p.lastUpdate);
      expect(updates).toEqual([...updates].sort().reverse());
    });
  });

  describe("everything else", () => {
    it("answers 404 not_found for unknown paths", async () => {
      const { response, body } = await call(api, "/api/shipments");
      expect(response.status).toBe(404);
      expect(body).toEqual({ error: "not_found" });
    });

    it("answers 405 with an Allow header for non-GET methods", async () => {
      const response = await fetch(`${api.url}/api/parcels`, { method: "DELETE" });
      expect(response.status).toBe(405);
      expect(response.headers.get("allow")).toBe("GET");
      expect(await response.json()).toEqual({ error: "method_not_allowed" });
    });
  });
});

describe("API when the carrier fails", () => {
  it("answers 502 carrier_unavailable on both routes", async () => {
    const carrier: CarrierClient = {
      getShipment: vi.fn().mockRejectedValue(new CarrierUnavailableError("down")),
      listShipments: vi.fn().mockRejectedValue(new Error("unexpected")),
    };
    const api = await startApi({ port: 0, service: createParcelService(carrier) });
    try {
      for (const path of ["/api/parcels/PK1000000001", "/api/parcels"]) {
        const { response, body } = await call(api, path);
        expect(response.status).toBe(502);
        expect(body).toEqual({ error: "carrier_unavailable" });
      }
    } finally {
      await api.close();
    }
  });

  it("answers 500 internal_error for a bug in the service itself", async () => {
    const api = await startApi({
      port: 0,
      service: { getParcel: vi.fn().mockRejectedValue(new TypeError("bug")), listParcels: vi.fn() },
    });
    try {
      const { response, body } = await call(api, "/api/parcels/PK1000000001");
      expect(response.status).toBe(500);
      expect(body).toEqual({ error: "internal_error" });
    } finally {
      await api.close();
    }
  });
});

describe("API through HTTP to the carrier mock", () => {
  let mock: MockServer;
  let api: RunningServer;

  beforeAll(async () => {
    mock = await startCarrierMock({ port: 0 });
    api = await startApi({ port: 0, service: createParcelService(new HttpCarrierClient({ baseUrl: mock.url })) });
  });
  afterAll(async () => {
    await api.close();
    await mock.close();
  });

  it("serves a parcel end to end", async () => {
    const { response, body } = await call(api, "/api/parcels/PK1000000003");
    expect(response.status).toBe(200);
    expect(body).toMatchObject({ trackingNumber: "PK1000000003", status: "delivered", estimatedDelivery: "2026-10-08" });
  });

  it("serves the list end to end", async () => {
    const { body } = await call(api, "/api/parcels");
    expect(body["parcels"]).toHaveLength(8);
  });

  it("answers 404 for a parcel the carrier does not know", async () => {
    const { response } = await call(api, "/api/parcels/PK9999999999");
    expect(response.status).toBe(404);
  });

  it("answers 502 once the carrier is gone", async () => {
    const orphan = await startApi({
      port: 0,
      service: createParcelService(new HttpCarrierClient({ baseUrl: "http://127.0.0.1:9", timeoutMs: 500 })),
    });
    try {
      const { response, body } = await call(orphan, "/api/parcels/PK1000000001");
      expect(response.status).toBe(502);
      expect(body).toEqual({ error: "carrier_unavailable" });
    } finally {
      await orphan.close();
    }
  });
});
