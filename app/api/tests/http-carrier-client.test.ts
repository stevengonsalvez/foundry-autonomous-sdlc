import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { loadCarrierContract } from "@parcel/contracts";
import { startCarrierMock, type RunningServer } from "@parcel/carrier-mock";
import { CarrierUnavailableError, SAMPLE_SHIPMENTS } from "@parcel/core";
import { HttpCarrierClient } from "../src";

const contract = loadCarrierContract();
let mock: RunningServer;

beforeAll(async () => {
  mock = await startCarrierMock({ port: 0 });
});

afterAll(async () => {
  await mock.close();
});

/** A fetch that fails the test if the client calls anything the contract does not document or the carrier answers off-contract. */
function contractCheckedFetch() {
  const exchanges: string[] = [];
  const checked: typeof fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input));
    const method = init?.method ?? "GET";
    const operation = contract.findOperation(method, url.pathname);
    expect(operation, `${method} ${url.pathname} must be a contract operation`).toBeDefined();

    const response = await fetch(input, init);
    const result = contract.validateResponse(method, url.pathname, response.status, await response.clone().json());
    expect(result, `${operation?.operationId} response must conform`).toEqual({ valid: true, errors: [] });
    exchanges.push(`${operation?.operationId} ${response.status}`);
    return response;
  };
  return { checked, exchanges };
}

describe("HttpCarrierClient against the carrier mock", () => {
  it("fetches a shipment exactly as the contract describes it", async () => {
    const { checked, exchanges } = contractCheckedFetch();
    const client = new HttpCarrierClient({ baseUrl: mock.url, fetch: checked });
    expect(await client.getShipment("PK1000000002")).toEqual(SAMPLE_SHIPMENTS[1]);
    expect(exchanges).toEqual(["getShipment 200"]);
  });

  it("resolves null for an unknown shipment", async () => {
    const { checked, exchanges } = contractCheckedFetch();
    const client = new HttpCarrierClient({ baseUrl: mock.url, fetch: checked });
    expect(await client.getShipment("PK9999999999")).toBeNull();
    expect(exchanges).toEqual(["getShipment 404"]);
  });

  it("percent-encodes ids so they stay a single path segment", async () => {
    const { checked, exchanges } = contractCheckedFetch();
    const client = new HttpCarrierClient({ baseUrl: mock.url, fetch: checked });
    expect(await client.getShipment("a/b")).toBeNull();
    expect(exchanges).toEqual(["getShipment 404"]);
  });

  it("lists every shipment", async () => {
    const { checked, exchanges } = contractCheckedFetch();
    const client = new HttpCarrierClient({ baseUrl: `${mock.url}/`, fetch: checked });
    expect(await client.listShipments()).toEqual(SAMPLE_SHIPMENTS);
    expect(exchanges).toEqual(["listShipments 200"]);
  });
});

describe("HttpCarrierClient when the carrier misbehaves", () => {
  let stub: Server;
  let stubUrl: string;
  let reply: (url: string) => { status: number; body: string } | "hang";

  beforeAll(async () => {
    stub = createServer((req, res) => {
      const next = reply(req.url ?? "");
      if (next === "hang") return;
      res.writeHead(next.status, { "content-type": "application/json" });
      res.end(next.body);
    });
    await new Promise<void>((resolve) => stub.listen(0, "127.0.0.1", resolve));
    stubUrl = `http://127.0.0.1:${(stub.address() as AddressInfo).port}`;
  });

  afterAll(async () => {
    stub.closeAllConnections();
    await new Promise((resolve) => stub.close(resolve));
  });

  const client = () => new HttpCarrierClient({ baseUrl: stubUrl, timeoutMs: 100 });
  const good = JSON.stringify(SAMPLE_SHIPMENTS[0]);

  it("reports a 5xx as unavailable", async () => {
    reply = () => ({ status: 503, body: "{}" });
    await expect(client().getShipment("PK1000000001")).rejects.toBeInstanceOf(CarrierUnavailableError);
    await expect(client().listShipments()).rejects.toBeInstanceOf(CarrierUnavailableError);
  });

  it("reports a 404 that is not an unknown shipment as unavailable", async () => {
    reply = () => ({ status: 404, body: JSON.stringify({ code: "NOT_FOUND" }) });
    await expect(client().getShipment("PK1000000001")).rejects.toBeInstanceOf(CarrierUnavailableError);
  });

  it("reports a body that is not JSON as unavailable", async () => {
    reply = () => ({ status: 200, body: "<html>oops</html>" });
    await expect(client().getShipment("PK1000000001")).rejects.toBeInstanceOf(CarrierUnavailableError);
  });

  it.each([
    ["an unknown state", { ...SAMPLE_SHIPMENTS[0], state: "LOST" }],
    ["no history", { ...SAMPLE_SHIPMENTS[0], history: [] }],
    ["a malformed history entry", { ...SAMPLE_SHIPMENTS[0], history: [{ ts: 5 }] }],
    ["a malformed eta", { ...SAMPLE_SHIPMENTS[0], eta: "soon" }],
    ["a non-object payload", "PK1000000001"],
  ])("reports %s as unavailable", async (_name, shipment) => {
    reply = () => ({ status: 200, body: JSON.stringify(shipment) });
    await expect(client().getShipment("PK1000000001")).rejects.toBeInstanceOf(CarrierUnavailableError);
  });

  it("reports a malformed list as unavailable", async () => {
    reply = () => ({ status: 200, body: JSON.stringify({ items: [{ id: 1 }] }) });
    await expect(client().listShipments()).rejects.toBeInstanceOf(CarrierUnavailableError);
    reply = () => ({ status: 200, body: JSON.stringify({ items: "none" }) });
    await expect(client().listShipments()).rejects.toBeInstanceOf(CarrierUnavailableError);
  });

  it("accepts a well-formed shipment", async () => {
    reply = () => ({ status: 200, body: good });
    expect((await client().getShipment("PK1000000001"))?.id).toBe("PK1000000001");
  });

  it("gives up when the carrier does not answer in time", async () => {
    reply = () => "hang";
    await expect(client().getShipment("PK1000000001")).rejects.toBeInstanceOf(CarrierUnavailableError);
  });

  it("reports a refused connection as unavailable", async () => {
    const closed = await startCarrierMock({ port: 0 });
    const url = closed.url;
    await closed.close();
    await expect(new HttpCarrierClient({ baseUrl: url }).getShipment("PK1000000001")).rejects.toBeInstanceOf(
      CarrierUnavailableError,
    );
  });
});
