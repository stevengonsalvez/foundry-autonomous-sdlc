import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import { SAMPLE_SHIPMENTS, type CarrierShipment } from "@parcel/core";

export interface RunningServer {
  url: string;
  close(): Promise<void>;
}

export interface CarrierMockOptions {
  port: number;
  shipments?: readonly CarrierShipment[];
}

const SHIPMENT_PATH = /^\/v1\/shipments\/([^/]+)$/;

function sendJson(res: ServerResponse, status: number, body: unknown, headers: Record<string, string> = {}): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(payload),
    ...headers,
  });
  res.end(payload);
}

function safeDecode(segment: string): string | null {
  try {
    return decodeURIComponent(segment);
  } catch {
    return null;
  }
}

export function createCarrierMock(shipments: readonly CarrierShipment[] = SAMPLE_SHIPMENTS): Server {
  return createServer((req: IncomingMessage, res: ServerResponse) => {
    const { pathname } = new URL(req.url ?? "/", "http://carrier.local");
    const single = SHIPMENT_PATH.exec(pathname);
    const known = pathname === "/v1/shipments" || single !== null;

    if (!known) return sendJson(res, 404, { code: "NOT_FOUND" });
    if (req.method !== "GET") return sendJson(res, 405, { code: "METHOD_NOT_ALLOWED" }, { allow: "GET" });

    if (!single) return sendJson(res, 200, { items: shipments });

    const id = safeDecode(single[1] ?? "");
    const shipment = id === null ? undefined : shipments.find((s) => s.id === id);
    if (!shipment) return sendJson(res, 404, { code: "UNKNOWN_SHIPMENT" });
    return sendJson(res, 200, shipment);
  });
}

export async function startCarrierMock({ port, shipments }: CarrierMockOptions): Promise<RunningServer> {
  const server = createCarrierMock(shipments);
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", resolve);
  });
  const { port: actual } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${actual}`,
    close: () =>
      new Promise((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
        server.closeAllConnections();
      }),
  };
}
