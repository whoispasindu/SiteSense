import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { resumeSession, signIn as apiSignIn, signOut as apiSignOut, type Me } from "../api/auth";
import { configureSession, refreshSession, setAccessToken } from "../api/client";
import { AuthContext, type AuthContextValue, type AuthStatus } from "./context";

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUserState] = useState<Me | null>(null);
  const [endedBy, setEndedBy] = useState<"user" | "expiry" | null>(null);

  const becomeAnonymous = useCallback(() => {
    setAccessToken(null);
    setUserState(null);
    setStatus("anonymous");
    // Drop every cached response so the next user never sees the previous user's data.
    queryClient.clear();
  }, [queryClient]);

  const setUser = useCallback((next: Me) => {
    setUserState(next);
    setStatus("authenticated");
    setEndedBy(null);
  }, []);

  useEffect(() => {
    configureSession({
      refresh: async () => {
        const me = await resumeSession();
        if (me) setUser(me);
        return me !== null;
      },
      onExpired: () => {
        setEndedBy("expiry");
        becomeAnonymous();
      },
    });

    let cancelled = false;
    // The access token lives only in memory, so every page load restores it from the cookie.
    refreshSession()
      .then((ok) => {
        if (!cancelled && !ok) becomeAnonymous();
      })
      .catch(() => {
        if (!cancelled) becomeAnonymous();
      });

    return () => {
      cancelled = true;
      configureSession(null);
    };
  }, [becomeAnonymous, setUser]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      queryClient.clear();
      const me = await apiSignIn(email, password);
      setUser(me);
      return me;
    },
    [queryClient, setUser],
  );

  const signOut = useCallback(async () => {
    setEndedBy("user");
    try {
      await apiSignOut();
    } finally {
      becomeAnonymous();
    }
  }, [becomeAnonymous]);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      endedBy,
      user,
      signIn,
      signOut,
      setUser,
      can: (permission: string) => user?.permissions.includes(permission) ?? false,
    }),
    [status, endedBy, user, signIn, signOut, setUser],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
