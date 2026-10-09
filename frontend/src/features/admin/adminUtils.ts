import type { AdminUser } from "../../api/admin";
import type { Role } from "../../api/auth";
import { ApiError } from "../../api/client";
import type { Tone } from "../../components/ui/StatusBadge";

/** Roles limited to their assigned sites (mirrors SITE_SCOPED_ROLES on the server). */
export const SITE_SCOPED_ROLES: readonly Role[] = ["project_manager", "quantity_surveyor", "site_engineer", "client"];

export function isSiteScoped(role: Role): boolean {
  return SITE_SCOPED_ROLES.includes(role);
}

export function userStatus(user: AdminUser): { tone: Tone; label: string } {
  if (!user.is_active) return { tone: "idle", label: "Inactive" };
  if (user.is_locked) return { tone: "down", label: "Locked" };
  if (user.must_change_password) return { tone: "warn", label: "Temp password" };
  return { tone: "ok", label: "Active" };
}

export function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong. Try again.";
}

const dateTime = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Colombo",
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

export function formatDateTime(iso: string | null): string {
  return iso ? dateTime.format(new Date(iso)) : "Never";
}
