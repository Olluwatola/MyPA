import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { API, callCount, server, user } from "@/test/server";
import { renderWithProviders } from "@/test/render";
import { getAccessToken } from "./session";
import { useAuth } from "./use-session";

function Probe() {
  const { session, logout, signup } = useAuth();
  return (
    <div>
      <p data-testid="status">
        {session.status}
        {session.status === "authenticated" && ` ${session.user.first_name} ${session.onboardingStatus}`}
        {session.status === "anonymous" && ` ${session.reason}`}
      </p>
      <button onClick={() => logout()}>logout</button>
      <button onClick={() => signup({ firstName: "Ada", email: "ada@example.com", password: "long-enough" })}>
        signup
      </button>
    </div>
  );
}

const status = () => screen.getByTestId("status");

describe("AuthProvider", () => {
  it("boots into an authenticated session when the refresh cookie works", async () => {
    renderWithProviders(<Probe />);

    expect(status()).toHaveTextContent("loading");
    await waitFor(() => expect(status()).toHaveTextContent("authenticated Ada completed"));
    expect(getAccessToken()).toBe("fresh-token");
  });

  it("boots anonymous when the refresh fails", async () => {
    server.use(http.post(`${API}/refresh`, () => HttpResponse.json({ detail: "Invalid" }, { status: 401 })));

    renderWithProviders(<Probe />);

    await waitFor(() => expect(status()).toHaveTextContent("anonymous boot"));
    expect(callCount("GET", "/api/v1/users/me")).toBe(0);
  });

  it("makes one /refresh call even though StrictMode runs the boot effect twice", async () => {
    renderWithProviders(<Probe />);

    await waitFor(() => expect(status()).toHaveTextContent("authenticated"));
    expect(callCount("POST", "/api/v1/refresh")).toBe(1);
    expect(callCount("GET", "/api/v1/users/me")).toBe(1);
    expect(callCount("GET", "/api/v1/onboarding/status")).toBe(1);
  });

  it("signs up with the browser's timezone, then logs in", async () => {
    server.use(http.post(`${API}/refresh`, () => HttpResponse.json({ detail: "Invalid" }, { status: 401 })));
    let registered: Record<string, unknown> | undefined;
    let loginForm: URLSearchParams | undefined;
    server.use(
      http.post(`${API}/register`, async ({ request }) => {
        registered = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(user, { status: 201 });
      }),
      http.post(`${API}/login`, async ({ request }) => {
        loginForm = new URLSearchParams(await request.text());
        return HttpResponse.json({ access_token: "login-token", token_type: "bearer" });
      }),
    );
    renderWithProviders(<Probe />);
    await waitFor(() => expect(status()).toHaveTextContent("anonymous"));

    await userEvent.click(screen.getByText("signup"));

    await waitFor(() => expect(status()).toHaveTextContent("authenticated"));
    expect(registered).toEqual({
      first_name: "Ada",
      email: "ada@example.com",
      password: "long-enough",
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    });
    expect(loginForm?.get("username")).toBe("ada@example.com");
    expect(loginForm?.get("password")).toBe("long-enough");
    expect(getAccessToken()).toBe("login-token");
  });

  it("signs out locally even when /logout fails", async () => {
    server.use(http.post(`${API}/logout`, () => HttpResponse.error()));
    const { queryClient } = renderWithProviders(<Probe />);
    await waitFor(() => expect(status()).toHaveTextContent("authenticated"));

    await userEvent.click(screen.getByText("logout"));

    await waitFor(() => expect(status()).toHaveTextContent("anonymous logout"));
    expect(getAccessToken()).toBeNull();
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  });
});
