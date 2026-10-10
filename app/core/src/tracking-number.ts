export function parseTrackingNumber(input: string | null | undefined): string | null {
  if (!input && input !== "") return null;

  // Trim regular whitespace and remove common invisible characters
  // including zero-width space (\u200B), zero-width no-break space, and non-breaking space
  const invisible = /[\u00A0\u200B\uFEFF]/g;
  let s = String(input).replace(invisible, "").trim();
  if (s === "") return null;

  // Uppercase the cleaned input so we accept lowercase inputs
  s = s.toUpperCase();

  // Validate: must be two uppercase letters followed by 10 digits
  if (!/^[A-Z]{2}\d{10}$/.test(s)) return null;
  return s;
}
