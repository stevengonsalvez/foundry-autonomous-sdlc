import type { AddressInfo } from "node:net";
import { createServer } from "node:http";
import { match as pathMatch } from "path-to-regexp";
import type { ParcelService } from "@parcel/core";
import { json, notFound, methodNotAllowed, internalError } from "./responses";

export type ApiOptions = { port: number; service: ParcelService };

export type RunningServer = { url: string; close: () => Promise<void> };

function normalizeTrackingNumber(raw: string) {
  return raw.toUpperCase();
}

function validateTrackingNumber(tn: string) {
  // Accept exact format: PK followed by 10 digits
  return /^PK\d{10}$/.test(tn);
}

export function createApi(service: ParcelService) {
  const shipmentsMatch = pathMatch("/api/parcels/:id");

  return async (req: Request) => {
    try {
      if (req.method !== "GET") return methodNotAllowed(["GET"]);
      const url = new URL(req.url);
      if (url.pathname === "/api/parcels") {
        const list = await service.listParcels();
        return json(200, { parcels: list });
      }
      const m = shipmentsMatch(url.pathname);
      if (!m || !m.params?.id) return notFound();
      let idRaw = String(m.params.id);
      // Normalise to uppercase for case-insensitive handling
      const id = normalizeTrackingNumber(idRaw);
      // Validate after normalisation
      if (!validateTrackingNumber(id)) return json(400, { error: "invalid_tracking_number" });
      const parcel = await service.getParcel(id);
      if (!parcel) return json(404, { error: "not_found" });
      return json(200, parcel);
    } catch (err: unknown) {
      return internalError();
    }
  };
}

export async function startApi(opts: ApiOptions): Promise<RunningServer> {
  const handler = createApi(opts.service);
  const server = createServer(async (req, res) => {
    try {
      const result = await handler(req as unknown as Request);
      res.writeHead(result.status, result.headers);
      res.end(result.body);
    } catch (e) {
      res.writeHead(500, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "internal_error" }));
    }
  });
  await new Promise<void>((resolve) => server.listen(opts.port, "127.0.0.1", resolve));
  const addr = server.address() as AddressInfo;
  const url = `http://127.0.0.1:${addr.port}`;
  return { url, close: async () => await new Promise((r) => server.close(r)) };
}
