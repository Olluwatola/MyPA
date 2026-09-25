"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { ShellSkeleton } from "@/components/shell-skeleton";
import { useSession } from "@/lib/auth/use-session";

// Google sign-in lands here with only the refresh cookie set. The AuthProvider's boot refresh
// turns it into a session; the (app) guard then applies the onboarding redirect.
export default function AuthCallbackPage() {
  const session = useSession();
  const router = useRouter();

  useEffect(() => {
    if (session.status === "authenticated") router.replace("/chat");
    if (session.status === "anonymous") router.replace("/login?error=google");
  }, [session.status, router]);

  return <ShellSkeleton />;
}
