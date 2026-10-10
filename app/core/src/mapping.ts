import type { CarrierShipment, CarrierState } from "./carrier";
import { CarrierUnavailableError } from "./errors";
import type { Parcel, ParcelStatus, ParcelSummary, TrackingNumber } from "./domain";

const STATUS_BY_STATE: Record<CarrierState, ParcelStatus> = {
  CREATED: "label_created",
  TRANSIT: "in_transit",
  OFD: "out_for_delivery",
  DELIVERED: "delivered",
  EXCEPTION: "exception",
};

export function toParcel(shipment: CarrierShipment): Parcel {
  return {
    trackingNumber: shipment.id as TrackingNumber,
    status: STATUS_BY_STATE[shipment.state],
    estimatedDelivery: shipment.eta,
    events: shipment.history
      .map((entry) => ({ timestamp: entry.ts, location: entry.place, description: entry.note }))
      .reverse(),
  };
}

export function toParcelSummary(shipment: CarrierShipment): ParcelSummary {
  const newest = shipment.history[0];
  if (!newest) throw new CarrierUnavailableError(`Carrier returned shipment ${shipment.id} without history`);
  return {
    trackingNumber: shipment.id as TrackingNumber,
    status: STATUS_BY_STATE[shipment.state],
    estimatedDelivery: shipment.eta,
    lastUpdate: newest.ts,
  };
}
