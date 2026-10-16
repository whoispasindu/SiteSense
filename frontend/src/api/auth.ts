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
  // Phase 13: two-step sign-in, and whether the server runs the demo (shows the banner).
  mfa_enabled: z.boolean().default(false),
  mfa_setup_required: z.boolean().default(false),
  demo_mode: z.boolean().default(false),
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

/** The password was right and a code is due: no session until ``completeSignIn``. */
const challengeSchema = z.object({
  mfa_required: z.literal(true),
  mfa_token: z.string().min(20),
  expires_in: z.number().int().positive(),
});
const loginSchema = z.union([tokenSchema.extend({ mfa_required: z.literal(false).optional() }), challengeSchema]);

export type SignInResult = { kind: "session"; user: Me } | { kind: "challenge"; token: string };

export async function signIn(email: string, password: string): Promise<SignInResult> {
  const { data } = await apiRequest("/auth/login", loginSchema, { method: "POST", body: { email, password }, auth: false });
  if ("mfa_token" in data) return { kind: "challenge", token: data.mfa_token };
  setAccessToken(data.access_token);
  return { kind: "session", user: data.user };
}

/** The code step: an authenticator code, or one recovery code. */
export function completeSignIn(token: string, second: { code: string } | { recovery_code: string }): Promise<Me> {
  return startSession("/auth/mfa/verify", { mfa_token: token, ...second });
}

// --- Two-step sign-in: the user's own set-up -----------------------------------------------------------

const mfaStatusSchema = z.object({
  enabled: z.boolean(),
  required: z.boolean(),
  enabled_at: z.iso.datetime({ offset: true }).nullable(),
  recovery_codes_left: z.number().int(),
});
export type MfaStatus = z.infer<typeof mfaStatusSchema>;

const mfaSetupSchema = z.object({
  secret: z.string().regex(/^[A-Z2-7]+$/),
  otpauth_uri: z.string().startsWith("otpauth://totp/"),
  qr_png: z.string().startsWith("data:image/png;base64,"),
});
export type MfaSetup = z.infer<typeof mfaSetupSchema>;

const codesSchema = z.object({ codes: z.array(z.string()) });

export function getMfaStatus(signal?: AbortSignal): Promise<MfaStatus> {
  return apiRequest("/auth/mfa", mfaStatusSchema, { signal }).then((r) => r.data);
}

export function startMfaSetup(): Promise<MfaSetup> {
  return apiRequest("/auth/mfa/setup", mfaSetupSchema, { method: "POST" }).then((r) => r.data);
}

export function enableMfa(code: string): Promise<string[]> {
  return apiRequest("/auth/mfa/enable", codesSchema, { method: "POST", body: { code } }).then((r) => r.data.codes);
}

export function renewRecoveryCodes(code: string): Promise<string[]> {
  return apiRequest("/auth/mfa/recovery-codes", codesSchema, { method: "POST", body: { code } }).then((r) => r.data.codes);
}

export function disableMfa(code: string): Promise<void> {
  return apiRequest("/auth/mfa/disable", empty, { method: "POST", body: { code } }).then(() => undefined);
}

export function fetchMe(): Promise<Me> {
  return apiRequest("/me", meSchema).then((r) => r.data);
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
