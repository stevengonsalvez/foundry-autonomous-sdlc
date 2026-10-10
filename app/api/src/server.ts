import type { AddressInfo } from "node:net";
import type { Server } from "node:http";
import { createServer } from "node:http";
import { createParcelService, type ParcelService } from "@parcel/core";
import { HttpCarrierClient } from "./http-carrier-client";
import { parse as parseUrl } from "node:url";
import { validateTrackingNumber } from "@parcel/core";

export type ApiOptions = { port: number; service?: ParcelService };

export type RunningServer = { url: string; close: () => Promise<void> };

function sendJson(res: ServerResponse, status: number, body: unknown) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
}

import type { IncomingMessage, ServerResponse } from "node:http";

export async function startApi(opts: ApiOptions): Promise<RunningServer> {
  const service = opts.service ?? createParcelService(new HttpCarrierClient({ baseUrl: `http://127.0.0.1:3001` }));

  const server: Server = createServer(async (req: IncomingMessage, res: ServerResponse) => {
    try {
      const url = req.url ?? "";
      const parsed = parseUrl(url);
      const method = (req.method ?? "GET").toUpperCase();

      // only support GET
      if (method !== "GET") return sendJson(res, 405, { error: "method_not_allowed" });

      if (parsed.pathname === "/api/parcels") {
        const list = await service.listParcels();
        return sendJson(res, 200, { parcels: list });
      }

      const m = parsed.pathname?.match(/^\/api\/parcels\/(.+)$/);
      if (m) {
        // normalise tracking number to uppercase before validation/lookups
        let rawId = m[1] ?? "";
        try {
          // the path segment may be percent-encoded; decode
          rawId = decodeURIComponent(rawId);
        } catch (e) {
          return sendJson(res, 400, { error: "invalid_tracking_number" });
        }
        const id = rawId.toUpperCase();

        if (!validateTrackingNumber(id)) return sendJson(res, 400, { error: "invalid_tracking_number" });

        const parcel = await service.getParcel(id);
        if (!parcel) return sendJson(res, 404, { error: "not_found" });
        return sendJson(res, 200, parcel);
      }

      return sendJson(res, 404, { error: "not_found" });
    } catch (err: unknown) {
      // Carrier unavailable
      // tests expect CarrierUnavailableError to be translated elsewhere; keep simple
      console.error(err);
      return sendJson(res, 500, { error: "internal_error" });
    }
  });

  await new Promise<void>((resolve) => server.listen(opts.port, "127.0.0.1", resolve));
  const address = server.address() as AddressInfo;
  const url = `http://${address.address === "::" ? "127.0.0.1" : address.address}:${address.port}`;
  return { url, close: async () => await new Promise<void>((resolve, reject) => server.close((err) => (err ? reject(err) : resolve()))) };
}
