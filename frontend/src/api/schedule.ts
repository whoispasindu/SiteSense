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
  is_critical: z.boolean(), // on the forecast critical path (Phase 9: calculated)
  is_concrete_pour: z.boolean(), // BR-06
  stopped: z.boolean(), // BR-11
  actual_start: z.iso.date().nullable(),
  actual_finish: z.iso.date().nullable(),
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
  network: (projectId: string) => ["projects", projectId, "network"] as const,
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
  is_concrete_pour?: boolean;
}

/** Any task change moves the curve: refresh tasks, progress and the portfolio summary together. */
function useInvalidateSchedule(projectId: string) {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: scheduleKeys.tasks(projectId) }),
      queryClient.invalidateQueries({ queryKey: scheduleKeys.progress(projectId) }),
      queryClient.invalidateQueries({ queryKey: scheduleKeys.network(projectId) }),
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

// --- Phase 9: the network (critical path and forecast) and dependencies ------------------------------

const timingSchema = z.object({
  task_id: z.uuid(),
  code: z.string().nullable(),
  name: z.string(),
  percent_complete: decimal,
  planned_start: z.iso.date(),
  planned_end: z.iso.date(),
  planned_duration: z.number().int(),
  forecast_start: z.iso.date(),
  forecast_finish: z.iso.date(),
  slip_days: z.number().int(),
  total_float: z.number().int(),
  is_critical: z.boolean(),
  is_done: z.boolean(),
  stopped: z.boolean(),
  stopped_days: z.number().int(),
  is_concrete_pour: z.boolean(),
  rain_days: z.array(z.iso.date()),
  predecessors: z.array(z.uuid()),
});
export type TaskTiming = z.infer<typeof timingSchema>;

const dependencySchema = z.object({ id: z.uuid(), predecessor_id: z.uuid(), successor_id: z.uuid(), lag_days: z.number().int() });
export type Dependency = z.infer<typeof dependencySchema>;

const networkSchema = z.object({
  project_id: z.uuid(),
  as_of: z.iso.date(),
  working_week: z.string(),
  planned_end: z.iso.date(),
  network_end: z.iso.date().nullable(),
  forecast_end: z.iso.date().nullable(),
  slip_days: z.number().int(),
  tasks: z.array(timingSchema),
  dependencies: z.array(dependencySchema),
  stop_work: z.array(
    z.object({
      action_id: z.uuid(),
      report_id: z.uuid(),
      summary: z.string(),
      scope: z.enum(["tasks", "project"]),
      task_ids: z.array(z.uuid()),
      since: z.iso.datetime({ offset: true }),
    }),
  ),
  warnings: z.array(z.string()),
});
export type Network = z.infer<typeof networkSchema>;

export function useNetwork(projectId: string) {
  return useQuery({
    queryKey: scheduleKeys.network(projectId),
    queryFn: ({ signal }) => apiRequest(`${projectPath(projectId)}/network`, networkSchema, { signal }).then((r) => r.data),
  });
}

export function useAddDependency(projectId: string) {
  const invalidate = useInvalidateSchedule(projectId);
  return useMutation({
    mutationFn: (body: { predecessor_id: string; successor_id: string; lag_days: number }) =>
      apiRequest(`${projectPath(projectId)}/dependencies`, dependencySchema, { method: "POST", body }).then((r) => r.data),
    onSuccess: invalidate,
  });
}

export function useRemoveDependency(projectId: string) {
  const invalidate = useInvalidateSchedule(projectId);
  return useMutation({
    mutationFn: (id: string) =>
      apiRequest(`/dependencies/${encodeURIComponent(id)}`, z.null(), { method: "DELETE" }).then(() => undefined),
    onSuccess: invalidate,
  });
}

// --- Holidays (Company Admin) ----------------------------------------------------------------------

const holidaySchema = z.object({ id: z.uuid(), holiday_date: z.iso.date(), name: z.string() });
export type Holiday = z.infer<typeof holidaySchema>;
const holidayListSchema = z.object({
  holidays: z.array(holidaySchema),
  years: z.array(z.number().int()),
  missing_next_year: z.boolean(),
});

export const holidayKeys = { all: ["admin", "holidays"] as const };

export function useHolidays() {
  return useQuery({
    queryKey: holidayKeys.all,
    queryFn: ({ signal }) => apiRequest("/admin/holidays", holidayListSchema, { signal }).then((r) => r.data),
  });
}

export function useAddHoliday() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { holiday_date: string; name: string }) =>
      apiRequest("/admin/holidays", holidaySchema, { method: "POST", body }).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: holidayKeys.all }),
  });
}

export function useRemoveHoliday() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      apiRequest(`/admin/holidays/${encodeURIComponent(id)}`, z.null(), { method: "DELETE" }).then(() => undefined),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: holidayKeys.all }),
  });
}
