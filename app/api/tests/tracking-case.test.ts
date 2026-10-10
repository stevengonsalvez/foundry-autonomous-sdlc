import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { FixtureCarrierClient, createParcelService } from "@parcel/core";
import { startApi, type RunningServer } from "../src";

async function call(server: RunningServer, path: string) {
  const response = await fetch(`${server.url}${path}`);
  return { response, body: await response.json() };
}

describe("tracking number case insensitivity", () => {
  let api: RunningServer;

  beforeAll(async () => {
    api = await startApi({ port: 0, service: createParcelService(new FixtureCarrierClient()) });
  });
  afterAll(async () => api.close());

  it("accepts a lowercase tracking number and returns the same parcel as the uppercase form", async () => {
    const lower = await call(api, "/api/parcels/pk1000000001");
    const upper = await call(api, "/api/parcels/PK1000000001");

    // both requests should succeed
    expect(lower.response.status).toBe(200);
    expect(upper.response.status).toBe(200);

    // and return equivalent bodies (at least same trackingNumber and status)
    expect(lower.body).toMatchObject({ trackingNumber: "PK1000000001", status: upper.body.status });
    expect(upper.body).toMatchObject({ trackingNumber: "PK1000000001" });
  });

  it("still rejects genuinely malformed lowercase tracking numbers with 400 invalid_tracking_number", async () => {
    const { response, body } = await call(api, "/api/parcels/pk123");
    expect(response.status).toBe(400);
    expect(body).toEqual({ error: "invalid_tracking_number" });
  });
});