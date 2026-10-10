import type { TrackingNumber } from "./domain";

const TRACKING_NUMBER = /^PK\d{10}$/;

export function parseTrackingNumber(input: string): TrackingNumber | null {
  return TRACKING_NUMBER.test(input) ? (input as TrackingNumber) : null;
}
