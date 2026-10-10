import type http from "node:http";
import { createServer as createHttpServer } from "node:http";
import { parse as parseUrl } from "node:url";
import { pathToRegexp, match } from "path-to-regexp";
import { ParcelService, CarrierUnavailableError } from "@parcel/core";

export type ApiOptions = { port: number; service: ParcelService };
export type RunningServer = { url: string; close: () => Promise<void> };

function json(res: http.ServerResponse, status: number, body: unknown) {
  const s = JSON.stringify(body);
  res.writeHead(status, { "content-type": "application/json" });
  res.end(s);
}

const getParcelsList = pathToRegexp("/api/parcels");
const getParcel = pathToRegexp("/api/parcels/:id");

function normalizeTracking(id: string) {
  // Normalise to uppercase for case-insensitive matching, but preserve validation
  return id.toUpperCase();
}

export function createApi(service: ParcelService) {
  return createHttpServer(async (req, res) => {
    try {
      const url = parseUrl(req.url ?? "", true);
      const method = (req.method ?? "GET").toUpperCase();

      // Only GET allowed on these endpoints
      if (getParcelsList.test(url.pathname || "")) {
        if (method !== "GET") return json(res, 405, { error: "method_not_allowed" });
        try {
          const list = await service.listParcels();
          return json(res, 200, { parcels: list });
        } catch (err) {
          if (err instanceof CarrierUnavailableError) return json(res, 502, { error: "carrier_unavailable" });
          throw err;
        }
      }

      const m = match("/api/parcels/:id", { decode: decodeURIComponent });
      const matched = m(url.pathname || "");
      if (matched) {
        if (method !== "GET") {
          res.setHeader("Allow", "GET");
          return json(res, 405, { error: "method_not_allowed" });
        }
        let id = String(matched.params.id);
        // If the path segment was undecodable, reject
        try {
          // decodeURIComponent ran during matching; ensure decoding succeeded
          // Normalise case-insensitively
          id = normalizeTracking(id);
        } catch {
          return json(res, 400, { error: "invalid_tracking_number" });
        }

        try {
          const parcel = await service.getParcel(id);
          if (!parcel) return json(res, 404, { error: "not_found" });
          return json(res, 200, parcel);
        } catch (err) {
          if (err instanceof CarrierUnavailableError) return json(res, 502, { error: "carrier_unavailable" });
          throw err;
        }
      }

      return json(res, 404, { error: "not_found" });
    } catch (err) {
      // unexpected
      console.error(err);
      json(res as unknown as http.ServerResponse, 500, { error: "internal_error" });
    }
  });
}

export async function startApi(opts: ApiOptions) {
  const server = createApi(opts.service);
  await new Promise<void>((resolve) => server.listen(opts.port, resolve));
  const address = server.address();
  const port = typeof address === "string" ? 0 : (address && address.port) || 0;
  const url = `http://127.0.0.1:${port}`;
  return {
    url,
    close: async () => {
      await new Promise<void>((resolve) => server.close(() => resolve()));
    },
  } as RunningServer;
}
