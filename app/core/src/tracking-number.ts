import type { TrackingNumber } from "./domain";

const TRACKING_NUMBER = /^PK\d{10}$/i;

export function parseTrackingNumber(input: string): TrackingNumber | null {
  return TRACKING_NUMBER.test(input) ? (input.toUpperCase() as TrackingNumber) : null;
}
