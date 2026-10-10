/* Tracking number parsing and normalization */

const VALID_PREFIXES = ["PK"];

/** Remove invisible characters like zero-width and NBSP, trim, uppercase */
export function normalizeTrackingNumber(input: string): string {
  if (typeof input !== "string") return input;
  // Remove common invisible characters and trim
  // Unicode categories: zero-width (\u200B-\u200D, \uFEFF), non-breaking space \u00A0
  const invisible = /[\u200B-\u200D\uFEFF\u00A0]/g;
  const trimmed = input.replace(invisible, "").trim();
  return trimmed.toUpperCase();
}

export function parseTrackingNumber(input: string | null | undefined): string | null {
  if (!input) return null;
  // first normalize
  const value = normalizeTrackingNumber(input);
  // Valid format: prefix + 10 digits (e.g., PK1000000001)
  const m = /^([A-Z]{2})(\d{10})$/.exec(value);
  if (!m) return null;
  const prefix = m[1];
  if (!VALID_PREFIXES.includes(prefix)) return null;
  return value;
}
