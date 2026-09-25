"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { ShellSkeleton } from "@/components/shell-skeleton";
import { guardRedirect } from "@/lib/auth/redirects";
import { useSession } from "@/lib/auth/use-session";

// Client-side guard: the token is in memory and the refresh cookie is scoped to /api/v1, so
// nothing on the server can tell whether the user is signed in (plan Q6).
export default function AppLayout({ children }: { children: ReactNode }) {
  const session = useSession();
  const pathname = usePathname();
  const router = useRouter();
  const redirect = guardRedirect(session, "app", pathname);

  useEffect(() => {
    if (redirect) router.replace(redirect);
  }, [redirect, router]);

  if (session.status !== "authenticated" || redirect) return <ShellSkeleton />;
  return <AppShell>{children}</AppShell>;
}
