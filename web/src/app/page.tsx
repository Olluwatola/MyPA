"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { ShellSkeleton } from "@/components/shell-skeleton";
import { useSession } from "@/lib/auth/use-session";

// PRD §4: / goes to /chat when signed in, /login otherwise.
export default function HomePage() {
  const session = useSession();
  const router = useRouter();

  useEffect(() => {
    if (session.status === "authenticated") router.replace("/chat");
    if (session.status === "anonymous") router.replace("/login");
  }, [session.status, router]);

  return <ShellSkeleton />;
}
