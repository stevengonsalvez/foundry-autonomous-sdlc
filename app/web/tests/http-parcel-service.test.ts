import { describe, expect, it, vi } from "vitest";
import {
  CarrierUnavailableError,
  InvalidTrackingNumberError,
  ParcelNotFoundError,
  createParcelService,
  FixtureCarrierClient,
} from "@parcel/core";
import { HttpParcelService } from "../src/http-parcel-service";

function stubFetch(status: number, body: unknown): typeof fetch {
  return vi.fn(async () => new Response(typeof body === "string" ? body : JSON.stringify(body), { status }));
}

describe("HttpParcelService.getParcel", () => {
  it("fetches /api/parcels/{trackingNumber} and returns the parcel", async () => {
    const parcel = await createParcelService(new FixtureCarrierClient()).getParcel("PK1000000001");
    const fetchImpl = stubFetch(200, parcel);
    const service = new HttpParcelService("", fetchImpl);
    expect(await service.getParcel("PK1000000001")).toEqual(parcel);
    expect(fetchImpl).toHaveBeenCalledWith("/api/parcels/PK1000000001", expect.anything());
  });

  it("encodes the tracking number into one path segment", async () => {
    const fetchImpl = stubFetch(404, { error: "not_found" });
    await new HttpParcelService("", fetchImpl).getParcel("a/b").catch(() => undefined);
    expect(fetchImpl).toHaveBeenCalledWith("/api/parcels/a%2Fb", expect.anything());
  });

  it("maps 400 to InvalidTrackingNumberError", async () => {
    const service = new HttpParcelService("", stubFetch(400, { error: "invalid_tracking_number" }));
    await expect(service.getParcel("nope")).rejects.toBeInstanceOf(InvalidTrackingNumberError);
  });

  it("maps 404 to ParcelNotFoundError", async () => {
    const service = new HttpParcelService("", stubFetch(404, { error: "not_found" }));
    await expect(service.getParcel("PK9999999999")).rejects.toBeInstanceOf(ParcelNotFoundError);
  });

  it.each([500, 502, 503])("maps %i to CarrierUnavailableError", async (status) => {
    const service = new HttpParcelService("", stubFetch(status, { error: "carrier_unavailable" }));
    await expect(service.getParcel("PK1000000001")).rejects.toBeInstanceOf(CarrierUnavailableError);
  });

  it("maps a network failure to CarrierUnavailableError", async () => {
    const service = new HttpParcelService("", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(service.getParcel("PK1000000001")).rejects.toBeInstanceOf(CarrierUnavailableError);
  });

  it("maps a body that is not JSON to CarrierUnavailableError", async () => {
    const service = new HttpParcelService("", stubFetch(200, "<html></html>"));
    await expect(service.getParcel("PK1000000001")).rejects.toBeInstanceOf(CarrierUnavailableError);
  });
});

describe("HttpParcelService.listParcels", () => {
  it("returns the parcels array", async () => {
    const parcels = await createParcelService(new FixtureCarrierClient()).listParcels();
    const fetchImpl = stubFetch(200, { parcels });
    expect(await new HttpParcelService("", fetchImpl).listParcels()).toEqual(parcels);
    expect(fetchImpl).toHaveBeenCalledWith("/api/parcels", expect.anything());
  });

  it("prefixes a base URL when one is given", async () => {
    const fetchImpl = stubFetch(200, { parcels: [] });
    await new HttpParcelService("http://127.0.0.1:4000", fetchImpl).listParcels();
    expect(fetchImpl).toHaveBeenCalledWith("http://127.0.0.1:4000/api/parcels", expect.anything());
  });

  it("maps a failure to CarrierUnavailableError", async () => {
    const service = new HttpParcelService("", stubFetch(502, { error: "carrier_unavailable" }));
    await expect(service.listParcels()).rejects.toBeInstanceOf(CarrierUnavailableError);
  });

  it("maps a body without parcels to CarrierUnavailableError", async () => {
    const service = new HttpParcelService("", stubFetch(200, { nope: true }));
    await expect(service.listParcels()).rejects.toBeInstanceOf(CarrierUnavailableError);
  });
});
