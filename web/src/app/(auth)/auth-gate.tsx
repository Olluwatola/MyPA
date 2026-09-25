"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { safeNext } from "@/lib/auth/redirects";
import { useSession } from "@/lib/auth/use-session";

export function AuthSkeleton() {
  return <Skeleton aria-busy="true" aria-label="Loading" className="h-80 w-full rounded-lg" />;
}

/** Signed-in users don't see the login/signup forms: they go to `next` (if safe) or /chat. */
export function AuthGate({ children }: { children: ReactNode }) {
  const session = useSession();
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next")) ?? "/chat";

  useEffect(() => {
    if (session.status === "authenticated") router.replace(next);
  }, [session.status, next, router]);

  if (session.status !== "anonymous") return <AuthSkeleton />;
  return children;
}
