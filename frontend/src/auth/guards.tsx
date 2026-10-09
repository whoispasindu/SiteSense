import type { ReactNode } from "react";
import { Navigate, useLocation, useSearchParams } from "react-router";

import { LogoMark } from "../components/ui/Logo";
import { ForbiddenPage } from "../pages/ForbiddenPage";
import { safeNextPath, useAuth } from "./context";

function GateLoader() {
  return (
    <div role="status" className="grid min-h-dvh place-items-center bg-asphalt text-asphalt-text">
      <div className="flex flex-col items-center gap-4">
        <LogoMark className="size-12 animate-pulse" />
        <p className="font-mono text-xs tracking-[0.2em] uppercase">Opening the site gate…</p>
      </div>
    </div>
  );
}

/** Signed-in users only; a temporary password must be replaced before anything else. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status, user, endedBy } = useAuth();
  const location = useLocation();

  if (status === "loading") return <GateLoader />;
  if (status === "anonymous" || !user) {
    if (endedBy === "user") return <Navigate to="/sign-in" replace />;
    const next = `${location.pathname}${location.search}`;
    return <Navigate to={`/sign-in?next=${encodeURIComponent(next)}`} replace />;
  }
  if (user.must_change_password && location.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace />;
  }
  return children;
}

/** UI guard only: the API enforces the same permission on every endpoint. */
export function RequirePermission({ permission, children }: { permission: string; children: ReactNode }) {
  const { can } = useAuth();
  return can(permission) ? children : <ForbiddenPage />;
}

/** The sign-in page is for signed-out visitors; signing in continues to a safe ``next`` path. */
export function AnonymousOnly({ children }: { children: ReactNode }) {
  const { status, user } = useAuth();
  const [params] = useSearchParams();
  if (status === "loading") return <GateLoader />;
  if (status === "authenticated" && user) {
    const destination = user.must_change_password ? "/change-password" : safeNextPath(params.get("next"));
    return <Navigate to={destination} replace />;
  }
  return children;
}
