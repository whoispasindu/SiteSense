import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { apiRequest } from "./client";
import { materialKeys } from "./materials";
import { notificationKeys } from "./notifications";
import { projectKeys } from "./projects";

/**
 * Phase 8: progress claims (BR-08), variation orders (BR-09), the client's view of variations, the
 * Company Admin's BR-09 limit, and the cost & claims overview.
 */

const decimal = z.string().regex(/^-?\d+(\.\d+)?$/, "Expected a decimal string");
const timestamp = z.iso.datetime({ offset: true });

// --- Claims ---------------------------------------------------------------------------------------------

export const CLAIM_STATUSES = ["submitted", "approved", "returned", "paid"] as const;
export type ClaimStatus = (typeof CLAIM_STATUSES)[number];
export const CLAIM_STATUS_LABELS: Record<ClaimStatus, string> = {
  submitted: "Waiting for the PM",
  approved: "Approved, unpaid",
  returned: "Returned",
  paid: "Paid",
};

const claimSectionSchema = z.object({
  section_id: z.uuid(),
  code: z.string(),
  name: z.string(),
  section_value: decimal,
  previous_pct: decimal,
  certified_pct: decimal.nullable().optional(),
});
export type ClaimSection = z.infer<typeof claimSectionSchema>;

const figuresSchema = z.object({
  contract_value: decimal,
  certified_pct: decimal,
  certified_value: decimal,
  retention: decimal,
  retention_rate: decimal,
  previous_claims: decimal,
  amount: decimal,
});
export type ClaimFigures = z.infer<typeof figuresSchema>;

const ruleSchema = z.object({ rule: z.string(), severity: z.string(), message: z.string(), facts: z.record(z.string(), z.string()) });

const claimSchema = z.object({
  id: z.uuid(),
  number: z.string(),
  project_id: z.uuid(),
  status: z.enum(CLAIM_STATUSES),
  figures: figuresSchema,
  notes: z.string().nullable(),
  submitted_by: z.string(),
  submitted_at: timestamp,
  decided_by: z.string().nullable(),
  decided_at: timestamp.nullable(),
  decision_comment: z.string().nullable(),
  paid_on: z.iso.date().nullable(),
  lines: z.array(claimSectionSchema),
  actions: z.array(z.enum(["approve", "return", "record_payment"])),
});
export type Claim = z.infer<typeof claimSchema>;

const claimsOverviewSchema = z.object({
  claims: z.array(claimSchema),
  sections: z.array(claimSectionSchema),
  claimed_to_date: decimal,
  retention_held: decimal,
  paid_to_date: decimal,
  can_create: z.boolean(),
});
export type ClaimsOverview = z.infer<typeof claimsOverviewSchema>;

const claimCheckSchema = z.object({ figures: figuresSchema, problems: z.array(ruleSchema) });
export type ClaimCheck = z.infer<typeof claimCheckSchema>;

export interface ClaimInput {
  sections: { section_id: string; certified_pct: string }[];
  notes?: string | null;
}

// --- Variations -----------------------------------------------------------------------------------------

export const VARIATION_STATUSES = [
  "awaiting_pricing",
  "awaiting_pm",
  "awaiting_client",
  "queried",
  "approved",
  "rejected",
  "withdrawn",
] as const;
export type VariationStatus = (typeof VARIATION_STATUSES)[number];
export const VARIATION_STATUS_LABELS: Record<VariationStatus, string> = {
  awaiting_pricing: "To be priced",
  awaiting_pm: "Waiting for the PM",
  awaiting_client: "Waiting for the client",
  queried: "Queried",
  approved: "Approved",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};
/** The client's own words for the same states. */
export const CLIENT_STATUS_LABELS: Record<VariationStatus, string> = {
  awaiting_pricing: "Being revised by the contractor",
  awaiting_pm: "Being revised by the contractor",
  awaiting_client: "Waiting for your decision",
  queried: "You asked a question",
  approved: "Approved",
  rejected: "Closed",
  withdrawn: "Withdrawn by the contractor",
};

const eventSchema = z.object({
  action: z.enum(["raised", "priced", "revised", "approved", "queried", "rejected", "withdrawn"]),
  actor: z.string(),
  from_status: z.string().nullable(),
  to_status: z.string(),
  comment: z.string().nullable(),
  at: timestamp,
});
export type VariationEvent = z.infer<typeof eventSchema>;

export const VARIATION_ACTIONS = ["price", "revise", "approve", "query", "reject", "withdraw"] as const;
export type VariationAction = (typeof VARIATION_ACTIONS)[number];

const variationSchema = z.object({
  id: z.uuid(),
  number: z.string(),
  project_id: z.uuid(),
  project_code: z.string(),
  title: z.string(),
  description: z.string(),
  section_id: z.uuid(),
  section: z.string(),
  boq_item_id: z.uuid().nullable(),
  boq_item: z.string().nullable(),
  quantity_change: decimal.nullable(),
  task_id: z.uuid().nullable(),
  task: z.string().nullable(),
  time_impact_days: z.number().int().min(0),
  contract_change: decimal.nullable(),
  budget_change: decimal.nullable(),
  status: z.enum(VARIATION_STATUSES),
  approver: z.enum(["pm", "client"]).nullable(),
  limit: decimal,
  limit_applied: decimal.nullable(),
  needs_client: z.boolean().nullable(),
  raised_by: z.string(),
  raised_by_role: z.enum(["pm", "qs"]),
  raised_at: timestamp,
  priced_by: z.string().nullable(),
  decided_at: timestamp.nullable(),
  events: z.array(eventSchema),
  actions: z.array(z.enum(VARIATION_ACTIONS)),
});
export type Variation = z.infer<typeof variationSchema>;

const variationListSchema = z.object({
  variations: z.array(variationSchema),
  limit: decimal,
  approved_contract_change: decimal,
  approved_time_impact_days: z.number().int(),
});
export type VariationList = z.infer<typeof variationListSchema>;

const clientVariationSchema = z.object({
  id: z.uuid(),
  number: z.string(),
  project_id: z.uuid(),
  project_code: z.string(),
  project_name: z.string(),
  title: z.string(),
  description: z.string(),
  contract_change: decimal.nullable(),
  time_impact_days: z.number().int().min(0),
  status: z.enum(VARIATION_STATUSES),
  limit: decimal,
  reason_for_client: z.string(),
  raised_at: timestamp,
  events: z.array(eventSchema),
  can_decide: z.boolean(),
});
export type ClientVariation = z.infer<typeof clientVariationSchema>;

export interface VariationInput {
  title: string;
  description: string;
  section_id: string;
  boq_item_id?: string | null;
  quantity_change?: string | null;
  task_id?: string | null;
  time_impact_days: number;
  contract_change?: string | null;
  budget_change?: string | null;
  comment?: string | null;
}

// --- Overview and admin ---------------------------------------------------------------------------------

const projectCostSchema = z.object({
  project_id: z.uuid(),
  code: z.string(),
  name: z.string(),
  status: z.string(),
  contract_value: decimal,
  approved_variations: decimal,
  budget: decimal,
  committed: decimal,
  forecast_final: decimal,
  variance: decimal,
  variance_pct: decimal.nullable(),
  sections_over: z.number().int().min(0),
  claimed_to_date: decimal,
  open_claim: z.string().nullable(),
  variations_open: z.number().int().min(0),
});
export type ProjectCost = z.infer<typeof projectCostSchema>;

const waitingSchema = z.object({
  kind: z.enum(["claim", "variation"]),
  id: z.uuid(),
  number: z.string(),
  project_id: z.uuid(),
  project_code: z.string(),
  title: z.string(),
  status: z.string(),
  since: timestamp,
});
export type WaitingItem = z.infer<typeof waitingSchema>;

const costOverviewSchema = z.object({ projects: z.array(projectCostSchema), waiting_for_you: z.array(waitingSchema) });

const projectLimitSchema = z.object({
  project_id: z.uuid(),
  code: z.string(),
  name: z.string(),
  site_code: z.string(),
  status: z.string(),
  variation_limit: decimal,
});
export type ProjectLimit = z.infer<typeof projectLimitSchema>;

// --- Queries --------------------------------------------------------------------------------------------

export const contractKeys = {
  overview: ["cost", "overview"] as const,
  claims: (projectId: string) => ["projects", projectId, "claims"] as const,
  variations: (projectId: string) => ["projects", projectId, "variations"] as const,
  variation: (id: string) => ["variations", id] as const,
  client: ["client", "variations"] as const,
  clientVariation: (id: string) => ["client", "variations", id] as const,
  limits: ["admin", "variation-limits"] as const,
};

const enc = encodeURIComponent;

export function useCostOverview() {
  return useQuery({
    queryKey: contractKeys.overview,
    queryFn: ({ signal }) => apiRequest("/cost/overview", costOverviewSchema, { signal }).then((r) => r.data),
  });
}

export function useClaims(projectId: string) {
  return useQuery({
    queryKey: contractKeys.claims(projectId),
    queryFn: ({ signal }) => apiRequest(`/projects/${enc(projectId)}/claims`, claimsOverviewSchema, { signal }).then((r) => r.data),
  });
}

export function checkClaim(projectId: string, body: ClaimInput, signal?: AbortSignal): Promise<ClaimCheck> {
  return apiRequest(`/projects/${enc(projectId)}/claims/check`, claimCheckSchema, {
    method: "POST",
    body,
    ...(signal ? { signal } : {}),
  }).then((r) => r.data);
}

export function useVariations(projectId: string) {
  return useQuery({
    queryKey: contractKeys.variations(projectId),
    queryFn: ({ signal }) => apiRequest(`/projects/${enc(projectId)}/variations`, variationListSchema, { signal }).then((r) => r.data),
  });
}

export function useVariation(id: string) {
  return useQuery({
    queryKey: contractKeys.variation(id),
    queryFn: ({ signal }) => apiRequest(`/variations/${enc(id)}`, variationSchema, { signal }).then((r) => r.data),
  });
}

export function useClientVariations() {
  return useQuery({
    queryKey: contractKeys.client,
    queryFn: ({ signal }) => apiRequest("/client/variations", z.array(clientVariationSchema), { signal }).then((r) => r.data),
  });
}

export function useClientVariation(id: string) {
  return useQuery({
    queryKey: contractKeys.clientVariation(id),
    queryFn: ({ signal }) => apiRequest(`/client/variations/${enc(id)}`, clientVariationSchema, { signal }).then((r) => r.data),
  });
}

export function useVariationLimits() {
  return useQuery({
    queryKey: contractKeys.limits,
    queryFn: ({ signal }) => apiRequest("/admin/variation-limits", z.array(projectLimitSchema), { signal }).then((r) => r.data),
  });
}

// --- Mutations ------------------------------------------------------------------------------------------

/** Claims and variations move the contract value, budget, risk, the overview and notifications. */
function useInvalidateContract() {
  const queryClient = useQueryClient();
  return (projectId: string) =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: contractKeys.overview }),
      queryClient.invalidateQueries({ queryKey: contractKeys.claims(projectId) }),
      queryClient.invalidateQueries({ queryKey: contractKeys.variations(projectId) }),
      queryClient.invalidateQueries({ queryKey: ["variations"] }),
      queryClient.invalidateQueries({ queryKey: ["client"] }),
      queryClient.invalidateQueries({ queryKey: materialKeys.budget(projectId) }),
      queryClient.invalidateQueries({ queryKey: projectKeys.all }),
      queryClient.invalidateQueries({ queryKey: ["risk"] }),
      queryClient.invalidateQueries({ queryKey: notificationKeys.all }),
    ]);
}

export function useCreateClaim(projectId: string) {
  const invalidate = useInvalidateContract();
  return useMutation({
    mutationFn: (body: ClaimInput) =>
      apiRequest(`/projects/${enc(projectId)}/claims`, claimSchema, { method: "POST", body }).then((r) => r.data),
    onSuccess: () => invalidate(projectId),
  });
}

export function useDecideClaim(projectId: string) {
  const invalidate = useInvalidateContract();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; decision: "approve" | "return"; comment?: string | null }) =>
      apiRequest(`/claims/${enc(id)}/decision`, claimSchema, { method: "POST", body }).then((r) => r.data),
    onSuccess: () => invalidate(projectId),
  });
}

export function useRecordPayment(projectId: string) {
  const invalidate = useInvalidateContract();
  return useMutation({
    mutationFn: ({ id, paid_on }: { id: string; paid_on: string }) =>
      apiRequest(`/claims/${enc(id)}/payment`, claimSchema, { method: "POST", body: { paid_on } }).then((r) => r.data),
    onSuccess: () => invalidate(projectId),
  });
}

export function useRaiseVariation(projectId: string) {
  const invalidate = useInvalidateContract();
  return useMutation({
    mutationFn: (body: VariationInput) =>
      apiRequest(`/projects/${enc(projectId)}/variations`, variationSchema, { method: "POST", body }).then((r) => r.data),
    onSuccess: () => invalidate(projectId),
  });
}

export type VariationStep =
  | { step: "price"; contract_change: string; budget_change: string; comment?: string | null }
  | { step: "decision"; decision: "approve" | "query" | "reject"; comment?: string | null }
  | { step: "withdraw"; comment?: string | null }
  | ({ step: "revision" } & VariationInput);

export function useVariationStep(variation: { id: string; project_id: string }) {
  const invalidate = useInvalidateContract();
  return useMutation({
    mutationFn: ({ step, ...body }: VariationStep) =>
      apiRequest(`/variations/${enc(variation.id)}/${step}`, variationSchema, { method: "POST", body }).then((r) => r.data),
    onSuccess: () => invalidate(variation.project_id),
  });
}

export function useClientDecision(variation: { id: string; project_id: string }) {
  const invalidate = useInvalidateContract();
  return useMutation({
    mutationFn: (body: { decision: "approve" | "query"; comment?: string | null }) =>
      apiRequest(`/variations/${enc(variation.id)}/client-decision`, clientVariationSchema, { method: "POST", body }).then(
        (r) => r.data,
      ),
    onSuccess: () => invalidate(variation.project_id),
  });
}

export function useSetVariationLimit() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ projectId, ...body }: { projectId: string; variation_limit: string; reason: string }) =>
      apiRequest(`/admin/projects/${enc(projectId)}/variation-limit`, projectLimitSchema, { method: "PUT", body }).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: contractKeys.limits }),
  });
}
