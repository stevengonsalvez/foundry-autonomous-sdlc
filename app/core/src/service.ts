import type { CarrierClient, CarrierShipment } from "./carrier";
import type { Parcel, ParcelSummary } from "./domain";
import {
  CarrierUnavailableError,
  InvalidTrackingNumberError,
  ParcelNotFoundError,
} from "./errors";
import { toParcel, toParcelSummary } from "./mapping";
import { parseTrackingNumber } from "./tracking-number";

/**
 * What the web app and the API both need. Rejects with InvalidTrackingNumberError,
 * ParcelNotFoundError or CarrierUnavailableError.
 */
export interface ParcelService {
  getParcel(trackingNumber: string): Promise<Parcel>;
  listParcels(): Promise<ParcelSummary[]>;
}

async function fromCarrier<T>(call: () => Promise<T>): Promise<T> {
  try {
    return await call();
  } catch (error) {
    if (error instanceof CarrierUnavailableError) throw error;
    throw new CarrierUnavailableError("Carrier call failed", { cause: error });
  }
}

function newestFirst(a: ParcelSummary, b: ParcelSummary): number {
  if (a.lastUpdate !== b.lastUpdate) return a.lastUpdate < b.lastUpdate ? 1 : -1;
  return a.trackingNumber < b.trackingNumber ? -1 : 1;
}

export function createParcelService(carrier: CarrierClient): ParcelService {
  return {
    async getParcel(input) {
      const trackingNumber = parseTrackingNumber(input);
      if (!trackingNumber) throw new InvalidTrackingNumberError(input);
      const shipment = await fromCarrier(() => carrier.getShipment(trackingNumber));
      if (!shipment) throw new ParcelNotFoundError(trackingNumber);
      return toParcel(shipment);
    },

    async listParcels() {
      const shipments: CarrierShipment[] = await fromCarrier(() => carrier.listShipments());
      return shipments.map(toParcelSummary).sort(newestFirst);
    },
  };
}
