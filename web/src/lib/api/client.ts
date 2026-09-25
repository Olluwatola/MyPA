import createClient from "openapi-fetch";

import { refreshAccessToken } from "@/lib/auth/refresh";
import { expireSession, getAccessToken } from "@/lib/auth/session";
import type { paths } from "./schema";
import { apiOrigin } from "./url";

// A 401 from these means "bad credentials" or "already signed out", not "access token expired".
const NO_REFRESH_PATHS = new Set(["/api/v1/login", "/api/v1/register", "/api/v1/refresh", "/api/v1/logout"]);

function send(request: Request, token: string | null): Promise<Response> {
  if (token) {
    request.headers.set("Authorization", `Bearer ${token}`);
  }
  return fetch(request);
}

/**
 * Attaches the in-memory access token. On a 401, refreshes once (shared with any other request
 * that hits 401 at the same moment) and retries the request once. If that doesn't work, the
 * session is over: it's cleared and the route guard sends the user to /login (PRD §6).
 */
export async function authFetch(request: Request): Promise<Response> {
  const replay = request.clone(); // the body can only be read once
  const sentWith = getAccessToken();
  const response = await send(request, sentWith);

  if (response.status !== 401 || NO_REFRESH_PATHS.has(new URL(request.url).pathname)) {
    return response;
  }

  // Another request may already have refreshed while this one was in flight.
  const current = getAccessToken();
  const token = current && current !== sentWith ? current : await refreshAccessToken();
  if (!token) {
    expireSession();
    return response;
  }

  const retried = await send(replay, token);
  if (retried.status === 401) {
    expireSession();
  }
  return retried;
}

export const api = createClient<paths>({ baseUrl: apiOrigin(), fetch: authFetch });
