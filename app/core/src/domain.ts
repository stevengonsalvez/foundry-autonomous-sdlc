export const PARCEL_STATUSES = [
  "label_created",
  "in_transit",
  "out_for_delivery",
  "delivered",
  "exception",
] as const;

export type ParcelStatus = (typeof PARCEL_STATUSES)[number];

export type TrackingNumber = string & { readonly __brand: "TrackingNumber" };

export interface ParcelEvent {
  /** ISO 8601 instant, UTC. */
  timestamp: string;
  location: string;
  description: string;
}

export interface Parcel {
  trackingNumber: TrackingNumber;
  status: ParcelStatus;
  /** `YYYY-MM-DD`, or null when the carrier has no estimate. */
  estimatedDelivery: string | null;
  /** Oldest first. */
  events: ParcelEvent[];
}

export interface ParcelSummary {
  trackingNumber: TrackingNumber;
  status: ParcelStatus;
  estimatedDelivery: string | null;
  /** Timestamp of the newest event. */
  lastUpdate: string;
}
