// The access token lives in module memory only — never localStorage/sessionStorage (PRD §8,
// decisions-log 2026-08-28). Module level, not React state, because the fetch wrapper runs
// outside React.

let accessToken: string | null = null;
let onSessionExpired: (() => void) | null = null;

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

/** Registered by `AuthProvider`: clears the React session and the query cache. */
export function setSessionExpiredHandler(handler: (() => void) | null): void {
  onSessionExpired = handler;
}

/** Called by the fetch wrapper when the session can't be refreshed. */
export function expireSession(): void {
  accessToken = null;
  onSessionExpired?.();
}
