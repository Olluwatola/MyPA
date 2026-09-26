import { MutationCache, QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError, errorMessage } from "./errors";

/**
 * How long each kind of data counts as fresh (decisions-log 2026-09-25, "instant cached screens").
 * Cached data always shows instantly; this only decides when a quiet background re-check happens.
 */
export const STALE_TIME = {
  /** `/users/me`, `/onboarding/status`: rarely change, and our own mutations update them. */
  session: 5 * 60_000,
  /** Goals list/detail: change rarely; the app's own edits update the cache directly. */
  goals: 5 * 60_000,
  /** Tasks list/detail: background jobs (email, Notion) add tasks. */
  tasks: 30_000,
  /** Integration status: can break at any time (expired token). */
  integrations: 60_000,
  /** Chat history: kept fresh by the live stream (F1.3), never re-fetched on a timer. */
  chatHistory: Infinity,
} as const;

export const queryKeys = {
  me: ["users", "me"],
  onboardingStatus: ["onboarding", "status"],
  goals: {
    all: ["goals"],
    lists: ["goals", "list"],
    list: (view: string) => ["goals", "list", view],
    detail: (id: string) => ["goals", "detail", id],
  },
  tasks: {
    byGoal: (goalId: string) => ["tasks", "byGoal", goalId],
  },
} as const;

/** Never retry a 4xx (it won't change); retry network errors and 5xx up to twice. */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status < 500) return false;
  return failureCount < 2;
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: true,
        retry: shouldRetry,
      },
    },
    // PRD §7: mutation failures are a toast, never a full-page error. While offline, TanStack's
    // default networkMode ("online") pauses mutations instead of failing them.
    mutationCache: new MutationCache({
      onError: (error) => {
        toast.error(errorMessage(error));
      },
    }),
  });
}
