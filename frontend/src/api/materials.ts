import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { apiRequest } from "./client";
import { notificationKeys } from "./notifications";

const decimal = z.string().regex(/^-?\d+(\.\d+)?$/, "Expected a decimal string");
const timestamp = z.iso.datetime({ offset: true });

export const REQUEST_STATUSES = [
  "requested",
  "pm_approval",
  "approved",
  "ordered",
  "delivered",
  "change_requested",
  "rejected",
  "cancelled",
] as const;
export type RequestStatus = (typeof REQUEST_STATUSES)[number];

export const REQUEST_STATUS_LABELS: Record<RequestStatus, string> = {
  requested: "QS check",
  pm_approval: "PM approval",
  approved: "Ready to order",
  ordered: "Ordered",
  delivered: "Delivered",
  change_requested: "Change requested",
  rejected: "Rejected",
  cancelled: "Cancelled",
};

const ACTIONS = ["approve", "reject", "request_change", "cancel", "edit", "order"] as const;
export type RequestAction = (typeof ACTIONS)[number];

const personSchema = z.object({ id: z.uuid(), full_name: z.string() });
const projectRefSchema = z.object({ id: z.uuid(), code: z.string(), name: z.string(), site_code: z.string() });

const ruleResultSchema = z.object({
  rule: z.string(),
  // "pending": a price rule that waits for the QS to enter the quoted price.
  severity: z.enum(["pass", "warn", "block", "pending"]),
  message: z.string(),
  facts: z.record(z.string(), z.string()),
});
export type RuleResult = z.infer<typeof ruleResultSchema>;

export const ruleCheckSchema = z.object({
  approval_level: z.enum(["qs", "pm"]),
  blocked: z.boolean(),
  results: z.array(ruleResultSchema),
  // The rules that sent the request to the project manager (BR-01, BR-13).
  routed_by: z.array(z.string()),
  // Absent for roles without "rates:read", which also never receive the BR-01 / BR-13 results.
  budget_rate: decimal.optional(),
  // Null while the price is pending.
  amount: decimal.nullable().optional(),
});
export type RuleCheck = z.infer<typeof ruleCheckSchema>;

const requestSummarySchema = z.object({
  id: z.uuid(),
  number: z.string(),
  project: projectRefSchema,
  boq_item: z.object({
    id: z.uuid(),
    item_code: z.string(),
    description: z.string(),
    unit: z.string(),
    section_code: z.string(),
  }),
  quantity: decimal,
  // Absent for roles without "rates:read"; null while the price is pending (the QS enters it).
  unit_price: decimal.nullable().optional(),
  amount: decimal.nullable().optional(),
  needed_by: z.iso.date(),
  status: z.enum(REQUEST_STATUSES),
  approval_level: z.enum(["qs", "pm"]),
  requested_by: personSchema,
  submitted_at: timestamp,
  updated_at: timestamp,
});
export type RequestSummary = z.infer<typeof requestSummarySchema>;

const requestListSchema = z.object({
  items: z.array(requestSummarySchema),
  total: z.number().int(),
  counts: z.record(z.string(), z.number().int()),
});
export type RequestList = z.infer<typeof requestListSchema>;

const deliverySchema = z.object({
  id: z.uuid(),
  quantity: decimal,
  delivered_on: z.iso.date(),
  notes: z.string().nullable(),
  created_at: timestamp,
  request_number: z.string().nullable().optional(),
  unit: z.string().nullable().optional(),
});

export const requestDetailSchema = requestSummarySchema.extend({
  notes: z.string().nullable(),
  boq_quantity: decimal,
  rules: ruleCheckSchema,
  history: z.array(
    z.object({
      action: z.string(),
      from_status: z.string().nullable(),
      to_status: z.string(),
      comment: z.string().nullable(),
      actor: personSchema,
      created_at: timestamp,
    }),
  ),
  order: z
    .object({
      id: z.uuid(),
      number: z.string(),
      supplier_name: z.string(),
      unit_price: decimal.optional(),
      amount: decimal.optional(),
      expected_delivery: z.iso.date(),
      delivered_quantity: decimal,
      deliveries: z.array(deliverySchema),
    })
    .nullable(),
  actions: z.array(z.enum(ACTIONS)),
});
export type RequestDetail = z.infer<typeof requestDetailSchema>;

const boqOptionSchema = z.object({
  id: z.uuid(),
  item_code: z.string(),
  description: z.string(),
  unit: z.string(),
  section_code: z.string(),
  section_name: z.string(),
  boq_quantity: decimal,
  requested_quantity: decimal,
  remaining_quantity: decimal,
  budget_rate: decimal.optional(),
});
export type BoqOption = z.infer<typeof boqOptionSchema>;

export const supplierSchema = z.object({
  id: z.uuid(),
  name: z.string(),
  contact_name: z.string().nullable(),
  phone: z.string().nullable(),
  email: z.string().nullable(),
  categories: z.string().nullable(),
  is_active: z.boolean(),
});
export type Supplier = z.infer<typeof supplierSchema>;

export const PO_STATUSES = ["issued", "part_delivered", "delivered"] as const;
export type PoStatus = (typeof PO_STATUSES)[number];
export const PO_STATUS_LABELS: Record<PoStatus, string> = {
  issued: "Issued",
  part_delivered: "Part delivered",
  delivered: "Delivered",
};

const poSummarySchema = z.object({
  id: z.uuid(),
  number: z.string(),
  project: projectRefSchema,
  supplier: supplierSchema,
  status: z.enum(PO_STATUSES),
  total: decimal.optional(),
  issued_at: timestamp,
  expected_delivery: z.iso.date(),
  issued_by: personSchema,
});
export type PoSummary = z.infer<typeof poSummarySchema>;

const poDetailSchema = poSummarySchema.extend({
  notes: z.string().nullable(),
  lines: z.array(
    z.object({
      id: z.uuid(),
      request_id: z.uuid(),
      request_number: z.string(),
      item_code: z.string(),
      description: z.string(),
      unit: z.string(),
      quantity: decimal,
      unit_price: decimal.optional(),
      amount: decimal.optional(),
      delivered_quantity: decimal,
    }),
  ),
  deliveries: z.array(deliverySchema),
});
export type PoDetail = z.infer<typeof poDetailSchema>;

const budgetFigures = {
  boq_amount: decimal,
  budget: decimal,
  approved: decimal, // approved, not yet on a purchase order
  on_order: decimal, // ordered, not yet delivered
  spent: decimal, // delivered
  // Cumulative: every approved, ordered or delivered request once, at its latest value (BR-13).
  committed: decimal,
  remaining: decimal, // budget - committed
  // Phase 8: committed plus the remaining budget at the cost trend so far.
  forecast_final: decimal,
  variance: decimal, // budget - forecast (negative: forecast overrun)
  variance_pct: decimal.nullable(),
  trend: decimal.nullable(), // committed / budgeted value of the committed work; null: nothing committed
  basis_pct: decimal, // % of the budget the trend rests on
  over_alert_line: z.boolean(), // forecast more than 5% over budget
};
const budgetSchema = z.object({
  project_id: z.uuid(),
  lines: z.array(
    z.object({
      section_id: z.uuid(),
      code: z.string(),
      name: z.string(),
      over_budget_since: z.iso.date().nullable(),
      ...budgetFigures,
    }),
  ),
  totals: z.object(budgetFigures),
});
export type Budget = z.infer<typeof budgetSchema>;

export const materialKeys = {
  all: ["materials"] as const,
  list: (filters: RequestFilters) => ["materials", "list", filters] as const,
  detail: (id: string) => ["materials", "detail", id] as const,
  options: (projectId: string) => ["projects", projectId, "boq-items"] as const,
  budget: (projectId: string) => ["projects", projectId, "budget"] as const,
  suppliers: (all: boolean) => ["suppliers", all] as const,
  orders: (status: string) => ["purchase-orders", status] as const,
  order: (id: string) => ["purchase-orders", "detail", id] as const,
  ready: ["purchase-orders", "ready"] as const,
};

export interface RequestFilters {
  status?: RequestStatus | "";
  projectId?: string;
  mine?: boolean;
  offset?: number;
}

export const REQUESTS_PAGE_SIZE = 50;

export function useRequests(filters: RequestFilters) {
  const params = new URLSearchParams({ limit: String(REQUESTS_PAGE_SIZE), offset: String(filters.offset ?? 0) });
  if (filters.status) params.set("status", filters.status);
  if (filters.projectId) params.set("project_id", filters.projectId);
  if (filters.mine) params.set("mine", "true");
  return useQuery({
    queryKey: materialKeys.list(filters),
    queryFn: ({ signal }) => apiRequest(`/material-requests?${params.toString()}`, requestListSchema, { signal }).then((r) => r.data),
    placeholderData: (previous) => previous,
  });
}

export function useRequest(id: string) {
  return useQuery({
    queryKey: materialKeys.detail(id),
    queryFn: ({ signal }) => apiRequest(`/material-requests/${encodeURIComponent(id)}`, requestDetailSchema, { signal }).then((r) => r.data),
  });
}

export function useBoqOptions(projectId: string) {
  return useQuery({
    queryKey: materialKeys.options(projectId),
    queryFn: ({ signal }) =>
      apiRequest(`/projects/${encodeURIComponent(projectId)}/boq-items`, z.array(boqOptionSchema), { signal }).then((r) => r.data),
    enabled: projectId !== "",
  });
}

export function useBudget(projectId: string, enabled = true) {
  return useQuery({
    queryKey: materialKeys.budget(projectId),
    queryFn: ({ signal }) => apiRequest(`/projects/${encodeURIComponent(projectId)}/budget`, budgetSchema, { signal }).then((r) => r.data),
    enabled,
  });
}

export interface RequestCheckInput {
  project_id: string;
  boq_item_id: string;
  quantity: string;
  /** Left out by roles that do not see rates: the price stays pending until the QS check. */
  unit_price?: string;
}

export function checkRequest(body: RequestCheckInput, signal?: AbortSignal): Promise<RuleCheck> {
  return apiRequest("/material-requests/check", ruleCheckSchema, { method: "POST", body, ...(signal ? { signal } : {}) }).then(
    (r) => r.data,
  );
}

export interface RequestInput extends RequestCheckInput {
  needed_by: string;
  notes: string | null;
  /** Raised from a daily report's follow-up: the follow-up is closed and linked to the request. */
  report_action_id?: string;
}

/** Anything that changes a request also moves counts, budgets, the ordering queue and notifications. */
function useInvalidateMaterials() {
  const queryClient = useQueryClient();
  return (projectId?: string) =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: materialKeys.all }),
      queryClient.invalidateQueries({ queryKey: ["purchase-orders"] }),
      queryClient.invalidateQueries({ queryKey: notificationKeys.all }),
      ...(projectId
        ? [
            queryClient.invalidateQueries({ queryKey: materialKeys.budget(projectId) }),
            queryClient.invalidateQueries({ queryKey: materialKeys.options(projectId) }),
          ]
        : []),
    ]);
}

export function useCreateRequest() {
  const invalidate = useInvalidateMaterials();
  return useMutation({
    mutationFn: (body: RequestInput) =>
      apiRequest("/material-requests", requestDetailSchema, { method: "POST", body }).then((r) => r.data),
    onSuccess: (request) => invalidate(request.project.id),
  });
}

export function useUpdateRequest(id: string) {
  const invalidate = useInvalidateMaterials();
  return useMutation({
    mutationFn: (body: { quantity?: string; unit_price?: string; needed_by?: string; notes?: string | null; comment?: string | null }) =>
      apiRequest(`/material-requests/${encodeURIComponent(id)}`, requestDetailSchema, { method: "PATCH", body }).then((r) => r.data),
    onSuccess: (request) => invalidate(request.project.id),
  });
}

export function useDecide(id: string) {
  const invalidate = useInvalidateMaterials();
  return useMutation({
    mutationFn: (body: {
      decision: "approve" | "reject" | "request_change" | "cancel";
      comment?: string | null;
      /** The QS may price the request when approving at the QS check. */
      unit_price?: string;
    }) =>
      apiRequest(`/material-requests/${encodeURIComponent(id)}/decision`, requestDetailSchema, { method: "POST", body }).then(
        (r) => r.data,
      ),
    onSuccess: (request) => invalidate(request.project.id),
  });
}

export function useSuppliers(includeInactive = false) {
  return useQuery({
    queryKey: materialKeys.suppliers(includeInactive),
    queryFn: ({ signal }) =>
      apiRequest(`/suppliers${includeInactive ? "?include_inactive=true" : ""}`, z.array(supplierSchema), { signal }).then(
        (r) => r.data,
      ),
  });
}

export interface SupplierInput {
  name?: string;
  contact_name?: string | null;
  phone?: string | null;
  email?: string | null;
  categories?: string | null;
  is_active?: boolean;
}

export function useSaveSupplier(id?: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SupplierInput) =>
      apiRequest(id ? `/suppliers/${encodeURIComponent(id)}` : "/suppliers", supplierSchema, {
        method: id ? "PATCH" : "POST",
        body,
      }).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["suppliers"] }),
  });
}

export function useReadyToOrder() {
  return useQuery({
    queryKey: materialKeys.ready,
    queryFn: ({ signal }) => apiRequest("/purchase-orders/ready", z.array(requestSummarySchema), { signal }).then((r) => r.data),
  });
}

export function useOrders(status: PoStatus | "" = "") {
  return useQuery({
    queryKey: materialKeys.orders(status),
    queryFn: ({ signal }) =>
      apiRequest(`/purchase-orders${status ? `?status=${status}` : ""}`, z.array(poSummarySchema), { signal }).then((r) => r.data),
  });
}

export function useOrder(id: string) {
  return useQuery({
    queryKey: materialKeys.order(id),
    queryFn: ({ signal }) => apiRequest(`/purchase-orders/${encodeURIComponent(id)}`, poDetailSchema, { signal }).then((r) => r.data),
  });
}

const orderResultSchema = z.object({
  // Null when every line went back to the project manager.
  order: poDetailSchema.nullable(),
  // Lines sent back for PM approval at the quoted price (BR-14, BR-13), with the reasons.
  returned: z.array(
    z.object({ request_id: z.uuid(), number: z.string(), unit_price: decimal, rules: z.array(ruleResultSchema) }),
  ),
});
export type OrderResult = z.infer<typeof orderResultSchema>;

export interface OrderInput {
  supplier_id: string;
  expected_delivery: string;
  notes: string | null;
  lines: { request_id: string; unit_price?: string }[];
}

export function useCreateOrder() {
  const invalidate = useInvalidateMaterials();
  return useMutation({
    mutationFn: (body: OrderInput) => apiRequest("/purchase-orders", orderResultSchema, { method: "POST", body }).then((r) => r.data),
    // Returned lines change requests on the same project, so the whole materials cache is refreshed.
    onSuccess: (result) => invalidate(result.order?.project.id),
  });
}

export function useRecordDelivery(orderId: string) {
  const invalidate = useInvalidateMaterials();
  return useMutation({
    mutationFn: (body: { request_id: string; quantity: string; delivered_on: string; notes: string | null }) =>
      apiRequest(`/purchase-orders/${encodeURIComponent(orderId)}/deliveries`, poDetailSchema, { method: "POST", body }).then(
        (r) => r.data,
      ),
    onSuccess: (po) => invalidate(po.project.id),
  });
}
