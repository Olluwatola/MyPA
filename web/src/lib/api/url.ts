/**
 * This app's own origin. `/api/*` is proxied to the backend (next.config.ts), so the browser only
 * ever talks to its own origin. URLs are made absolute because `Request` outside a browser (tests)
 * can't resolve relative ones. Empty during server rendering, where no API calls are made.
 */
export function apiOrigin(): string {
  return typeof window === "undefined" ? "" : window.location.origin;
}
