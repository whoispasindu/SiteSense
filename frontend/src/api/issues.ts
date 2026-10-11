import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { apiRequest } from "./client";
import { materialKeys } from "./materials";
import { notificationKeys } from "./notifications";
import { riskKeys } from "./risk";

export const ISSUE_CATEGORIES = ["material_delay", "labour", "weather", "equipment", "safety", "design", "quality", "other"] as const;
export type IssueCategory = (typeof ISSUE_CATEGORIES)[number];
export const SEVERITIES = ["low", "medium", "high"] as const;
export type IssueSeverity = (typeof SEVERITIES)[number];

export const CATEGORY_LABELS: Record<IssueCategory, string> = {
  material_delay: "Material delay",
  labour: "Labour",
  weather: "Weather",
  equipment: "Equipment",
  safety: "Safety",
  design: "Design or drawing",
  quality: "Quality",
  other: "Other",
};
export const SEVERITY_LABELS: Record<IssueSeverity, string> = { low: "Low", medium: "Medium", high: "High" };

const issueSchema = z.object({
  id: z.uuid(),
  snippet: z.string(),
  category: z.enum(ISSUE_CATEGORIES),
  severity: z.enum(SEVERITIES),
  status: z.enum(["suggested", "confirmed", "removed"]),
  source: z.enum(["ai", "manual"]),
  confidence: z.number().min(0).max(1).nullable(),
  low_confidence: z.boolean(),
  ai_category: z.enum(ISSUE_CATEGORIES).nullable(),
  ai_severity: z.enum(SEVERITIES).nullable(),
  edited: z.boolean(),
  confirmed_at: z.iso.datetime({ offset: true }).nullable(),
});
export type Issue = z.infer<typeof issueSchema>;

export const ACTION_KINDS = ["material_request", "pm_alert", "stop_work"] as const;
export type ActionKind = (typeof ACTION_KINDS)[number];

const actionSchema = z.object({
  id: z.uuid(),
  report_id: z.uuid(),
  kind: z.enum(ACTION_KINDS),
  status: z.enum(["open", "done", "dismissed"]),
  summary: z.string(),
  created_at: z.iso.datetime({ offset: true }),
  closed_at: z.iso.datetime({ offset: true }).nullable(),
  request_id: z.uuid().nullable(),
  can_close: z.boolean(),
  // BR-11 (Phase 9): what a stop-work flag stops.
  stop_scope: z.enum(["tasks", "project"]).nullable(),
  stop_task_ids: z.array(z.uuid()),
  can_edit_scope: z.boolean(),
});
export type ReportAction = z.infer<typeof actionSchema>;
export type StopScope = "tasks" | "project";

const reportIssuesSchema = z.object({
  report_id: z.uuid(),
  confirmed: z.boolean(),
  can_confirm: z.boolean(),
  model_version: z.string().nullable(),
  low_confidence_below: z.number(),
  issues: z.array(issueSchema),
  actions: z.array(actionSchema),
});
export type ReportIssues = z.infer<typeof reportIssuesSchema>;

export interface ConfirmInput {
  issues: { suggestion_id?: string; category: IssueCategory; severity: IssueSeverity; snippet?: string }[];
  actions: {
    material_request: boolean;
    pm_alert: boolean;
    stop_work: boolean;
    stop_work_scope?: StopScope;
    stop_work_task_ids?: string[];
  };
}

export const issueKeys = {
  report: (reportId: string) => ["reports", reportId, "issues"] as const,
  projectActions: (projectId: string) => ["projects", projectId, "report-actions"] as const,
};

const path = (reportId: string) => `/reports/${encodeURIComponent(reportId)}`;

export function useReportIssues(reportId: string) {
  return useQuery({
    queryKey: issueKeys.report(reportId),
    queryFn: ({ signal }) => apiRequest(`${path(reportId)}/issues`, reportIssuesSchema, { signal }).then((r) => r.data),
  });
}

export function useAnalyze(reportId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest(`${path(reportId)}/analyze`, reportIssuesSchema, { method: "POST" }).then((r) => r.data),
    onSuccess: (data) => {
      queryClient.setQueryData(issueKeys.report(reportId), data);
    },
  });
}

export function useConfirmIssues(reportId: string, projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ConfirmInput) =>
      apiRequest(`${path(reportId)}/issues/confirm`, reportIssuesSchema, { method: "POST", body }).then((r) => r.data),
    onSuccess: (data) => {
      queryClient.setQueryData(issueKeys.report(reportId), data);
      // Confirmed issues feed the risk score and may notify the project managers.
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: issueKeys.projectActions(projectId) }),
        queryClient.invalidateQueries({ queryKey: ["projects", projectId, "network"] }),
        queryClient.invalidateQueries({ queryKey: ["projects", projectId, "tasks"] }),
        queryClient.invalidateQueries({ queryKey: riskKeys.project(projectId) }),
        queryClient.invalidateQueries({ queryKey: riskKeys.ranking }),
        queryClient.invalidateQueries({ queryKey: notificationKeys.all }),
      ]);
    },
  });
}

export function useProjectActions(projectId: string, enabled = true) {
  return useQuery({
    queryKey: issueKeys.projectActions(projectId),
    queryFn: ({ signal }) =>
      apiRequest(`/projects/${encodeURIComponent(projectId)}/report-actions`, z.array(actionSchema), { signal }).then((r) => r.data),
    enabled,
  });
}

export function useCloseAction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, resolution }: { id: string; resolution: "done" | "dismissed" }) =>
      apiRequest(`/report-actions/${encodeURIComponent(id)}/close`, actionSchema, { method: "POST", body: { resolution } }).then(
        (r) => r.data,
      ),
    onSuccess: (action) =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: issueKeys.report(action.report_id) }),
        queryClient.invalidateQueries({ queryKey: ["projects"] }),
        queryClient.invalidateQueries({ queryKey: materialKeys.all }),
      ]),
  });
}

/** BR-11: the PM changes what an open stop-work flag stops. */
export function useSetStopScope() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; scope: StopScope; task_ids: string[] }) =>
      apiRequest(`/report-actions/${encodeURIComponent(id)}/stop-scope`, actionSchema, { method: "PUT", body }).then((r) => r.data),
    onSuccess: (action) =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: issueKeys.report(action.report_id) }),
        queryClient.invalidateQueries({ queryKey: ["projects"] }),
        queryClient.invalidateQueries({ queryKey: ["risk"] }),
      ]),
  });
}

/** Which follow-ups a set of tags allows (the API refuses the others). */
export function allowedActions(tags: { category: IssueCategory; severity: IssueSeverity }[]) {
  return {
    material_request: tags.some((t) => t.category === "material_delay"),
    pm_alert: tags.some((t) => t.severity === "high"),
    stop_work: tags.some((t) => t.category === "safety"),
  };
}
