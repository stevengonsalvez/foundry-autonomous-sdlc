import {
  CarrierUnavailableError,
  InvalidTrackingNumberError,
  ParcelNotFoundError,
  type Parcel,
  type ParcelService,
  type ParcelSummary,
} from "@parcel/core";

/** Talks to the API under `/api`. Failures surface as the same errors the core service throws. */
export class HttpParcelService implements ParcelService {
  constructor(
    private readonly baseUrl = "",
    private readonly fetchImpl: typeof fetch = (...args) => fetch(...args),
  ) {}

  async getParcel(trackingNumber: string): Promise<Parcel> {
    const response = await this.get(`/api/parcels/${encodeURIComponent(trackingNumber)}`);
    if (response.status === 400) throw new InvalidTrackingNumberError(trackingNumber);
    if (response.status === 404) throw new ParcelNotFoundError(trackingNumber);
    return (await this.json(response)) as Parcel;
  }

  async listParcels(): Promise<ParcelSummary[]> {
    const body = (await this.json(await this.get("/api/parcels"))) as { parcels?: ParcelSummary[] };
    if (!Array.isArray(body.parcels)) throw new CarrierUnavailableError("The parcel list was malformed");
    return body.parcels;
  }

  private async get(path: string): Promise<Response> {
    try {
      return await this.fetchImpl(`${this.baseUrl}${path}`, { headers: { accept: "application/json" } });
    } catch (error) {
      throw new CarrierUnavailableError("The tracking service could not be reached", { cause: error });
    }
  }

  private async json(response: Response): Promise<unknown> {
    if (!response.ok) throw new CarrierUnavailableError(`The tracking service answered ${response.status}`);
    try {
      return await response.json();
    } catch (error) {
      throw new CarrierUnavailableError("The tracking service sent an unreadable answer", { cause: error });
    }
  }
}
