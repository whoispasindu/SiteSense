import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { apiRequest } from "./client";

/** A supplier's chance of delivering on time (BR-12), always with its range and the deliveries behind it. */
const onTimeSchema = z.object({
  supplier_id: z.uuid(),
  supplier_name: z.string(),
  chance: z.number().min(0).max(1),
  chance_range: z.object({ low: z.number().min(0).max(1), high: z.number().min(0).max(1) }),
  based_on: z.number().int().min(0),
  low_data: z.boolean(),
  below_br12: z.boolean(),
  model: z.string(),
  model_version: z.string(),
});
export type OnTime = z.infer<typeof onTimeSchema>;

const outlookSchema = z.object({
  project_id: z.uuid(),
  expected_delivery: z.iso.date(),
  lead_time_days: z.number().int(),
  suppliers: z.array(onTimeSchema),
  critical_request_ids: z.array(z.uuid()),
  threshold: z.number(),
});
export type Outlook = z.infer<typeof outlookSchema>;

const criticalPathSchema = z.object({
  request_id: z.uuid(),
  critical: z.boolean(),
  from_programme: z.boolean(),
  override: z.boolean().nullable(),
  reason: z.string(),
  can_override: z.boolean(),
  float_days: z.number().int(),
});
export type CriticalPath = z.infer<typeof criticalPathSchema>;

export const supplierKeys = {
  outlook: (projectId: string, expected: string) => ["suppliers", "outlook", projectId, expected] as const,
  critical: (requestId: string) => ["suppliers", "critical", requestId] as const,
};

export function useSupplierOutlook(projectId: string | undefined, expected: string, enabled = true) {
  return useQuery({
    queryKey: supplierKeys.outlook(projectId ?? "", expected),
    queryFn: ({ signal }) =>
      apiRequest(
        `/projects/${encodeURIComponent(projectId ?? "")}/supplier-outlook?expected_delivery=${encodeURIComponent(expected)}`,
        outlookSchema,
        { signal },
      ).then((r) => r.data),
    enabled: enabled && Boolean(projectId) && /^\d{4}-\d{2}-\d{2}$/.test(expected),
    placeholderData: (previous) => previous,
  });
}

export function useCriticalPath(requestId: string) {
  return useQuery({
    queryKey: supplierKeys.critical(requestId),
    queryFn: ({ signal }) =>
      apiRequest(`/material-requests/${encodeURIComponent(requestId)}/critical-path`, criticalPathSchema, { signal }).then(
        (r) => r.data,
      ),
  });
}

/** The project manager marks a request critical (true), not critical (false), or hands it back (null). */
export function useSetCriticalPath(requestId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (critical: boolean | null) =>
      apiRequest(`/material-requests/${encodeURIComponent(requestId)}/critical-path`, criticalPathSchema, {
        method: "PUT",
        body: { critical },
      }).then((r) => r.data),
    onSuccess: (data) => {
      client.setQueryData(supplierKeys.critical(requestId), data);
      void client.invalidateQueries({ queryKey: ["suppliers", "outlook"] });
    },
  });
}

/** "72% (likely 55% to 85%), based on 12 deliveries". */
export function chanceText(estimate: OnTime): string {
  const pct = (v: number) => `${String(Math.round(v * 100))}%`;
  const deliveries = `${String(estimate.based_on)} ${estimate.based_on === 1 ? "delivery" : "deliveries"}`;
  return `${pct(estimate.chance)} (likely ${pct(estimate.chance_range.low)} to ${pct(estimate.chance_range.high)}), based on ${deliveries}`;
}

/**
 * BR-12: the best alternative to a supplier under 50% for a critical-path order: the most likely to be on
 * time, preferring suppliers with enough history; null when no one does better.
 */
export function br12Alternative(outlook: Outlook, supplierId: string): OnTime | null {
  const current = outlook.suppliers.find((s) => s.supplier_id === supplierId);
  if (!current?.below_br12) return null;
  const others = outlook.suppliers.filter((s) => s.supplier_id !== supplierId && s.chance > current.chance);
  const solid = others.filter((s) => !s.low_data && !s.below_br12);
  return [...solid, ...others].at(0) ?? null;
}
