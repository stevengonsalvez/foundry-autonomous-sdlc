export function formatDateTime(input: string | Date | null | undefined) {
  if (!input) return String(input);
  // Accept date-only strings like 2026-10-12 and render as UTC date without timezone shift
  // If given a Date, use its UTC year/month/day
  let year: number, month: number, day: number, weekday: number;
  if (typeof input === "string") {
    // Try ISO date-only YYYY-MM-DD
    const m = input.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (m) {
      year = Number(m[1]);
      month = Number(m[2]) - 1;
      day = Number(m[3]);
      const d = new Date(Date.UTC(year, month, day));
      weekday = d.getUTCDay();
    } else {
      // try full ISO
      const d = new Date(input);
      if (Number.isNaN(d.getTime())) return String(input);
      year = d.getUTCFullYear();
      month = d.getUTCMonth();
      day = d.getUTCDate();
      weekday = d.getUTCDay();
    }
  } else {
    const d = input;
    if (!(d instanceof Date) || Number.isNaN(d.getTime())) return String(input);
    year = d.getUTCFullYear();
    month = d.getUTCMonth();
    day = d.getUTCDate();
    weekday = d.getUTCDay();
  }

  const weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${weekdays[weekday]} ${String(day).padStart(2, "0")} ${months[month]} ${year}`;
}
