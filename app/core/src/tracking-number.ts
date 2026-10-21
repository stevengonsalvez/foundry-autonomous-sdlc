import type { TrackingNumber } from "./domain";

const TRACKING_NUMBER = /^(?:PK\d{10}|\s+PK\d{10}\s+)$/i;

export function parseTrackingNumber(input: string): TrackingNumber | null {
  return TRACKING_NUMBER.test(input) ? (input.trim().toUpperCase() as TrackingNumber) : null;
}
