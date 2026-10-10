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

const deliveryDateFormat = new Intl.DateTimeFormat("en-GB", {
  weekday: "short",
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

export function formatEstimatedDelivery(dateStr: string): string {
  const [year, month, day] = dateStr.split("-").map(Number);
  if (!year || !month || !day) return dateStr;
  const instant = new Date(Date.UTC(year, month - 1, day));
  return Number.isNaN(instant.getTime())
    ? dateStr
    : deliveryDateFormat.format(instant).replace(/,/g, "");
}
