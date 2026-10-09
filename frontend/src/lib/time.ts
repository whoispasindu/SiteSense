/** Site time: SiteSense targets Sri Lankan contractors, so clocks and dates use Colombo time. */
export const SITE_TIME_ZONE = "Asia/Colombo";

export function formatSiteClock(date: Date): string {
  const day = new Intl.DateTimeFormat("en-GB", {
    timeZone: SITE_TIME_ZONE,
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
  const time = new Intl.DateTimeFormat("en-GB", {
    timeZone: SITE_TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(date);
  return `${day} · ${time}`.toUpperCase();
}

export function formatSiteDate(date: Date): string {
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeZone: SITE_TIME_ZONE }).format(date);
}

export function greeting(date: Date): string {
  const hour = Number(
    new Intl.DateTimeFormat("en-GB", { hour: "numeric", hourCycle: "h23", timeZone: SITE_TIME_ZONE }).format(date),
  );
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}
