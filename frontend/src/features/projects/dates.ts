const DAY_MS = 86_400_000;

function parseDate(iso: string): number {
  // Dates are calendar dates (no time zone); compare them at UTC midnight.
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1);
}

function utcMidnight(date: Date): number {
  return Date.UTC(date.getFullYear(), date.getMonth(), date.getDate());
}

export function durationWeeks(start: string, end: string): number {
  return Math.round((parseDate(end) - parseDate(start)) / DAY_MS / 7);
}

/** How far through the contract period ``today`` is. */
export function programmeProgress(
  start: string,
  end: string,
  today: Date,
): { elapsed: number; state: "not_started" | "running" | "overdue" } {
  const s = parseDate(start);
  const e = parseDate(end);
  const t = utcMidnight(today);
  if (t < s) return { elapsed: 0, state: "not_started" };
  if (t > e) return { elapsed: 100, state: "overdue" };
  const span = Math.max(1, e - s);
  return { elapsed: Math.round(((t - s) / span) * 1000) / 10, state: "running" };
}

const display = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });

export function formatDate(iso: string): string {
  return display.format(new Date(parseDate(iso)));
}
