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
  // How much this factor moved each forecast, against a typical project at the same stage.
  delay_days: z.number(),
  overrun_pct: z.number(),
});
export type Driver = z.infer<typeof driverSchema>;

const riskSchema = z.object({
  score_date: z.iso.date(),
  score: z.number().int().min(0).max(100),
  level: z.enum(RISK_LEVELS),
  delay_days: decimal,
  overrun_pct: decimal,
  drivers: z.array(driverSchema),
  notes: z.array(z.string()),
  model_version: z.string(),
  scored_at: z.iso.datetime({ offset: true }),
});
export type Risk = z.infer<typeof riskSchema>;

const projectRiskSchema = z.object({
  project_id: z.uuid(),
  latest: riskSchema.nullable(),
  history: z.array(z.object({ date: z.iso.date(), score: z.number().int(), level: z.enum(RISK_LEVELS) })),
});
export type ProjectRisk = z.infer<typeof projectRiskSchema>;

const rankingSchema = z.array(
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
