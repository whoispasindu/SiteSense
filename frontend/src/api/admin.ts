import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { roleSchema, siteSummarySchema, type Role } from "./auth";
import { apiRequest } from "./client";

const pageOf = <T extends z.ZodType>(item: T) =>
  z.object({ items: z.array(item), total: z.number().int(), limit: z.number().int(), offset: z.number().int() });

export const userSchema = z.object({
  id: z.uuid(),
  email: z.string(),
  full_name: z.string(),
  role: roleSchema,
  role_label: z.string(),
  is_active: z.boolean(),
  is_locked: z.boolean(),
  must_change_password: z.boolean(),
  last_login_at: z.iso.datetime({ offset: true }).nullable(),
  created_at: z.iso.datetime({ offset: true }),
  sites: z.array(siteSummarySchema),
  // Clients only (Phase 12): the projects they may see.
  projects: z.array(z.object({ id: z.uuid(), code: z.string(), name: z.string() })).default([]),
});
export type AdminUser = z.infer<typeof userSchema>;

export const siteSchema = z.object({
  id: z.uuid(),
  code: z.string(),
  name: z.string(),
  location: z.string(),
  latitude: z.number().nullable(),
  longitude: z.number().nullable(),
  is_active: z.boolean(),
  created_at: z.iso.datetime({ offset: true }),
});
export type Site = z.infer<typeof siteSchema>;

export const auditLogSchema = z.object({
  id: z.uuid(),
  occurred_at: z.iso.datetime({ offset: true }),
  action: z.string(),
  actor_id: z.uuid().nullable(),
  actor_name: z.string().nullable(),
  target_type: z.string().nullable(),
  target_id: z.string().nullable(),
  ip_address: z.string().nullable(),
  details: z.record(z.string(), z.unknown()),
});
export type AuditLogEntry = z.infer<typeof auditLogSchema>;

const usersPage = pageOf(userSchema);
const auditPage = pageOf(auditLogSchema);
const createdUserSchema = z.object({ user: userSchema, temporary_password: z.string() });
const passwordResetSchema = z.object({ temporary_password: z.string() });

export const adminKeys = {
  users: ["admin", "users"] as const,
  sites: ["admin", "sites"] as const,
  audit: (offset: number, action: string) => ["admin", "audit", offset, action] as const,
};

// --- Users --------------------------------------------------------------------------------

export function useUsers() {
  return useQuery({
    queryKey: adminKeys.users,
    queryFn: ({ signal }) => apiRequest("/admin/users?limit=100", usersPage, { signal }).then((r) => r.data),
  });
}

export interface NewUser {
  email: string;
  full_name: string;
  role: Role;
  site_ids: string[];
}

function useInvalidateUsers() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: adminKeys.users });
}

export function useCreateUser() {
  const invalidate = useInvalidateUsers();
  return useMutation({
    mutationFn: (body: NewUser) =>
      apiRequest("/admin/users", createdUserSchema, { method: "POST", body }).then((r) => r.data),
    onSuccess: invalidate,
  });
}

export function useUpdateUser() {
  const invalidate = useInvalidateUsers();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; full_name?: string; role?: Role; is_active?: boolean }) =>
      apiRequest(`/admin/users/${encodeURIComponent(id)}`, userSchema, { method: "PATCH", body }).then((r) => r.data),
    onSuccess: invalidate,
  });
}

export function useAssignSites() {
  const invalidate = useInvalidateUsers();
  return useMutation({
    mutationFn: ({ id, siteIds }: { id: string; siteIds: string[] }) =>
      apiRequest(`/admin/users/${encodeURIComponent(id)}/sites`, userSchema, {
        method: "POST",
        body: { site_ids: siteIds },
      }).then((r) => r.data),
    onSuccess: invalidate,
  });
}

const adminProjectSchema = z.object({
  id: z.uuid(),
  code: z.string(),
  name: z.string(),
  site_code: z.string(),
  status: z.string(),
  client_name: z.string(),
  clients: z.number().int(),
});
export type AdminProject = z.infer<typeof adminProjectSchema>;

/** Every project, to link client accounts to (Phase 12). No contract figures. */
export function useAdminProjects(enabled = true) {
  return useQuery({
    queryKey: ["admin", "projects"] as const,
    queryFn: ({ signal }) => apiRequest("/admin/projects", z.array(adminProjectSchema), { signal }).then((r) => r.data),
    enabled,
  });
}

export function useAssignProjects() {
  const invalidate = useInvalidateUsers();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, projectIds }: { id: string; projectIds: string[] }) =>
      apiRequest(`/admin/users/${encodeURIComponent(id)}/projects`, userSchema, {
        method: "POST",
        body: { project_ids: projectIds },
      }).then((r) => r.data),
    onSuccess: async () => {
      await invalidate();
      await queryClient.invalidateQueries({ queryKey: ["admin", "projects"] });
    },
  });
}

export function useResetPassword() {
  const invalidate = useInvalidateUsers();
  return useMutation({
    mutationFn: (id: string) =>
      apiRequest(`/admin/users/${encodeURIComponent(id)}/reset-password`, passwordResetSchema, {
        method: "POST",
      }).then((r) => r.data),
    onSuccess: invalidate,
  });
}

// --- Sites --------------------------------------------------------------------------------

export function useSites() {
  return useQuery({
    queryKey: adminKeys.sites,
    queryFn: ({ signal }) => apiRequest("/admin/sites", z.array(siteSchema), { signal }).then((r) => r.data),
  });
}

export interface NewSite {
  code: string;
  name: string;
  location: string;
  latitude: number | null;
  longitude: number | null;
}

export function useCreateSite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: NewSite) => apiRequest("/admin/sites", siteSchema, { method: "POST", body }).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin"] }),
  });
}

export function useUpdateSite() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; is_active?: boolean; name?: string; location?: string }) =>
      apiRequest(`/admin/sites/${encodeURIComponent(id)}`, siteSchema, { method: "PATCH", body }).then((r) => r.data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin"] }),
  });
}

// --- Audit log ----------------------------------------------------------------------------

export const AUDIT_PAGE_SIZE = 25;

export function useAuditLog(offset: number, action: string) {
  const params = new URLSearchParams({ limit: String(AUDIT_PAGE_SIZE), offset: String(offset) });
  if (action) params.set("action", action);
  return useQuery({
    queryKey: adminKeys.audit(offset, action),
    queryFn: ({ signal }) => apiRequest(`/admin/audit-logs?${params.toString()}`, auditPage, { signal }).then((r) => r.data),
    placeholderData: (previous) => previous,
  });
}
