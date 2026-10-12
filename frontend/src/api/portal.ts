import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { apiBlob, apiRequest } from "./client";
import { blobToDataUrl } from "../lib/files";
import { dashboardKeys, reminderSchema } from "./dashboard";

const decimal = z.string().regex(/^-?\d+(\.\d+)?$/, "Expected a decimal string");
const timestamp = z.iso.datetime({ offset: true });

// --- The client's portal (Phase 12) --------------------------------------------------------------------

export const MILESTONE_STATUSES = ["done", "on_track", "late", "not_started"] as const;
export type MilestoneStatus = (typeof MILESTONE_STATUSES)[number];

const cardSchema = z.object({
  id: z.uuid(),
  code: z.string(),
  name: z.string(),
  location: z.string(),
  status: z.string(),
  planned_percent: z.number(),
  actual_percent: z.number(),
  handover_date: z.iso.date(),
  handover_published: z.boolean(),
  variations_waiting: z.number().int(),
});
export type ClientProjectCard = z.infer<typeof cardSchema>;

const clientProjectSchema = cardSchema.extend({
  start_date: z.iso.date(),
  handover: z.object({
    contract_end: z.iso.date(),
    published_date: z.iso.date().nullable(),
    reason: z.string().nullable(),
    published_at: timestamp.nullable(),
    history: z.array(z.object({ handover_date: z.iso.date(), reason: z.string(), published_at: timestamp })),
  }),
  progress: z.array(z.object({ date: z.iso.date(), planned: z.number(), actual: z.number().nullable() })),
  milestones: z.array(
    z.object({
      name: z.string(),
      planned_date: z.iso.date(),
      expected_date: z.iso.date(),
      completed_on: z.iso.date().nullable(),
      percent_complete: z.number(),
      status: z.enum(MILESTONE_STATUSES),
    }),
  ),
  photos: z.array(
    z.object({ id: z.uuid(), caption: z.string().nullable(), taken_on: z.iso.date(), width: z.number().int(), height: z.number().int() }),
  ),
});
export type ClientProject = z.infer<typeof clientProjectSchema>;
export type ClientPhoto = ClientProject["photos"][number];

const claimsSchema = z.object({
  project_id: z.uuid(),
  original_contract_value: decimal,
  approved_variations: decimal,
  contract_value: decimal,
  claimed_to_date: decimal,
  paid_to_date: decimal,
  retention_held: decimal,
  retention_note: z.string(),
  claims: z.array(
    z.object({
      number: z.string(),
      status: z.enum(["approved", "paid"]),
      certified_pct: decimal,
      certified_value: decimal,
      retention: decimal,
      previous_claims: decimal,
      amount: decimal,
      approved_on: z.iso.date(),
      paid_on: z.iso.date().nullable(),
    }),
  ),
});
export type ClientClaims = z.infer<typeof claimsSchema>;

export const portalKeys = {
  projects: ["client", "projects"] as const,
  project: (id: string) => ["client", "projects", id] as const,
  claims: (id: string) => ["client", "projects", id, "claims"] as const,
  photo: (id: string, size: "full" | "thumb") => ["client", "photos", id, size] as const,
  handover: (projectId: string) => ["projects", projectId, "handover"] as const,
  photos: (projectId: string) => ["projects", projectId, "photos"] as const,
};

export function useClientProjects() {
  return useQuery({
    queryKey: portalKeys.projects,
    queryFn: ({ signal }) => apiRequest("/client/projects", z.array(cardSchema), { signal }).then((r) => r.data),
  });
}

export function useClientProject(id: string) {
  return useQuery({
    queryKey: portalKeys.project(id),
    queryFn: ({ signal }) => apiRequest(`/client/projects/${encodeURIComponent(id)}`, clientProjectSchema, { signal }).then((r) => r.data),
  });
}

export function useClientClaims(id: string) {
  return useQuery({
    queryKey: portalKeys.claims(id),
    queryFn: ({ signal }) => apiRequest(`/client/projects/${encodeURIComponent(id)}/claims`, claimsSchema, { signal }).then((r) => r.data),
  });
}

/** A shared photo as a data: URL (never a public link; fetched with the client's session). */
export function useClientPhoto(id: string, size: "full" | "thumb", enabled = true) {
  return useQuery({
    queryKey: portalKeys.photo(id, size),
    queryFn: ({ signal }) =>
      apiBlob(`/client/photos/${encodeURIComponent(id)}?size=${size}`, { signal, what: "the photo" }).then(blobToDataUrl),
    enabled,
    staleTime: 10 * 60_000,
  });
}

// --- The project manager's side --------------------------------------------------------------------------

const entrySchema = z.object({
  kind: z.enum(["published", "confirmed"]),
  handover_date: z.iso.date(),
  reason: z.string(),
  programme_forecast: z.iso.date().nullable(),
  published_by: z.string(),
  published_at: timestamp,
});
export type HandoverEntry = z.infer<typeof entrySchema>;

const handoverSchema = z.object({
  project_id: z.uuid(),
  current: entrySchema.nullable(),
  published: entrySchema.nullable(),
  history: z.array(entrySchema),
  suggestions: z.object({
    contract_end: z.iso.date(),
    programme_forecast: z.iso.date().nullable(),
    risk_range: z.object({ start: z.iso.date(), end: z.iso.date() }).nullable(),
  }),
  reminder: reminderSchema.nullable(),
  can_publish: z.boolean(),
});
export type HandoverState = z.infer<typeof handoverSchema>;

const photosSchema = z.object({
  items: z.array(
    z.object({
      id: z.uuid(),
      report_id: z.uuid(),
      report_date: z.iso.date(),
      caption: z.string().nullable(),
      width: z.number().int(),
      height: z.number().int(),
      shared_with_client: z.boolean(),
      shared_at: timestamp.nullable(),
    }),
  ),
  total: z.number().int(),
  shared: z.number().int(),
});
export type ProjectPhotos = z.infer<typeof photosSchema>;

export function useHandover(projectId: string) {
  return useQuery({
    queryKey: portalKeys.handover(projectId),
    queryFn: ({ signal }) => apiRequest(`/projects/${encodeURIComponent(projectId)}/handover`, handoverSchema, { signal }).then((r) => r.data),
  });
}

function useHandoverMutation<T>(projectId: string, send: (body: T) => Promise<HandoverState>) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: send,
    onSuccess: (data) => {
      queryClient.setQueryData(portalKeys.handover(projectId), data);
      void queryClient.invalidateQueries({ queryKey: dashboardKeys.portfolio });
    },
  });
}

export function usePublishHandover(projectId: string) {
  return useHandoverMutation(projectId, (body: { handover_date: string; reason: string }) =>
    apiRequest(`/projects/${encodeURIComponent(projectId)}/handover`, handoverSchema, { method: "POST", body }).then((r) => r.data),
  );
}

export function useConfirmHandover(projectId: string) {
  return useHandoverMutation(projectId, () =>
    apiRequest(`/projects/${encodeURIComponent(projectId)}/handover/confirm`, handoverSchema, { method: "POST" }).then((r) => r.data),
  );
}

export function useProjectPhotos(projectId: string) {
  return useQuery({
    queryKey: portalKeys.photos(projectId),
    queryFn: ({ signal }) => apiRequest(`/projects/${encodeURIComponent(projectId)}/photos`, photosSchema, { signal }).then((r) => r.data),
  });
}

export function useSharePhotos(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { photo_ids: string[]; shared: boolean }) =>
      apiRequest(`/projects/${encodeURIComponent(projectId)}/photos/client-share`, photosSchema, { method: "POST", body }).then((r) => r.data),
    onSuccess: (data) => {
      queryClient.setQueryData(portalKeys.photos(projectId), data);
    },
  });
}
