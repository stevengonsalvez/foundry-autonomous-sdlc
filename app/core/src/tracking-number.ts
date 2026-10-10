export function parseTrackingNumber(input: unknown): string | null {
  if (typeof input !== "string") return null;
  // Trim surrounding whitespace and remove common invisible characters
  const cleaned = input
    .replace(/[\u200B\uFEFF\u00A0]/g, "")
    .trim()
    .toUpperCase();
  if (!/^PK\d{10}$/.test(cleaned)) return null;
  return cleaned;
}
