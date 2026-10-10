import {
  CARRIER_STATES,
  CarrierUnavailableError,
  type CarrierClient,
  type CarrierShipment,
} from "@parcel/core";

export interface HttpCarrierClientOptions {
  baseUrl: string;
  /** Per request, default 5000. */
  timeoutMs?: number;
  fetch?: typeof fetch;
}

const DATE = /^\d{4}-\d{2}-\d{2}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCarrierShipment(value: unknown): value is CarrierShipment {
  if (!isRecord(value)) return false;
  const { id, state, history, eta } = value;
  return (
    typeof id === "string" &&
    CARRIER_STATES.includes(state as CarrierShipment["state"]) &&
    (eta === null || (typeof eta === "string" && DATE.test(eta))) &&
    Array.isArray(history) &&
    history.length > 0 &&
    history.every(
      (entry) =>
        isRecord(entry) &&
        typeof entry["ts"] === "string" &&
        typeof entry["place"] === "string" &&
        typeof entry["note"] === "string",
    )
  );
}

export class HttpCarrierClient implements CarrierClient {
  private readonly baseUrl: string;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor({ baseUrl, timeoutMs = 5000, fetch: fetchImpl = fetch }: HttpCarrierClientOptions) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.timeoutMs = timeoutMs;
    this.fetchImpl = fetchImpl;
  }

  async getShipment(id: string): Promise<CarrierShipment | null> {
    const { status, body } = await this.get(`/v1/shipments/${encodeURIComponent(id)}`);
    if (status === 404 && isRecord(body) && body["code"] === "UNKNOWN_SHIPMENT") return null;
    if (status !== 200 || !isCarrierShipment(body)) throw this.unexpected(`GET shipment`, status);
    return body;
  }

  async listShipments(): Promise<CarrierShipment[]> {
    const { status, body } = await this.get("/v1/shipments");
    const items = isRecord(body) ? body["items"] : undefined;
    if (status !== 200 || !Array.isArray(items) || !items.every(isCarrierShipment)) {
      throw this.unexpected("GET shipments", status);
    }
    return items;
  }

  private async get(path: string): Promise<{ status: number; body: unknown }> {
    try {
      const response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        headers: { accept: "application/json" },
        signal: AbortSignal.timeout(this.timeoutMs),
      });
      const body: unknown = await response.json().catch(() => undefined);
      return { status: response.status, body };
    } catch (error) {
      throw new CarrierUnavailableError(`Carrier request failed: GET ${path}`, { cause: error });
    }
  }

  private unexpected(what: string, status: number): CarrierUnavailableError {
    return new CarrierUnavailableError(`Carrier gave an unexpected answer to ${what} (HTTP ${status})`);
  }
}
