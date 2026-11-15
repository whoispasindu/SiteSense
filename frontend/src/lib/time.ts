import { siteTimeZone } from "./locale";

/** Site time: clocks and dates use the company's time zone (SITESENSE_TIME_ZONE, lib/locale.ts). */

export function formatSiteClock(date: Date): string {
  const day = new Intl.DateTimeFormat("en-GB", {
    timeZone: siteTimeZone(),
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(date);
  const time = new Intl.DateTimeFormat("en-GB", {
    timeZone: siteTimeZone(),
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(date);
  return `${day} · ${time}`;
}

export function formatSiteDate(date: Date): string {
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeZone: siteTimeZone() }).format(date);
}

export function greeting(date: Date): string {
  const hour = Number(
    new Intl.DateTimeFormat("en-GB", { hour: "numeric", hourCycle: "h23", timeZone: siteTimeZone() }).format(date),
  );
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

/** Today's calendar date on site (the company's time zone), as YYYY-MM-DD. */
export function siteTodayIso(now: Date = new Date()): string {
  // en-CA formats dates as YYYY-MM-DD.
  return new Intl.DateTimeFormat("en-CA", { timeZone: siteTimeZone() }).format(now);
}

/** Calendar arithmetic on YYYY-MM-DD strings (no time zone involved). */
export function addDaysIso(iso: string, days: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, (d ?? 1) + days));
  return date.toISOString().slice(0, 10);
}

/** "Fri 9 Oct" for a YYYY-MM-DD date. */
export function formatDayShort(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(
    new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1)),
  );
}

/** "14:05" in site time for a timestamp. */
export function formatSiteTime(timestamp: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: siteTimeZone(),
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(timestamp));
}

/** "5 min ago", "3 h ago", "2 days ago": for notification lists. */
export function timeAgo(timestamp: string, now: Date = new Date()): string {
  const minutes = Math.max(0, Math.round((now.getTime() - new Date(timestamp).getTime()) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${String(minutes)} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${String(hours)} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${String(days)} days ago`;
}

/** "11 Oct 2026, 09:15" in site time: for histories that span days. */
export function formatSiteDateTime(timestamp: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: siteTimeZone(),
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(timestamp));
}
