import { createContext, useContext } from "react";

import type { Me } from "../api/auth";

export type AuthStatus = "loading" | "anonymous" | "authenticated";

export interface AuthContextValue {
  status: AuthStatus;
  /** Why the user is signed out: a deliberate sign-out starts clean, an expiry keeps "next". */
  endedBy: "user" | "expiry" | null;
  user: Me | null;
  signIn: (email: string, password: string) => Promise<Me>;
  signOut: () => Promise<void>;
  /** Replace the signed-in user (after a password change, for example). */
  setUser: (user: Me) => void;
  can: (permission: string) => boolean;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}

/** Only same-origin, absolute paths may be used as a post-sign-in destination (no open redirect). */
export function safeNextPath(next: string | null | undefined): string {
  if (!next?.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return "/";
  if (next.startsWith("/sign-in") || next.startsWith("/change-password")) return "/";
  return next;
}
