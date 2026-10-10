export function normalizeTrackingNumber(input: string): string {
  if (typeof input !== "string") return input as unknown as string;
  // Trim whitespace and remove common invisible characters
  // Remove zero-width and non-breaking spaces
  const cleaned = input.trim().replace(/[\u200B-\u200D\uFEFF\u00A0]/g, "");
  return cleaned.toUpperCase();
}

export function parseTrackingNumber(raw: string | null): string | null {
  if (!raw) return null;
  const value = normalizeTrackingNumber(raw);
  // Valid format: two uppercase letters followed by 10 digits (e.g. PK1000000001)
  if (!/^[A-Z]{2}\d{10}$/.test(value)) return null;
  return value;
}
