import { Skeleton } from "@/components/ui/skeleton";

/** Shown while the session is being restored — never a login-screen flash (PRD §6). */
export function ShellSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading" className="mx-auto flex min-h-dvh w-full max-w-2xl flex-col gap-6 px-4 py-16">
      <Skeleton className="h-6 w-40" />
      <Skeleton className="h-16 w-4/5" />
      <Skeleton className="ml-auto h-10 w-1/2" />
      <Skeleton className="h-24 w-3/4" />
    </div>
  );
}
