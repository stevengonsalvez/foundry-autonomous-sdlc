export function formatDateTime(iso: string): string {
  // Expected format in tests: "10 Oct 2026, 06:42 UTC"
  // The input is an ISO timestamp (with timezone Z). Keep UTC and format day first.
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const weekday = d.toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" });
  const dayMonthYear = d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC" });
  return `${dayMonthYear}, ${time} UTC`;
}

export function formatDateOnly(dateOnly: string): string {
  // dateOnly like "2026-10-12" should render as "Mon 12 Oct 2026" (weekday day short-month year)
  // Parse without timezone shifting by constructing as UTC date.
  const [y, m, d] = dateOnly.split("-").map(Number);
  if (![y, m, d].every((n) => Number.isFinite(n))) return "";
  // Create Date in UTC at midday to avoid DST edge cases
  const dt = new Date(Date.UTC(y, m - 1, d, 12, 0, 0));
  const weekday = dt.toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" });
  const dayMonthYear = dt.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
  return `${weekday} ${dayMonthYear.split(' ').slice(0).join(' ')}`.replace(/\s+/g, ' ').trim();
}
