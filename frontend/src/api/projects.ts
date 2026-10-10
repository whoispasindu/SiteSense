import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { roleSchema, siteSummarySchema } from "./auth";
import { apiRequest } from "./client";

/** Exact decimal strings from the API, e.g. "1114000000.00". */
const decimal = z.string().regex(/^-?\d+(\.\d+)?$/, "Expected a decimal string");

export const PROJECT_STATUSES = ["planning", "active", "on_hold", "completed", "cancelled"] as const;
export const PROJECT_TYPES = ["residential", "commercial", "mixed_use", "industrial", "institutional"] as const;
export type ProjectStatus = (typeof PROJECT_STATUSES)[number];
export type ProjectType = (typeof PROJECT_TYPES)[number];

export const STATUS_LABELS: Record<ProjectStatus, string> = {
  planning: "Planning",
  active: "Active",
  on_hold: "On hold",
  completed: "Completed",
  cancelled: "Cancelled",
};

export const TYPE_LABELS: Record<ProjectType, string> = {
  residential: "Residential",
  commercial: "Commercial",
  mixed_use: "Mixed use",
  industrial: "Industrial",
  institutional: "Institutional",
};

export const projectSummarySchema = z.object({
  id: z.uuid(),
  code: z.string(),
  name: z.string(),
  site: siteSummarySchema,
  client_name: z.string(),
  project_type: z.enum(PROJECT_TYPES),
  status: z.enum(PROJECT_STATUSES),
  start_date: z.iso.date(),
  planned_end: z.iso.date(),
  item_count: z.number().int(),
  // Rates and amounts: present only for roles with "rates:read" (PM, QS, procurement). Site
  // engineers receive a response without them, so every screen must cope with their absence.
  contract_value: decimal.optional(),
  boq_total: decimal.optional(),
  budget_total: decimal.optional(),
});
export type ProjectSummary = z.infer<typeof projectSummarySchema>;

const sectionTotalsSchema = z.object({
  id: z.uuid(),
  code: z.string(),
  name: z.string(),
  item_count: z.number().int(),
  amount: decimal.optional(),
  budget_line_id: z.uuid().optional(),
  budget_amount: decimal.optional(),
});
export type SectionTotals = z.infer<typeof sectionTotalsSchema>;

export const projectDetailSchema = projectSummarySchema.extend({
  description: z.string().nullable(),
  sections: z.array(sectionTotalsSchema),
  team: z.array(z.object({ id: z.uuid(), full_name: z.string(), role: roleSchema, role_label: z.string() })),
  created_at: z.iso.datetime({ offset: true }),
  updated_at: z.iso.datetime({ offset: true }),
});
export type ProjectDetail = z.infer<typeof projectDetailSchema>;

const boqItemSchema = z.object({
  id: z.uuid(),
  item_code: z.string(),
  description: z.string(),
  unit: z.string(),
  quantity: decimal,
  requested_quantity: decimal,
  remaining_quantity: decimal,
  rate: decimal.optional(),
  amount: decimal.optional(),
});
export type BoqItem = z.infer<typeof boqItemSchema>;

export const boqSchema = z.object({
  project_id: z.uuid(),
  sections: z.array(sectionTotalsSchema.extend({ items: z.array(boqItemSchema) })),
  boq_total: decimal.optional(),
  budget_total: decimal.optional(),
  item_count: z.number().int(),
});
export type Boq = z.infer<typeof boqSchema>;

export const importReportSchema = z.object({
  file_name: z.string(),
  imported: z.boolean(),
  dry_run: z.boolean(),
  total_rows: z.number().int(),
  ok_rows: z.number().int(),
  error_rows: z.number().int(),
  skipped_rows: z.number().int(),
  has_budget_rates: z.boolean(),
  replaces_items: z.number().int(),
  boq_total: decimal,
  budget_total: decimal,
  sections: z.array(z.object({ code: z.string(), name: z.string(), items: z.number().int(), amount: decimal, budget: decimal })),
  rows: z.array(
    z.object({
      row: z.number().int(),
      status: z.enum(["ok", "skipped", "error"]),
      section_code: z.string().nullable(),
      item_code: z.string().nullable(),
      description: z.string().nullable(),
      errors: z.array(z.object({ column: z.string(), message: z.string() })),
    }),
  ),
});
export type ImportReport = z.infer<typeof importReportSchema>;

export const projectKeys = {
  all: ["projects"] as const,
  list: (status: string, q: string) => ["projects", "list", status, q] as const,
  detail: (id: string) => ["projects", id] as const,
  boq: (id: string) => ["projects", id, "boq"] as const,
};

const path = (id: string) => `/projects/${encodeURIComponent(id)}`;

export function useProjects(status = "", q = "") {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (q.trim()) params.set("q", q.trim());
  const query = params.toString();
  return useQuery({
    queryKey: projectKeys.list(status, q.trim()),
    queryFn: ({ signal }) =>
      apiRequest(`/projects${query ? `?${query}` : ""}`, z.array(projectSummarySchema), { signal }).then((r) => r.data),
    placeholderData: (previous) => previous,
  });
}

export function useProject(id: string) {
  return useQuery({
    queryKey: projectKeys.detail(id),
    queryFn: ({ signal }) => apiRequest(path(id), projectDetailSchema, { signal }).then((r) => r.data),
  });
}

export function useBoq(id: string) {
  return useQuery({
    queryKey: projectKeys.boq(id),
    queryFn: ({ signal }) => apiRequest(`${path(id)}/boq`, boqSchema, { signal }).then((r) => r.data),
  });
}

export interface ProjectInput {
  code?: string;
  site_id?: string;
  name: string;
  client_name: string;
  project_type: ProjectType;
  status: ProjectStatus;
  contract_value: string;
  start_date: string;
  planned_end: string;
  description: string | null;
}

export function useSaveProject(id?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ProjectInput) =>
      apiRequest(id ? path(id) : "/projects", projectDetailSchema, { method: id ? "PATCH" : "POST", body }).then(
        (r) => r.data,
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: projectKeys.all }),
  });
}

export function useImportBoq(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, dryRun }: { file: File; dryRun: boolean }) => {
      const form = new FormData();
      form.append("file", file);
      return apiRequest(`${path(id)}/boq/import?dry_run=${String(dryRun)}`, importReportSchema, {
        method: "POST",
        body: form,
        timeoutMs: 60_000,
      }).then((r) => r.data);
    },
    onSuccess: (report) => {
      if (report.imported) void queryClient.invalidateQueries({ queryKey: projectKeys.all });
    },
  });
}

export function useUpdateBudgetLine(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ lineId, amount }: { lineId: string; amount: string }) =>
      apiRequest(`${path(projectId)}/budget-lines/${encodeURIComponent(lineId)}`, sectionTotalsSchema, {
        method: "PATCH",
        body: { budget_amount: amount },
      }).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: projectKeys.all }),
  });
}
