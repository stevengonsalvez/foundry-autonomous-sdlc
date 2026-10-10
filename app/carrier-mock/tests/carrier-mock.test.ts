import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { loadCarrierContract } from "@parcel/contracts";
import { SAMPLE_SHIPMENTS } from "@parcel/core";
import { startCarrierMock, type RunningServer } from "../src";

const contract = loadCarrierContract();
let mock: RunningServer;

beforeAll(async () => {
  mock = await startCarrierMock({ port: 0 });
});

afterAll(async () => {
  await mock.close();
});

async function get(path: string) {
  const response = await fetch(`${mock.url}${path}`);
  return { response, body: (await response.json()) as unknown };
}

function expectConforms(path: string, status: number, body: unknown) {
  const pathname = new URL(path, "http://x").pathname;
  expect(contract.validateResponse("GET", pathname, status, body)).toEqual({ valid: true, errors: [] });
}

describe("GET /v1/shipments", () => {
  it("lists every sample shipment in the contract shape", async () => {
    const { response, body } = await get("/v1/shipments");
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toMatch(/^application\/json/);
    expect(body).toEqual({ items: SAMPLE_SHIPMENTS });
    expectConforms("/v1/shipments", 200, body);
  });
});

describe("GET /v1/shipments/{id}", () => {
  it.each(SAMPLE_SHIPMENTS.map((s) => s.id))("serves %s in the contract shape", async (id) => {
    const { response, body } = await get(`/v1/shipments/${id}`);
    expect(response.status).toBe(200);
    expect(body).toEqual(SAMPLE_SHIPMENTS.find((s) => s.id === id));
    expectConforms(`/v1/shipments/${id}`, 200, body);
  });

  it("answers 404 UNKNOWN_SHIPMENT for an id it does not hold", async () => {
    const { response, body } = await get("/v1/shipments/PK9999999999");
    expect(response.status).toBe(404);
    expect(body).toEqual({ code: "UNKNOWN_SHIPMENT" });
    expectConforms("/v1/shipments/PK9999999999", 404, body);
  });

  it("treats an undecodable id as unknown", async () => {
    const { response, body } = await get("/v1/shipments/%E0%A4%A");
    expect(response.status).toBe(404);
    expect(body).toEqual({ code: "UNKNOWN_SHIPMENT" });
  });

  it("ignores the query string", async () => {
    const { response } = await get("/v1/shipments/PK1000000001?verbose=1");
    expect(response.status).toBe(200);
  });
});

describe("outside the contract", () => {
  it("answers 404 NOT_FOUND with a JSON body for other paths", async () => {
    const { response, body } = await get("/v2/shipments");
    expect(response.status).toBe(404);
    expect(body).toEqual({ code: "NOT_FOUND" });
  });

  it("answers 405 with an Allow header for non-GET methods", async () => {
    const response = await fetch(`${mock.url}/v1/shipments`, { method: "POST", body: "{}" });
    expect(response.status).toBe(405);
    expect(response.headers.get("allow")).toBe("GET");
    expect(await response.json()).toEqual({ code: "METHOD_NOT_ALLOWED" });
  });
});

describe("startCarrierMock", () => {
  it("serves the shipments it is given", async () => {
    const custom = await startCarrierMock({ port: 0, shipments: SAMPLE_SHIPMENTS.slice(0, 2) });
    try {
      const body = (await (await fetch(`${custom.url}/v1/shipments`)).json()) as { items: unknown[] };
      expect(body.items).toHaveLength(2);
    } finally {
      await custom.close();
    }
  });
});
