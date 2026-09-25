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
