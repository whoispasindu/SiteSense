import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { apiRequest } from "./client";
import { projectKeys, projectSummarySchema } from "./projects";

const decimal = z.string().regex(/^-?\d+(\.\d+)?$/, "Expected a decimal string");

export const TASK_STATES = ["not_started", "on_track", "behind", "done"] as const;
export type TaskState = (typeof TASK_STATES)[number];

export const taskSchema = z.object({
  id: z.uuid(),
  project_id: z.uuid(),
  code: z.string().nullable(),
  name: z.string(),
  boq_section_id: z.uuid().nullable(),
  boq_section_code: z.string().nullable(),
  planned_start: z.iso.date(),
  planned_end: z.iso.date(),
  weight: decimal,
  percent_complete: decimal,
  is_critical: z.boolean(),
  position: z.number().int(),
  planned_percent_today: z.number(),
  state: z.enum(TASK_STATES),
  progress_updated_at: z.iso.datetime({ offset: true }).nullable(),
});
export type Task = z.infer<typeof taskSchema>;

const taskListSchema = z.object({ tasks: z.array(taskSchema), weight_total: decimal });

export const progressSchema = z.object({
  as_of: z.iso.date(),
  planned_percent: z.number(),
  actual_percent: z.number(),
  variance: z.number(),
  weight_total: decimal,
  task_count: z.number().int(),
  programme_start: z.iso.date(),
  programme_end: z.iso.date(),
  contract_end: z.iso.date(),
  points: z.array(z.object({ date: z.iso.date(), planned: z.number(), actual: z.number().nullable() })),
});
export type Progress = z.infer<typeof progressSchema>;

const summarySchema = z.array(
  z.object({
    project: projectSummarySchema,
    planned_percent: z.number(),
    actual_percent: z.number(),
    variance: z.number(),
    task_count: z.number().int(),
  }),
);
export type ScheduleSummary = z.infer<typeof summarySchema>[number];

export const scheduleKeys = {
  summary: ["schedule", "summary"] as const,
  tasks: (projectId: string) => ["projects", projectId, "tasks"] as const,
  progress: (projectId: string) => ["projects", projectId, "progress"] as const,
};

const projectPath = (id: string) => `/projects/${encodeURIComponent(id)}`;
const taskPath = (id: string) => `/tasks/${encodeURIComponent(id)}`;

export function useScheduleSummary() {
  return useQuery({
    queryKey: scheduleKeys.summary,
    queryFn: ({ signal }) => apiRequest("/schedule/summary", summarySchema, { signal }).then((r) => r.data),
  });
}

export function useTasks(projectId: string) {
  return useQuery({
    queryKey: scheduleKeys.tasks(projectId),
    queryFn: ({ signal }) => apiRequest(`${projectPath(projectId)}/tasks`, taskListSchema, { signal }).then((r) => r.data),
  });
}

export function useProgress(projectId: string) {
  return useQuery({
    queryKey: scheduleKeys.progress(projectId),
    queryFn: ({ signal }) => apiRequest(`${projectPath(projectId)}/progress`, progressSchema, { signal }).then((r) => r.data),
  });
}

export interface TaskInput {
  code?: string | null;
  name?: string;
  boq_section_id?: string | null;
  planned_start?: string;
  planned_end?: string;
  weight?: string;
  percent_complete?: string;
  is_critical?: boolean;
}

/** Any task change moves the curve: refresh tasks, progress and the portfolio summary together. */
function useInvalidateSchedule(projectId: string) {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: scheduleKeys.tasks(projectId) }),
      queryClient.invalidateQueries({ queryKey: scheduleKeys.progress(projectId) }),
      queryClient.invalidateQueries({ queryKey: scheduleKeys.summary }),
      queryClient.invalidateQueries({ queryKey: projectKeys.detail(projectId) }),
    ]);
}

export function useCreateTask(projectId: string) {
  const invalidate = useInvalidateSchedule(projectId);
  return useMutation({
    mutationFn: (body: TaskInput) =>
      apiRequest(`${projectPath(projectId)}/tasks`, taskSchema, { method: "POST", body }).then((r) => r.data),
    onSuccess: invalidate,
  });
}

export function useUpdateTask(projectId: string) {
  const invalidate = useInvalidateSchedule(projectId);
  return useMutation({
    mutationFn: ({ id, ...body }: TaskInput & { id: string }) =>
      apiRequest(taskPath(id), taskSchema, { method: "PATCH", body }).then((r) => r.data),
    onSuccess: invalidate,
  });
}

export function useDeleteTask(projectId: string) {
  const invalidate = useInvalidateSchedule(projectId);
  return useMutation({
    mutationFn: (id: string) => apiRequest(taskPath(id), z.null(), { method: "DELETE" }).then(() => undefined),
    onSuccess: invalidate,
  });
}
