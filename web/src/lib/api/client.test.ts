import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { getAccessToken, setAccessToken, setSessionExpiredHandler } from "@/lib/auth/session";
import { API, callCount, server, user } from "@/test/server";
import { api } from "./client";

/** /users/me accepts only `validToken`; everything else is a 401. */
function meAcceptsOnly(validToken: string) {
  server.use(
    http.get(`${API}/users/me`, ({ request }) =>
      request.headers.get("Authorization") === `Bearer ${validToken}`
        ? HttpResponse.json(user)
        : HttpResponse.json({ detail: "Not authenticated" }, { status: 401 }),
    ),
  );
}

describe("authFetch", () => {
  it("attaches the bearer token", async () => {
    setAccessToken("current-token");
    meAcceptsOnly("current-token");

    const { data } = await api.GET("/api/v1/users/me");

    expect(data).toEqual(user);
    expect(callCount("POST", "/api/v1/refresh")).toBe(0);
  });

  it("refreshes once on a 401 and retries with the new token", async () => {
    setAccessToken("expired-token");
    meAcceptsOnly("fresh-token");

    const { data, response } = await api.GET("/api/v1/users/me");

    expect(response.status).toBe(200);
    expect(data).toEqual(user);
    expect(callCount("POST", "/api/v1/refresh")).toBe(1);
    expect(callCount("GET", "/api/v1/users/me")).toBe(2);
    expect(getAccessToken()).toBe("fresh-token");
  });

  it("replays the request body on the retry", async () => {
    setAccessToken("expired-token");
    const bodies: unknown[] = [];
    server.use(
      http.post(`${API}/tasks`, async ({ request }) => {
        bodies.push(await request.json());
        return request.headers.get("Authorization") === "Bearer fresh-token"
          ? HttpResponse.json({}, { status: 201 })
          : HttpResponse.json({ detail: "Not authenticated" }, { status: 401 });
      }),
    );

    const { response } = await api.POST("/api/v1/tasks", { body: { title: "Draft the proposal" } });

    expect(response.status).toBe(201);
    expect(bodies).toEqual([{ title: "Draft the proposal" }, { title: "Draft the proposal" }]);
  });

  it("ends the session when the refresh fails", async () => {
    setAccessToken("expired-token");
    meAcceptsOnly("never");
    server.use(http.post(`${API}/refresh`, () => HttpResponse.json({ detail: "Invalid" }, { status: 401 })));
    const onExpired = vi.fn();
    setSessionExpiredHandler(onExpired);

    const { response } = await api.GET("/api/v1/users/me");

    expect(response.status).toBe(401);
    expect(onExpired).toHaveBeenCalledOnce();
    expect(getAccessToken()).toBeNull();
    setSessionExpiredHandler(null);
  });

  it("doesn't refresh a second time when the retried request is still 401", async () => {
    setAccessToken("expired-token");
    meAcceptsOnly("never");
    const onExpired = vi.fn();
    setSessionExpiredHandler(onExpired);

    const { response } = await api.GET("/api/v1/users/me");

    expect(response.status).toBe(401);
    expect(callCount("POST", "/api/v1/refresh")).toBe(1);
    expect(callCount("GET", "/api/v1/users/me")).toBe(2);
    expect(onExpired).toHaveBeenCalledOnce();
    setSessionExpiredHandler(null);
  });

  it("makes exactly one /refresh call when three requests get 401 at once", async () => {
    setAccessToken("expired-token");
    meAcceptsOnly("fresh-token");

    const results = await Promise.all([
      api.GET("/api/v1/users/me"),
      api.GET("/api/v1/users/me"),
      api.GET("/api/v1/users/me"),
    ]);

    expect(results.map((r) => r.response.status)).toEqual([200, 200, 200]);
    expect(callCount("POST", "/api/v1/refresh")).toBe(1);
  });

  it("doesn't try to refresh on a 401 from /login", async () => {
    server.use(
      http.post(`${API}/login`, () => HttpResponse.json({ detail: "Wrong email or password." }, { status: 401 })),
    );

    const { error, response } = await api.POST("/api/v1/login", {
      body: { username: "ada@example.com", password: "wrong", scope: "" },
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });

    expect(response.status).toBe(401);
    expect(error).toEqual({ detail: "Wrong email or password." });
    expect(callCount("POST", "/api/v1/refresh")).toBe(0);
  });
});
