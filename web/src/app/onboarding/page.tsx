"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { LogoutButton } from "@/components/logout-button";
import { ShellSkeleton } from "@/components/shell-skeleton";
import { guardRedirect } from "@/lib/auth/redirects";
import { useSession } from "@/lib/auth/use-session";

// Placeholder until F1.4 (onboarding wizard). Full screen, no tab bar (PRD §5.2).
export default function OnboardingPage() {
  const session = useSession();
  const router = useRouter();
  const redirect = guardRedirect(session, "onboarding", "/onboarding");

  useEffect(() => {
    if (redirect) router.replace(redirect);
  }, [redirect, router]);

  if (session.status !== "authenticated" || redirect) return <ShellSkeleton />;

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-lg flex-col justify-center gap-4 px-4 py-16">
      <h1 className="font-serif text-display font-medium">Welcome, {session.user.first_name}.</h1>
      <p className="text-ink-2">
        Setup comes next: connecting your accounts and choosing your goals. It isn&apos;t built yet.
      </p>
      <div>
        <LogoutButton />
      </div>
    </main>
  );
}
