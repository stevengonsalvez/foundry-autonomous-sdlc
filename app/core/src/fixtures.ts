import type { CarrierClient, CarrierShipment } from "./carrier";

/** Eight sample shipments, history newest first, as the carrier would return them. */
export const SAMPLE_SHIPMENTS: readonly CarrierShipment[] = [
  {
    id: "PK1000000001",
    state: "TRANSIT",
    eta: "2026-10-13",
    history: [
      { ts: "2026-10-10T06:42:00Z", place: "Hamburg, DE", note: "Departed sorting hub" },
      { ts: "2026-10-09T21:15:00Z", place: "Hamburg, DE", note: "Arrived at sorting hub" },
      { ts: "2026-10-09T13:20:00Z", place: "Rotterdam, NL", note: "Departed origin facility" },
      { ts: "2026-10-09T09:05:00Z", place: "Rotterdam, NL", note: "Picked up from sender" },
      { ts: "2026-10-08T16:30:00Z", place: "Rotterdam, NL", note: "Shipping label created" },
    ],
  },
  {
    id: "PK1000000002",
    state: "OFD",
    eta: "2026-10-10",
    history: [
      { ts: "2026-10-10T07:55:00Z", place: "Leeds, GB", note: "Out for delivery" },
      { ts: "2026-10-10T05:10:00Z", place: "Leeds, GB", note: "Arrived at local depot" },
      { ts: "2026-10-09T18:45:00Z", place: "Birmingham, GB", note: "Departed regional hub" },
      { ts: "2026-10-08T10:00:00Z", place: "Dover, GB", note: "Cleared customs" },
      { ts: "2026-10-07T15:20:00Z", place: "Calais, FR", note: "Picked up from sender" },
    ],
  },
  {
    id: "PK1000000003",
    state: "DELIVERED",
    eta: "2026-10-08",
    history: [
      { ts: "2026-10-08T11:32:00Z", place: "Manchester, GB", note: "Delivered, signed for by recipient" },
      { ts: "2026-10-08T08:05:00Z", place: "Manchester, GB", note: "Out for delivery" },
      { ts: "2026-10-07T22:40:00Z", place: "Manchester, GB", note: "Arrived at local depot" },
      { ts: "2026-10-06T14:10:00Z", place: "Antwerp, BE", note: "Picked up from sender" },
    ],
  },
  {
    id: "PK1000000004",
    state: "CREATED",
    eta: "2026-10-15",
    history: [{ ts: "2026-10-10T09:12:00Z", place: "Lyon, FR", note: "Shipping label created, awaiting pickup" }],
  },
  {
    id: "PK1000000005",
    state: "EXCEPTION",
    eta: null,
    history: [
      { ts: "2026-10-09T12:48:00Z", place: "Frankfurt, DE", note: "Held for customs documents" },
      { ts: "2026-10-09T07:30:00Z", place: "Frankfurt, DE", note: "Arrived at international gateway" },
      { ts: "2026-10-07T19:05:00Z", place: "Singapore, SG", note: "Departed origin facility" },
      { ts: "2026-10-07T08:40:00Z", place: "Singapore, SG", note: "Picked up from sender" },
    ],
  },
  {
    id: "PK1000000006",
    state: "TRANSIT",
    eta: "2026-10-12",
    history: [
      { ts: "2026-10-09T23:58:00Z", place: "Madrid, ES", note: "Arrived at sorting hub" },
      { ts: "2026-10-09T15:25:00Z", place: "Zaragoza, ES", note: "Departed regional hub" },
      { ts: "2026-10-09T06:50:00Z", place: "Barcelona, ES", note: "Picked up from sender" },
    ],
  },
  {
    id: "PK1000000007",
    state: "DELIVERED",
    eta: "2026-10-05",
    history: [
      { ts: "2026-10-05T16:20:00Z", place: "Dublin, IE", note: "Delivered to a safe place" },
      { ts: "2026-10-05T09:15:00Z", place: "Dublin, IE", note: "Out for delivery" },
      { ts: "2026-10-04T20:00:00Z", place: "Dublin, IE", note: "Arrived at local depot" },
      { ts: "2026-10-03T11:35:00Z", place: "Holyhead, GB", note: "Departed regional hub" },
      { ts: "2026-10-02T14:00:00Z", place: "Cardiff, GB", note: "Picked up from sender" },
    ],
  },
  {
    id: "PK1000000008",
    state: "EXCEPTION",
    eta: null,
    history: [
      { ts: "2026-10-08T15:10:00Z", place: "Milan, IT", note: "Delivery attempt failed, recipient not available" },
      { ts: "2026-10-08T08:25:00Z", place: "Milan, IT", note: "Out for delivery" },
      { ts: "2026-10-07T21:30:00Z", place: "Milan, IT", note: "Arrived at local depot" },
      { ts: "2026-10-06T12:00:00Z", place: "Zurich, CH", note: "Picked up from sender" },
    ],
  },
];

/** In-memory carrier over the sample shipments. Returns copies so callers cannot alter the fixtures. */
export class FixtureCarrierClient implements CarrierClient {
  constructor(private readonly shipments: readonly CarrierShipment[] = SAMPLE_SHIPMENTS) {}

  async getShipment(id: string): Promise<CarrierShipment | null> {
    const found = this.shipments.find((s) => s.id === id);
    return found ? structuredClone(found) : null;
  }

  async listShipments(): Promise<CarrierShipment[]> {
    return structuredClone([...this.shipments]);
  }
}
