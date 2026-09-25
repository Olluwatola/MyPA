import type { components } from "@/lib/api/schema";
import { apiOrigin } from "@/lib/api/url";
import { setAccessToken } from "./session";

type Token = components["schemas"]["Token"];

let inflight: Promise<string | null> | null = null;

/**
 * Trades the HttpOnly refresh cookie for a new access token.
 *
 * Single-flight: the backend rotates the refresh cookie on every call and blacklists the old one,
 * so two concurrent calls (StrictMode's double boot effect, or several queries hitting 401 at
 * once) would make the second one fail and log the user out. Everyone shares one request.
 */
export function refreshAccessToken(): Promise<string | null> {
  inflight ??= fetch(`${apiOrigin()}/api/v1/refresh`, { method: "POST", credentials: "same-origin" })
    .then(async (response) => (response.ok ? ((await response.json()) as Token).access_token : null))
    .catch(() => null)
    .then((token) => {
      setAccessToken(token);
      return token;
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}
