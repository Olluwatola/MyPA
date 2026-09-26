"use client";

import { use } from "react";

import { AuthContext, type AuthContextValue } from "./auth-provider";

export function useAuth(): AuthContextValue {
  const auth = use(AuthContext);
  if (!auth) throw new Error("useAuth must be used inside <AuthProvider>");
  return auth;
}

export function useSession() {
  return useAuth().session;
}

/** The signed-in user's timezone (their profile, set from the browser at signup). */
export function useTimeZone(): string {
  const session = useSession();
  return session.status === "authenticated" ? session.user.timezone : "UTC";
}
