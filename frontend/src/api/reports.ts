import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { apiBlob, apiRequest } from "./client";
import { projectKeys } from "./projects";
import { scheduleKeys } from "./schedule";
import { blobToDataUrl } from "../lib/files";

const decimal = z.string().regex(/^-?\d+(\.\d+)?$/, "Expected a decimal string");
const timestamp = z.iso.datetime({ offset: true });

export const WEATHER_SOURCES = ["forecast", "manual"] as const;
export type WeatherSource = (typeof WEATHER_SOURCES)[number];

const authorSchema = z.object({ id: z.uuid(), full_name: z.string() });

export const photoSchema = z.object({
  id: z.uuid(),
  caption: z.string().nullable(),
  width: z.number().int(),
  height: z.number().int(),
  size_bytes: z.number().int(),
  created_at: timestamp,
});
export type Photo = z.infer<typeof photoSchema>;

const reportSummarySchema = z.object({
  id: z.uuid(),
  project_id: z.uuid(),
  report_date: z.iso.date(),
  author: authorSchema,
  weather_summary: z.string().nullable(),
  rain_mm: decimal.nullable(),
  crew_count: z.number().int(),
  work_done_preview: z.string(),
  has_problems: z.boolean(),
  photo_count: z.number().int(),
  progress_count: z.number().int(),
  submitted_at: timestamp,
});
export type ReportSummary = z.infer<typeof reportSummarySchema>;

const reportListSchema = z.object({ items: z.array(reportSummarySchema), total: z.number().int() });

export const reportDetailSchema = z.object({
  id: z.uuid(),
  project_id: z.uuid(),
  project_name: z.string(),
  report_date: z.iso.date(),
  author: authorSchema,
  weather_summary: z.string().nullable(),
  temp_max_c: decimal.nullable(),
  temp_min_c: decimal.nullable(),
  rain_mm: decimal.nullable(),
  weather_source: z.enum(WEATHER_SOURCES),
  crew_count: z.number().int(),
  work_done: z.string(),
  problems: z.string().nullable(),
  submitted_at: timestamp,
  updated_at: timestamp,
  photos: z.array(photoSchema),
  progress: z.array(
    z.object({
      task_id: z.uuid().nullable(),
      task_name: z.string(),
      percent_before: decimal,
      percent_after: decimal,
    }),
  ),
  editable: z.boolean(),
  photo_limit: z.number().int(),
});
export type ReportDetail = z.infer<typeof reportDetailSchema>;

const todayStatusSchema = z.object({
  date: z.iso.date(),
  deadline: timestamp,
  deadline_passed: z.boolean(),
  projects: z.array(
    z.object({
      project_id: z.uuid(),
      project_code: z.string(),
      project_name: z.string(),
      site_code: z.string(),
      report_id: z.uuid().nullable(),
      submitted_at: timestamp.nullable(),
      author_name: z.string().nullable(),
    }),
  ),
});
export type TodayStatus = z.infer<typeof todayStatusSchema>;

export const weatherDaySchema = z.object({
  date: z.iso.date(),
  summary: z.string(),
  weather_code: z.number().int().nullable(),
  temp_max_c: decimal.nullable(),
  temp_min_c: decimal.nullable(),
  rain_mm: decimal.nullable(),
  rain_probability: z.number().int().nullable(),
});
export type WeatherDay = z.infer<typeof weatherDaySchema>;

const weatherSchema = z.object({
  site_code: z.string(),
  available: z.boolean(),
  stale: z.boolean(),
  fetched_at: timestamp.nullable(),
  message: z.string().nullable(),
  days: z.array(weatherDaySchema),
  heavy_rain_threshold_mm: decimal,
});
export type Weather = z.infer<typeof weatherSchema>;

export const reportKeys = {
  today: ["reports", "today"] as const,
  list: (projectId: string, offset: number) => ["projects", projectId, "reports", offset] as const,
  project: (projectId: string) => ["projects", projectId, "reports"] as const,
  detail: (reportId: string) => ["reports", reportId] as const,
  weather: (projectId: string) => ["projects", projectId, "weather"] as const,
  photo: (photoId: string, size: "full" | "thumb") => ["photos", photoId, size] as const,
};

export const REPORTS_PAGE_SIZE = 20;

const projectPath = (id: string) => `/projects/${encodeURIComponent(id)}`;
const reportPath = (id: string) => `/reports/${encodeURIComponent(id)}`;

export function useTodayStatus() {
  return useQuery({
    queryKey: reportKeys.today,
    queryFn: ({ signal }) => apiRequest("/reports/today", todayStatusSchema, { signal }).then((r) => r.data),
  });
}

export function useReports(projectId: string, offset = 0) {
  return useQuery({
    queryKey: reportKeys.list(projectId, offset),
    queryFn: ({ signal }) =>
      apiRequest(`${projectPath(projectId)}/reports?limit=${String(REPORTS_PAGE_SIZE)}&offset=${String(offset)}`, reportListSchema, {
        signal,
      }).then((r) => r.data),
    // Keep the old page on screen while the next loads, but never another project's reports.
    placeholderData: (previous, previousQuery) => (previousQuery?.queryKey[1] === projectId ? previous : undefined),
  });
}

export function useReport(reportId: string) {
  return useQuery({
    queryKey: reportKeys.detail(reportId),
    queryFn: ({ signal }) => apiRequest(reportPath(reportId), reportDetailSchema, { signal }).then((r) => r.data),
  });
}

export function useWeather(projectId: string) {
  return useQuery({
    queryKey: reportKeys.weather(projectId),
    queryFn: ({ signal }) => apiRequest(`${projectPath(projectId)}/weather`, weatherSchema, { signal }).then((r) => r.data),
    staleTime: 10 * 60_000,
  });
}

export interface ReportInput {
  report_date: string;
  crew_count: number;
  work_done: string;
  problems: string | null;
  weather_summary: string | null;
  temp_max_c: string | null;
  temp_min_c: string | null;
  rain_mm: string | null;
  weather_source: WeatherSource;
  progress: { task_id: string; percent_complete: string }[];
}

export type ReportPatch = Partial<Omit<ReportInput, "report_date" | "progress">>;

export function useCreateReport(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ReportInput) =>
      apiRequest(`${projectPath(projectId)}/reports`, reportDetailSchema, { method: "POST", body }).then((r) => r.data),
    onSuccess: (report) => {
      queryClient.setQueryData(reportKeys.detail(report.id), report);
      return Promise.all([
        queryClient.invalidateQueries({ queryKey: reportKeys.project(projectId) }),
        queryClient.invalidateQueries({ queryKey: reportKeys.today }),
        // Task progress in the report moves the programme.
        queryClient.invalidateQueries({ queryKey: scheduleKeys.tasks(projectId) }),
        queryClient.invalidateQueries({ queryKey: scheduleKeys.progress(projectId) }),
        queryClient.invalidateQueries({ queryKey: scheduleKeys.summary }),
        queryClient.invalidateQueries({ queryKey: projectKeys.detail(projectId) }),
      ]);
    },
  });
}

export function useUpdateReport(reportId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ReportPatch) =>
      apiRequest(reportPath(reportId), reportDetailSchema, { method: "PATCH", body }).then((r) => r.data),
    onSuccess: (report) => {
      queryClient.setQueryData(reportKeys.detail(report.id), report);
      return queryClient.invalidateQueries({ queryKey: reportKeys.project(report.project_id) });
    },
  });
}

/** Upload one photo. Not a hook so the form can upload a queue in order after creating the report. */
export function uploadPhoto(reportId: string, file: Blob, caption: string | null, name = "site-photo.jpg"): Promise<Photo> {
  const form = new FormData();
  form.append("file", file, name);
  if (caption) form.append("caption", caption);
  return apiRequest(`${reportPath(reportId)}/photos`, photoSchema, { method: "POST", body: form, timeoutMs: 60_000 }).then(
    (r) => r.data,
  );
}

export function useDeletePhoto(reportId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (photoId: string) =>
      apiRequest(`/photos/${encodeURIComponent(photoId)}`, z.null(), { method: "DELETE" }).then(() => undefined),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: reportKeys.detail(reportId) }),
  });
}

/** A stored photo as a data: URL. Fetched with the session, so photos never need a public link. */
export function usePhotoUrl(photoId: string, size: "full" | "thumb") {
  return useQuery({
    queryKey: reportKeys.photo(photoId, size),
    queryFn: async ({ signal }) =>
      blobToDataUrl(await apiBlob(`/photos/${encodeURIComponent(photoId)}?size=${size}`, { signal })),
    staleTime: 10 * 60_000,
    gcTime: 10 * 60_000,
  });
}
