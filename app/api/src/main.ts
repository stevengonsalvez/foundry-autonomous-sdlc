import { createParcelService } from "@parcel/core";
import { HttpCarrierClient } from "./http-carrier-client";
import { startApi } from "./server";

const port = Number(process.env["PORT"] ?? 4000);
const carrierUrl = process.env["CARRIER_URL"] ?? "http://127.0.0.1:4010";

const service = createParcelService(new HttpCarrierClient({ baseUrl: carrierUrl }));
const { url, close } = await startApi({ port, service });
console.log(`api listening on ${url}, carrier at ${carrierUrl}`);

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.once(signal, () => void close().then(() => process.exit(0)));
}
