import type { ApprovalItem, IssueCategory, SiteWeather, SourceKind } from "../../api/dashboard";
import type { Weather } from "../../api/reports";
import { siteTimeZone } from "../../lib/locale";

const SOURCE_WORDS: Record<SourceKind, [string, string]> = {
  risk: ["risk score", "risk scores"],
  programme: ["programme", "programmes"],
  reports: ["report due", "reports due"],
  issues: ["issue", "issues"],
  stop_work: ["stop-work flag", "stop-work flags"],
  weather: ["pour in rain", "pours in rain"],
  approvals: ["item waiting", "items waiting"],
  cost: ["cost plan", "cost plans"],
};

/** "3 issues", "1 risk score": what a briefing bullet rests on, counted by the server. */
export function sourceText(kind: SourceKind, count: number): string {
  const [one, many] = SOURCE_WORDS[kind];
  return `${String(count)} ${count === 1 ? one : many}`;
}

export const CATEGORY_LABELS: Record<IssueCategory, string> = {
  material_delay: "Material delay",
  labour: "Labour",
  weather: "Weather",
  equipment: "Equipment",
  safety: "Safety",
  design: "Design",
  quality: "Quality",
  other: "Other",
};

export function categoryLabel(key: string): string {
  return key in CATEGORY_LABELS ? CATEGORY_LABELS[key as IssueCategory] : key;
}

export const APPROVAL_LABELS: Record<ApprovalItem["kind"], string> = {
  material_request: "Material request",
  purchase_order: "Ready to order",
  claim: "Progress claim",
  variation: "Variation",
};

/** The dashboard's saved forecast in the shape the report form's weather strip already draws. */
export function asWeather(site: SiteWeather): Weather {
  let message: string | null = null;
  if (!site.available) message = "No forecast is saved for this site yet. It is fetched every morning at 05:30.";
  else if (site.stale) message = "This morning's weather refresh did not run. Showing the last saved forecast.";
  return {
    site_code: site.site_code,
    available: site.available,
    stale: site.stale,
    fetched_at: site.fetched_at,
    message,
    days: site.days,
    heavy_rain_threshold_mm: site.heavy_rain_threshold_mm,
  };
}

/** "07:42": a time of day at the site. */
export function siteClock(timestamp: string): string {
  return new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: siteTimeZone() }).format(
    new Date(timestamp),
  );
}
