import type { Session } from "./auth-provider";

/**
 * Only follow `next` if it's a path on this site: a single leading `/`, not `//host` (protocol-
 * relative) or `/\host` (browsers treat `\` as `/`). Anything else could be an open redirect.
 */
export function safeNext(next: string | null | undefined): string | null {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return null;
  return next;
}

export function loginUrl(next?: string): string {
  return next ? `/login?next=${encodeURIComponent(next)}` : "/login";
}

/**
 * Where a guarded area must send the user instead of rendering (plan §6). `null` = render.
 * `app` is Chat/Tasks/Goals/Settings; `onboarding` is the full-screen wizard.
 */
export function guardRedirect(session: Session, area: "app" | "onboarding", pathname: string): string | null {
  switch (session.status) {
    case "loading":
      return null;
    case "anonymous":
      return session.reason === "logout" ? loginUrl() : loginUrl(pathname);
    case "authenticated": {
      const onboarded = session.onboardingStatus === "completed";
      if (area === "app" && !onboarded) return "/onboarding";
      if (area === "onboarding" && onboarded) return "/chat";
      return null;
    }
  }
}
