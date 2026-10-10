import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { startApi, type RunningServer } from "../src";
import { createParcelService, FixtureCarrierClient } from "@parcel/core";

async function call(server: RunningServer, path: string) {
  const response = await fetch(`${server.url}${path}`);
  return { response, body: (await response.json()) as Record<string, unknown> };
}

describe("API lowercase tracking numbers", () => {
  let api: RunningServer;

  beforeAll(async () => {
    api = await startApi({ port: 0, service: createParcelService(new FixtureCarrierClient()) });
  });
  afterAll(async () => api.close());

  it("accepts a lowercase tracking number in the path and returns the parcel", async () => {
    const { response, body } = await call(api, "/api/parcels/pk1000000001");
    expect(response.status).toBe(200);
    expect(body["trackingNumber"]).toBe("PK1000000001");
  });
});
