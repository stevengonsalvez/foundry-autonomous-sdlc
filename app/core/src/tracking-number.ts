export function parseTrackingNumber(input: string | null | undefined): string | null {
  if (input == null) return null;
  // Normalise: trim whitespace, remove common invisible characters, uppercase
  // Remove zero-width and non-breaking spaces etc.
  const invisible = /[\u200B-\u200F\uFEFF\u00A0]/g;
  const cleaned = input.replace(invisible, "").trim().toUpperCase();
  // Only accept IDs of the form PK followed by exactly 10 digits
  if (!/^PK\d{10}$/.test(cleaned)) return null;
  return cleaned;
}
