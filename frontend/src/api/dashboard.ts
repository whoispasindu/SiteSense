import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { apiBlob, apiRequest } from "./client";
import { weatherDaySchema } from "./reports";
import { rankingSchema } from "./risk";

const decimal = z.string().regex(/^-?\d+(\.\d+)?$/, "Expected a decimal string");
const timestamp = z.iso.datetime({ offset: true });

// --- Portfolio analytics (Phase 11) ---------------------------------------------------------------------

const kpisSchema = z.object({
  active_projects: z.number().int(),
  total_projects: z.number().int(),
  average_actual_pct: z.number().nullable(),
  average_planned_pct: z.number().nullable(),
  behind_plan: z.number().int(),
  reports_due_today: z.number().int(),
  reports_filed_today: z.number().int(),
  issues_this_week: z.number().int(),
  stop_work_open: z.number().int(),
  waiting_for_you: z.number().int(),
  // Null for roles without risk access.
  high_risk: z.number().int().nullable(),
});
export type Kpis = z.infer<typeof kpisSchema>;

const costPointSchema = z.object({
  project_id: z.uuid(),
  code: z.string(),
  name: z.string(),
  budget: decimal,
  committed: decimal,
  // At current rates (the cost rules).
  forecast_final: decimal,
  // The risk model's likely final cost; null until the project is scored with ranges.
  model_final_range: z.object({ low: decimal, high: decimal }).nullable(),
});
export type CostPoint = z.infer<typeof costPointSchema>;

const costSchema = z.object({
  totals: z.object({ budget: decimal, committed: decimal, forecast_final: decimal, over_budget: z.number().int() }),
  projects: z.array(costPointSchema),
});
export type CostAgainstPlan = z.infer<typeof costSchema>;

export const ISSUE_CATEGORIES = ["material_delay", "labour", "weather", "equipment", "safety", "design", "quality", "other"] as const;
export type IssueCategory = (typeof ISSUE_CATEGORIES)[number];

const issueWeekSchema = z.object({
  week_start: z.iso.date(),
  total: z.number().int(),
  by_category: z.record(z.string(), z.number().int()),
});
export type IssueWeek = z.infer<typeof issueWeekSchema>;

const siteWeatherSchema = z.object({
  site_code: z.string(),
  site_name: z.string(),
  available: z.boolean(),
  stale: z.boolean(),
  fetched_at: timestamp.nullable(),
  days: z.array(weatherDaySchema),
  heavy_rain_threshold_mm: decimal,
});
export type SiteWeather = z.infer<typeof siteWeatherSchema>;

export const APPROVAL_KINDS = ["material_request", "purchase_order", "claim", "variation"] as const;
const approvalSchema = z.object({
  kind: z.enum(APPROVAL_KINDS),
  id: z.uuid(),
  number: z.string(),
  project_id: z.uuid(),
  project_code: z.string(),
  title: z.string(),
  status: z.string(),
  since: timestamp,
  link: z.string(),
});
export type ApprovalItem = z.infer<typeof approvalSchema>;

const portfolioSchema = z.object({
  as_of: z.iso.date(),
  kpis: kpisSchema,
  cost: costSchema.nullable(),
  risk: rankingSchema.nullable(),
  issue_trend: z.array(issueWeekSchema),
  weather: z.array(siteWeatherSchema),
  approvals: z.array(approvalSchema),
});
export type Portfolio = z.infer<typeof portfolioSchema>;

// --- The daily briefing ---------------------------------------------------------------------------------

export const SOURCE_KINDS = ["risk", "programme", "reports", "issues", "stop_work", "weather", "approvals", "cost"] as const;
export type SourceKind = (typeof SOURCE_KINDS)[number];

const briefingSchema = z.object({
  date: z.iso.date(),
  source: z.enum(["ai", "rules"]),
  label: z.string(),
  model: z.string().nullable(),
  generated_at: timestamp,
  bullets: z.array(
    z.object({
      text: z.string(),
      projects: z.array(z.string()),
      // Counted by the server, never by the model.
      sources: z.array(z.object({ kind: z.enum(SOURCE_KINDS), count: z.number().int() })),
    }),
  ),
  note: z.string().nullable(),
});
export type Briefing = z.infer<typeof briefingSchema>;

// --- Email preferences ----------------------------------------------------------------------------------

const preferencesSchema = z.object({
  email_urgent: z.boolean(),
  email_digest: z.boolean(),
  weekly_report: z.boolean(),
  weekly_report_available: z.boolean(),
  stop_work_always: z.boolean(),
  email_configured: z.boolean(),
  digest_time: z.string(),
  weekly_time: z.string(),
});
export type NotificationPreferences = z.infer<typeof preferencesSchema>;
export interface PreferencesInput {
  email_urgent: boolean;
  email_digest: boolean;
  weekly_report?: boolean;
}

export const dashboardKeys = {
  portfolio: ["dashboard", "portfolio"] as const,
  briefing: ["dashboard", "briefing"] as const,
  preferences: ["me", "notification-preferences"] as const,
};

export function usePortfolio(enabled = true) {
  return useQuery({
    queryKey: dashboardKeys.portfolio,
    queryFn: ({ signal }) => apiRequest("/analytics/portfolio", portfolioSchema, { signal }).then((r) => r.data),
    enabled,
    refetchInterval: 5 * 60_000,
  });
}

export function useBriefing(enabled = true) {
  return useQuery({
    queryKey: dashboardKeys.briefing,
    // The model may take a few seconds; the server falls back to the rule-based text on its own.
    queryFn: ({ signal }) => apiRequest("/briefing/today", briefingSchema, { signal, timeoutMs: 45_000 }).then((r) => r.data),
    enabled,
    staleTime: 5 * 60_000,
  });
}

/** The weekly PDF (cost roles only). Fetched with the session, then saved through a short-lived link. */
export async function downloadWeeklyReport(today: string): Promise<void> {
  const blob = await apiBlob("/reports/weekly.pdf", { what: "the weekly report" });
  const url = URL.createObjectURL(blob);
  try {
    const link = document.createElement("a");
    link.href = url;
    link.download = `sitesense-weekly-${today}.pdf`;
    document.body.append(link);
    link.click();
    link.remove();
  } finally {
    // Give the browser a moment to start the download before the link is revoked.
    setTimeout(() => {
      URL.revokeObjectURL(url);
    }, 10_000);
  }
}

export function useNotificationPreferences() {
  return useQuery({
    queryKey: dashboardKeys.preferences,
    queryFn: ({ signal }) => apiRequest("/me/notification-preferences", preferencesSchema, { signal }).then((r) => r.data),
  });
}

export function useSaveNotificationPreferences() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: PreferencesInput) =>
      apiRequest("/me/notification-preferences", preferencesSchema, { method: "PUT", body }).then((r) => r.data),
    onSuccess: (data) => {
      queryClient.setQueryData(dashboardKeys.preferences, data);
    },
  });
}
