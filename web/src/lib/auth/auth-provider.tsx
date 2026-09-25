"use client";

import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { queryKeys, STALE_TIME } from "@/lib/api/query-config";
import type { components } from "@/lib/api/schema";
import { refreshAccessToken } from "./refresh";
import { setAccessToken, setSessionExpiredHandler } from "./session";

export type User = components["schemas"]["UserRead"];
export type OnboardingStatus = components["schemas"]["OnboardingStatusRead"]["onboarding_status"];

export type Session =
  | { status: "loading" }
  | { status: "anonymous"; reason: "boot" | "logout" | "expired" }
  | { status: "authenticated"; user: User; onboardingStatus: OnboardingStatus };

export type SignupValues = { firstName: string; lastName?: string; email: string; password: string };

export type AuthContextValue = {
  session: Session;
  login: (email: string, password: string) => Promise<void>;
  signup: (values: SignupValues) => Promise<void>;
  logout: () => Promise<void>;
  /** F1.4 calls this when onboarding completes, so the guard lets the user into the app. */
  setOnboardingStatus: (status: OnboardingStatus) => void;
};

export const AuthContext = createContext<AuthContextValue | null>(null);

/** `/users/me` has no onboarding status, so both are fetched (in parallel, cached for later screens). */
async function loadSession(queryClient: QueryClient): Promise<Session> {
  const [user, onboarding] = await Promise.all([
    queryClient.fetchQuery({
      queryKey: queryKeys.me,
      queryFn: async () => unwrap(await api.GET("/api/v1/users/me")),
      staleTime: STALE_TIME.session,
    }),
    queryClient.fetchQuery({
      queryKey: queryKeys.onboardingStatus,
      queryFn: async () => unwrap(await api.GET("/api/v1/onboarding/status")),
      staleTime: STALE_TIME.session,
    }),
  ]);
  return { status: "authenticated", user, onboardingStatus: onboarding.onboarding_status };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [session, setSession] = useState<Session>({ status: "loading" });

  // PRD §6: the token is gone after a page load, so refresh silently before rendering any
  // authenticated route. StrictMode runs this twice in dev; refresh is single-flight and
  // fetchQuery dedupes, so the backend still sees one call of each.
  useEffect(() => {
    let active = true;
    (async () => {
      const token = await refreshAccessToken();
      const next: Session = token
        ? await loadSession(queryClient).catch(() => ({ status: "anonymous", reason: "boot" }) as const)
        : { status: "anonymous", reason: "boot" };
      if (active) setSession(next);
    })();
    return () => {
      active = false;
    };
  }, [queryClient]);

  useEffect(() => {
    setSessionExpiredHandler(() => {
      queryClient.clear();
      setSession({ status: "anonymous", reason: "expired" });
    });
    return () => setSessionExpiredHandler(null);
  }, [queryClient]);

  const login = useCallback(
    async (email: string, password: string) => {
      const result = await api.POST("/api/v1/login", {
        body: { username: email, password, scope: "" },
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
      });
      setAccessToken(unwrap(result).access_token);
      setSession(await loadSession(queryClient));
    },
    [queryClient],
  );

  const signup = useCallback(
    async ({ firstName, lastName, email, password }: SignupValues) => {
      unwrap(
        await api.POST("/api/v1/register", {
          body: {
            first_name: firstName,
            last_name: lastName || undefined,
            email,
            password,
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
          },
        }),
      );
      // /register doesn't sign in.
      await login(email, password);
    },
    [login],
  );

  const logout = useCallback(async () => {
    // Clear locally even if the request fails: the user asked to be signed out.
    await api.POST("/api/v1/logout").catch(() => undefined);
    setAccessToken(null);
    queryClient.clear();
    setSession({ status: "anonymous", reason: "logout" });
  }, [queryClient]);

  const setOnboardingStatus = useCallback((onboardingStatus: OnboardingStatus) => {
    setSession((current) => (current.status === "authenticated" ? { ...current, onboardingStatus } : current));
  }, []);

  const value = useMemo(
    () => ({ session, login, signup, logout, setOnboardingStatus }),
    [session, login, signup, logout, setOnboardingStatus],
  );

  return <AuthContext value={value}>{children}</AuthContext>;
}
