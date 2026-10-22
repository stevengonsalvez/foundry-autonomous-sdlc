import { describe, expect, it } from "vitest";
import type { Parcel, ParcelService, ParcelSummary } from "@parcel/core";
import { FixtureCarrierClient, createParcelService } from "@parcel/core";
import * as serverModule from "../src/server";

function getServerFactory(): (service: ParcelService) => unknown {
  const mod: Record<string, unknown> = serverModule as unknown as Record<string, unknown>;
  const entries = Object.entries(mod).filter(
    (entry): entry is [string, (service: ParcelService) => unknown] => typeof entry[1] === "function",
  );
  const first = entries[0];
  if (entries.length === 1 && first !== undefined) {
    return first[1];
  }
  const candidates = [
    "createServer",
    "createApiServer",
    "createParcelServer",
    "createApp",
    "createApi",
    "createParcelApi",
    "createHttpServer",
    "buildServer",
    "buildApp",
    "startServer",
    "serve",
    "default",
  ];
  for (const name of candidates) {
    const candidate = mod[name];
    if (typeof candidate === "function") {
      return candidate as (service: ParcelService) => unknown;
    }
  }
  const matched = entries.find((entry) => /create|server|api|app|build/i.test(entry[0]));
  if (matched !== undefined) {
    return matched[1];
  }
  if (first !== undefined) {
    return first[1];
  }
  throw new Error("No server factory function found in server module");
}

function createServerInstance(service: ParcelService): unknown {
  const factory = getServerFactory();
  try {
    return factory(service);
  } catch {
    try {
      return (factory as unknown as (opts: { service: ParcelService }) => unknown)({ service });
    } catch {
      return new (factory as unknown as new (s: ParcelService) => unknown)(service);
    }
  }
}

let baseUrl = "";
let serverInstance: unknown;

async function startServer(): Promise<string> {
  if (baseUrl) {
    return baseUrl;
  }
  const service = createParcelService(new FixtureCarrierClient());
  serverInstance = createServerInstance(service);
  const server = serverInstance as {
    listen?: (port: number, cb?: () => void) => unknown;
    address?: () => unknown;
    unref?: () => void;
  };
  const listen = server?.listen;
  if (typeof listen === "function") {
    await new Promise<void>((resolve, reject) => {
      try {
        listen.call(server, 0, () => resolve());
      } catch (err) {
        reject(err);
      }
    });
    if (typeof server.unref === "function") {
      server.unref();
    }
    const addr = typeof server.address === "function" ? server.address() : undefined;
    const port =
      typeof addr === "object" && addr !== null && "port" in addr
        ? (addr as { port: number }).port
        : 0;
    baseUrl = `http://127.0.0.1:${port}`;
  }
  return baseUrl;
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  await startServer();
  if (baseUrl) {
    return fetch(`${baseUrl}${path}`, init);
  }
  const instance = serverInstance as {
    fetch?: (req: Request) => Promise<Response>;
  };
  if (typeof instance?.fetch === "function") {
    return instance.fetch(new Request(`http://localhost${path}`, init));
  }
  if (typeof serverInstance === "function") {
    return (serverInstance as (req: Request) => Promise<Response>)(
      new Request(`http://localhost${path}`, init),
    );
  }
  throw new Error("Unable to dispatch request to server instance");
}

describe("API trailing slash support", () => {
  it("GET /api/parcels/{tracking_number}/ returns 200 with the same parcel as GET /api/parcels/{tracking_number}", async () => {
    const withoutSlash = await request("/api/parcels/PK1000000001");
    expect(withoutSlash.status).toBe(200);
    const expectedParcel = (await withoutSlash.json()) as Parcel;

    const withSlash = await request("/api/parcels/PK1000000001/");
    expect(withSlash.status).toBe(200);
    const actualParcel = (await withSlash.json()) as Parcel;
    expect(actualParcel).toEqual(expectedParcel);
  });

  it("GET /api/parcels/ returns 200 with the same list as GET /api/parcels", async () => {
    const withoutSlash = await request("/api/parcels");
    expect(withoutSlash.status).toBe(200);
    const expectedList = (await withoutSlash.json()) as { parcels: ParcelSummary[] };

    const withSlash = await request("/api/parcels/");
    expect(withSlash.status).toBe(200);
    const actualList = (await withSlash.json()) as { parcels: ParcelSummary[] };
    expect(actualList).toEqual(expectedList);
  });

  it("Unknown paths such as /api/shipments and /api/shipments/ return 404 with {'error':'not_found'}", async () => {
    const res1 = await request("/api/shipments");
    expect(res1.status).toBe(404);
    expect(await res1.json()).toEqual({ error: "not_found" });

    const res2 = await request("/api/shipments/");
    expect(res2.status).toBe(404);
    expect(await res2.json()).toEqual({ error: "not_found" });
  });

  it("A tracking number that is invalid returns 400", async () => {
    const res = await request("/api/parcels/nope");
    expect(res.status).toBe(400);
  });

  it("Non-GET methods return 405 with an Allow: GET header", async () => {
    const res = await request("/api/parcels", { method: "POST" });
    expect(res.status).toBe(405);
    expect(res.headers.get("allow")).toBe("GET");
  });
});
