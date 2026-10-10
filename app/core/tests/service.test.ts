import { describe, expect, it, vi } from "vitest";
import {
  CarrierUnavailableError,
  InvalidTrackingNumberError,
  ParcelNotFoundError,
  createParcelService,
  type CarrierClient,
  type CarrierShipment,
} from "../src";

function shipment(id: string, ts: string): CarrierShipment {
  return { id, state: "TRANSIT", eta: null, history: [{ ts, place: "Leeds, GB", note: "Scanned" }] };
}

function fakeCarrier(items: CarrierShipment[]): CarrierClient {
  return {
    getShipment: vi.fn(async (id: string) => items.find((s) => s.id === id) ?? null),
    listShipments: vi.fn(async () => items),
  };
}

describe("ParcelService.getParcel", () => {
  it("returns the mapped parcel for a known tracking number", async () => {
    const service = createParcelService(fakeCarrier([shipment("PK1000000001", "2026-10-01T10:00:00Z")]));
    const parcel = await service.getParcel("PK1000000001");
    expect(parcel.trackingNumber).toBe("PK1000000001");
    expect(parcel.status).toBe("in_transit");
    expect(parcel.events).toHaveLength(1);
  });

  it("rejects a malformed number without calling the carrier", async () => {
    const carrier = fakeCarrier([]);
    await expect(createParcelService(carrier).getParcel("nope")).rejects.toBeInstanceOf(InvalidTrackingNumberError);
    expect(carrier.getShipment).not.toHaveBeenCalled();
  });

  it("reports a well-formed but unknown number as not found", async () => {
    const service = createParcelService(fakeCarrier([]));
    await expect(service.getParcel("PK9999999999")).rejects.toBeInstanceOf(ParcelNotFoundError);
  });

  it("passes carrier outages through", async () => {
    const carrier = fakeCarrier([]);
    vi.mocked(carrier.getShipment).mockRejectedValue(new CarrierUnavailableError("down"));
    await expect(createParcelService(carrier).getParcel("PK1000000001")).rejects.toBeInstanceOf(CarrierUnavailableError);
  });

  it("wraps unexpected carrier failures as an outage and keeps the cause", async () => {
    const carrier = fakeCarrier([]);
    const cause = new TypeError("boom");
    vi.mocked(carrier.getShipment).mockRejectedValue(cause);
    const error = await createParcelService(carrier)
      .getParcel("PK1000000001")
      .catch((e: unknown) => e);
    expect(error).toBeInstanceOf(CarrierUnavailableError);
    expect((error as CarrierUnavailableError).cause).toBe(cause);
  });
});

describe("ParcelService.listParcels", () => {
  it("sorts by last update, newest first, with the tracking number as tie-break", async () => {
    const service = createParcelService(
      fakeCarrier([
        shipment("PK1000000003", "2026-10-02T10:00:00Z"),
        shipment("PK1000000002", "2026-10-05T10:00:00Z"),
        shipment("PK1000000001", "2026-10-05T10:00:00Z"),
      ]),
    );
    const parcels = await service.listParcels();
    expect(parcels.map((p) => p.trackingNumber)).toEqual(["PK1000000001", "PK1000000002", "PK1000000003"]);
    expect(parcels[0]).toEqual({
      trackingNumber: "PK1000000001",
      status: "in_transit",
      estimatedDelivery: null,
      lastUpdate: "2026-10-05T10:00:00Z",
    });
  });

  it("wraps unexpected carrier failures as an outage", async () => {
    const carrier = fakeCarrier([]);
    vi.mocked(carrier.listShipments).mockRejectedValue(new Error("boom"));
    await expect(createParcelService(carrier).listParcels()).rejects.toBeInstanceOf(CarrierUnavailableError);
  });
});
