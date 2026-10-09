import { z } from "zod";

import { ApiError, apiRequest, setAccessToken } from "./client";

export const ROLES = [
  "admin",
  "project_manager",
  "quantity_surveyor",
  "site_engineer",
  "procurement_officer",
  "client",
] as const;

export const roleSchema = z.enum(ROLES);
export type Role = z.infer<typeof roleSchema>;

export const ROLE_LABELS: Record<Role, string> = {
  admin: "Company Admin",
  project_manager: "Project Manager",
  quantity_surveyor: "Quantity Surveyor",
  site_engineer: "Site Engineer",
  procurement_officer: "Procurement Officer",
  client: "Client",
};

export const siteSummarySchema = z.object({
  id: z.uuid(),
  code: z.string(),
  name: z.string(),
});
export type SiteSummary = z.infer<typeof siteSummarySchema>;

export const meSchema = z.object({
  id: z.uuid(),
  email: z.string(),
  full_name: z.string(),
  role: roleSchema,
  role_label: z.string(),
  permissions: z.array(z.string()),
  site_scoped: z.boolean(),
  sites: z.array(siteSummarySchema),
  must_change_password: z.boolean(),
});
export type Me = z.infer<typeof meSchema>;

export const tokenSchema = z.object({
  access_token: z.string().min(1),
  token_type: z.literal("bearer"),
  expires_in: z.number().int().positive(),
  user: meSchema,
});

const empty = z.null();

async function startSession(path: string, body?: unknown): Promise<Me> {
  const { data } = await apiRequest(path, tokenSchema, { method: "POST", body, auth: false });
  setAccessToken(data.access_token);
  return data.user;
}

export function signIn(email: string, password: string): Promise<Me> {
  return startSession("/auth/login", { email, password });
}

const SUPERSEDED_RETRY_MS = 250;

/** Restore or extend the session from the httpOnly refresh cookie. Null when signed out. */
export async function resumeSession(): Promise<Me | null> {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      return await startSession("/auth/refresh");
    } catch (error) {
      // Another tab rotated the cookie a moment ago; the browser now holds the new one.
      if (error instanceof ApiError && error.code === "refresh_superseded" && attempt === 0) {
        await new Promise((resolve) => setTimeout(resolve, SUPERSEDED_RETRY_MS));
        continue;
      }
      if (error instanceof ApiError && error.status === 401) return null;
      throw error;
    }
  }
  return null;
}

export async function signOut(): Promise<void> {
  try {
    await apiRequest("/auth/logout", empty, { method: "POST", auth: false });
  } finally {
    setAccessToken(null);
  }
}

export function changePassword(currentPassword: string, newPassword: string): Promise<Me> {
  // Uses the current access token, so it goes through the authenticated path.
  return apiRequest("/auth/change-password", tokenSchema, {
    method: "POST",
    body: { current_password: currentPassword, new_password: newPassword },
  }).then(({ data }) => {
    setAccessToken(data.access_token);
    return data.user;
  });
}
