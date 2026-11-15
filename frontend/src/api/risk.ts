import { useQuery } from "@tanstack/react-query";
import { z } from "zod";

import { apiRequest } from "./client";

const decimal = z.string().regex(/^-?\d+(\.\d+)?$/, "Expected a decimal string");

export const RISK_LEVELS = ["low", "medium", "high"] as const;
export type RiskLevel = (typeof RISK_LEVELS)[number];

const driverSchema = z.object({
  feature: z.string(),
  label: z.string(),
  // "signal": something the site can act on; "context": size, type, how far along.
  kind: z.enum(["signal", "context"]),
  value: z.string(),
  // How much this factor moved each forecast away from the average training snapshot (SHAP values).
  delay_days: z.number(),
  overrun_pct: z.number(),
});
export type Driver = z.infer<typeof driverSchema>;

/** The likely range: 8 in 10 outcomes fall inside it (10th to 90th percentile). */
const rangeSchema = z.object({ low: z.number(), high: z.number() });
export type Range = z.infer<typeof rangeSchema>;
const scoreRangeSchema = z.object({ low: z.number().int().min(0).max(100), high: z.number().int().min(0).max(100) });
const rangesSchema = z.object({ delay_days: rangeSchema, overrun_pct: rangeSchema, score: scoreRangeSchema });
export type Ranges = z.infer<typeof rangesSchema>;

const riskSchema = z.object({
  score_date: z.iso.date(),
  score: z.number().int().min(0).max(100),
  level: z.enum(RISK_LEVELS),
  delay_days: decimal,
  overrun_pct: decimal,
  // Null only for scores made before risk model v2.
  ranges: rangesSchema.nullable(),
  drivers: z.array(driverSchema),
  notes: z.array(z.string()),
  model_version: z.string(),
  scored_at: z.iso.datetime({ offset: true }),
});
export type Risk = z.infer<typeof riskSchema>;

const projectRiskSchema = z.object({
  project_id: z.uuid(),
  latest: riskSchema.nullable(),
  history: z.array(
    z.object({ date: z.iso.date(), score: z.number().int(), level: z.enum(RISK_LEVELS), score_range: scoreRangeSchema.nullable() }),
  ),
});
export type ProjectRisk = z.infer<typeof projectRiskSchema>;

export const rankingSchema = z.array(
  z.object({
    project_id: z.uuid(),
    code: z.string(),
    name: z.string(),
    site_code: z.string(),
    status: z.string(),
    score: z.number().int().nullable(),
    level: z.enum(RISK_LEVELS).nullable(),
    delay_days: decimal.nullable(),
    overrun_pct: decimal.nullable(),
    ranges: rangesSchema.nullable(),
    top_driver: z.string().nullable(),
    score_date: z.iso.date().nullable(),
  }),
);
export type RiskRanking = z.infer<typeof rankingSchema>;

export const riskKeys = {
  project: (id: string) => ["risk", "project", id] as const,
  ranking: ["risk", "ranking"] as const,
};

export function useProjectRisk(projectId: string, enabled = true) {
  return useQuery({
    queryKey: riskKeys.project(projectId),
    queryFn: ({ signal }) =>
      apiRequest(`/projects/${encodeURIComponent(projectId)}/risk`, projectRiskSchema, { signal }).then((r) => r.data),
    enabled,
  });
}

export function useRiskRanking(enabled = true) {
  return useQuery({
    queryKey: riskKeys.ranking,
    queryFn: ({ signal }) => apiRequest("/risk/projects", rankingSchema, { signal }).then((r) => r.data),
    enabled,
  });
}

// --- What-if planner (Phase 10) ------------------------------------------------------------------------

export const ACTION_IDS = ["add_crew", "work_sundays", "expedite_materials", "weather_protection"] as const;
export type ActionId = (typeof ACTION_IDS)[number];

/** A forecast always travels with its likely range. */
const forecastSchema = z.object({
  delay_days: z.number(),
  delay_range: rangeSchema,
  overrun_pct: z.number(),
  overrun_range: rangeSchema,
  score: z.number().int().min(0).max(100),
  score_range: scoreRangeSchema,
  level: z.enum(RISK_LEVELS),
});
export type Forecast = z.infer<typeof forecastSchema>;

/** What an action saves (positive is better): from half its planned change to all of it. */
const effectSchema = z.object({ low: z.number(), high: z.number() });
export type Effect = z.infer<typeof effectSchema>;

const whatIfSchema = z.object({
  project_id: z.uuid(),
  as_of: z.iso.date(),
  model_version: z.string(),
  baseline: forecastSchema,
  actions: z.array(
    z.object({
      id: z.enum(ACTION_IDS),
      label: z.string(),
      description: z.string(),
      change: z.string(),
      selected: z.boolean(),
      delay_saved_days: effectSchema,
      overrun_saved_pct: effectSchema,
      cost: decimal.nullable(),
      cost_pct: z.number().nullable(),
    }),
  ),
  plan: forecastSchema.nullable(),
  plan_delay_saved_days: effectSchema.nullable(),
  plan_overrun_saved_pct: effectSchema.nullable(),
  costs_not_entered: z.array(z.string()),
  advice: z.array(z.object({ id: z.string(), label: z.string(), text: z.string() })),
  notes: z.array(z.string()),
});
export type WhatIf = z.infer<typeof whatIfSchema>;

export interface PlannedAction {
  id: ActionId;
  cost: string | null; // the company's currency, as a decimal string; null when the PM left it blank
}

/** The planner calculates only (nothing is saved), so it is fetched like any read, keyed by the plan. */
export function useWhatIf(projectId: string, actions: PlannedAction[], enabled = true) {
  return useQuery({
    queryKey: ["risk", "what-if", projectId, actions] as const,
    queryFn: ({ signal }) =>
      apiRequest(`/projects/${encodeURIComponent(projectId)}/risk/what-if`, whatIfSchema, {
        method: "POST",
        body: { actions },
        signal,
      }).then((r) => r.data),
    enabled,
    placeholderData: (previous) => previous,
  });
}
