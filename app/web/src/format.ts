const dateTime = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: "UTC",
});

/** `10 Oct 2026, 06:42 UTC`. Shown in UTC so everyone reads the same time. */
export function formatDateTime(iso: string): string {
  const instant = new Date(iso);
  return Number.isNaN(instant.getTime()) ? iso : `${dateTime.format(instant)} UTC`;
}
