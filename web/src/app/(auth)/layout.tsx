import { Suspense, type ReactNode } from "react";

import { AuthGate, AuthSkeleton } from "./auth-gate";

// Centered card for /login and /signup. Suspense because the pages read search params.
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <p className="mb-8 text-center font-serif text-display font-medium">MyPA</p>
        <Suspense fallback={<AuthSkeleton />}>
          <AuthGate>{children}</AuthGate>
        </Suspense>
      </div>
    </main>
  );
}
