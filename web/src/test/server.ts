import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

import type { components } from "@/lib/api/schema";

export const API = "http://localhost:3000/api/v1";

export const user: components["schemas"]["UserRead"] = {
  id: "0199a0c0-0000-7000-8000-000000000001",
  first_name: "Ada",
  last_name: "Lovelace",
  email: "ada@example.com",
  timezone: "Europe/London",
  is_superuser: false,
};

/** Counts calls per "METHOD /path" so tests can assert e.g. exactly one /refresh. */
export const calls = new Map<string, number>();

export function callCount(method: string, path: string): number {
  return calls.get(`${method} ${path}`) ?? 0;
}

// Default: a signed-in user whose refresh cookie works and who finished onboarding.
export const handlers = [
  http.post(`${API}/refresh`, () => HttpResponse.json({ access_token: "fresh-token", token_type: "bearer" })),
  http.get(`${API}/users/me`, () => HttpResponse.json(user)),
  http.get(`${API}/onboarding/status`, () =>
    HttpResponse.json({ onboarding_status: "completed", onboarding_suggested_goals: null, onboarding_completed_at: null }),
  ),
  http.post(`${API}/login`, () => HttpResponse.json({ access_token: "login-token", token_type: "bearer" })),
  http.post(`${API}/register`, () => HttpResponse.json(user, { status: 201 })),
  http.post(`${API}/logout`, () => new HttpResponse(null, { status: 204 })),
];

export const server = setupServer(...handlers);

server.events.on("request:start", ({ request }) => {
  const key = `${request.method} ${new URL(request.url).pathname}`;
  calls.set(key, (calls.get(key) ?? 0) + 1);
});
