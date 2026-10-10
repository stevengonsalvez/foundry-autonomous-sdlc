export function formatDate(dateOnly: string): string {
  // Date-only string like YYYY-MM-DD. Parse without timezone shifts by splitting instead of Date constructor.
  const [y, m, d] = dateOnly.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  // Format as 'Mon 12 Oct 2026' in en-GB short month, weekday
  return dt.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
}
