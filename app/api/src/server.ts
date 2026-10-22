import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";
import {
  CarrierUnavailableError,
  InvalidTrackingNumberError,
  ParcelNotFoundError,
  type ParcelService,
} from "@parcel/core";

export interface RunningServer {
  url: string;
  close(): Promise<void>;
}

export interface ApiOptions {
  port: number;
  service: ParcelService;
}

const PARCEL_PATH = /^\/api\/parcels\/([^/]+)\/?$/;

function sendJson(res: ServerResponse, status: number, body: unknown, headers: Record<string, string> = {}): void {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(payload),
    "cache-control": "no-store",
    ...headers,
  });
  res.end(payload);
}

function sendError(res: ServerResponse, error: unknown): void {
  if (error instanceof InvalidTrackingNumberError) return sendJson(res, 400, { error: "invalid_tracking_number" });
  if (error instanceof ParcelNotFoundError) return sendJson(res, 404, { error: "not_found" });
  if (error instanceof CarrierUnavailableError) return sendJson(res, 502, { error: "carrier_unavailable" });
  console.error(error);
  return sendJson(res, 500, { error: "internal_error" });
}

function safeDecode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}

export function createApi(service: ParcelService): Server {
  return createServer((req: IncomingMessage, res: ServerResponse) => {
    const { pathname } = new URL(req.url ?? "/", "http://api.local");
    const single = PARCEL_PATH.exec(pathname);
    const known = pathname === "/api/parcels" || pathname === "/api/parcels/" || single !== null;

    if (!known) return sendJson(res, 404, { error: "not_found" });
    if (req.method !== "GET") return sendJson(res, 405, { error: "method_not_allowed" }, { allow: "GET" });

    const work = single
      ? service.getParcel(safeDecode(single[1] ?? "")).then((parcel) => sendJson(res, 200, parcel))
      : service.listParcels().then((parcels) => sendJson(res, 200, { parcels }));
    work.catch((error: unknown) => sendError(res, error));
  });
}

export async function startApi({ port, service }: ApiOptions): Promise<RunningServer> {
  const server = createApi(service);
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
