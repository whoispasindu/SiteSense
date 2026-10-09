import type { Tone } from "../../components/ui/StatusBadge";

export const ACTION_LABELS: Record<string, { label: string; tone: Tone }> = {
  "auth.login_succeeded": { label: "Signed in", tone: "ok" },
  "auth.login_failed": { label: "Sign-in failed", tone: "warn" },
  "auth.account_locked": { label: "Account locked", tone: "down" },
  "auth.logout": { label: "Signed out", tone: "idle" },
  "auth.refresh_reuse_detected": { label: "Session token reused", tone: "down" },
  "auth.password_changed": { label: "Password changed", tone: "ok" },
  "user.created": { label: "User created", tone: "ok" },
  "user.updated": { label: "User updated", tone: "idle" },
  "user.deactivated": { label: "User deactivated", tone: "down" },
  "user.reactivated": { label: "User reactivated", tone: "ok" },
  "user.password_reset": { label: "Password reset", tone: "warn" },
  "user.sites_assigned": { label: "Sites assigned", tone: "idle" },
  "site.created": { label: "Site created", tone: "ok" },
  "site.updated": { label: "Site updated", tone: "idle" },
};
