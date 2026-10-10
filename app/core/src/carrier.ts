/** Shapes of the external carrier API (see contracts/carrier.openapi.yaml). */

export const CARRIER_STATES = ["CREATED", "TRANSIT", "OFD", "DELIVERED", "EXCEPTION"] as const;

export type CarrierState = (typeof CARRIER_STATES)[number];

export interface CarrierHistoryEntry {
  ts: string;
  place: string;
  note: string;
}

export interface CarrierShipment {
  id: string;
  state: CarrierState;
  /** Newest first. */
  history: CarrierHistoryEntry[];
  eta: string | null;
}

export interface CarrierClient {
  /** Resolves to null when the carrier does not know the id. Rejects with CarrierUnavailableError when it cannot answer. */
  getShipment(id: string): Promise<CarrierShipment | null>;
  listShipments(): Promise<CarrierShipment[]>;
}
