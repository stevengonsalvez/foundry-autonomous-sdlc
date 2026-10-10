import { startCarrierMock } from "./server";

const port = Number(process.env["PORT"] ?? 4010);
const { url, close } = await startCarrierMock({ port });
console.log(`carrier-mock listening on ${url}`);

for (const signal of ["SIGINT", "SIGTERM"] as const) {
  process.once(signal, () => void close().then(() => process.exit(0)));
}
