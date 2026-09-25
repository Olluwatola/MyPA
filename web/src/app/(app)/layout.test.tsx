import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { LogoutButton } from "@/components/logout-button";
import { safeNext } from "@/lib/auth/redirects";
import { navigation } from "@/test/navigation-mock";
import { renderWithProviders } from "@/test/render";
import { API, server } from "@/test/server";
import OnboardingPage from "../onboarding/page";
import AppLayout from "./layout";

function onboardingStatus(status: string) {
  server.use(
    http.get(`${API}/onboarding/status`, () =>
      HttpResponse.json({ onboarding_status: status, onboarding_suggested_goals: null, onboarding_completed_at: null }),
    ),
  );
}

function renderApp(pathname: string) {
  navigation.pathname = pathname;
  return renderWithProviders(
    <AppLayout>
      <p>page content</p>
    </AppLayout>,
  );
}

describe("(app) guard", () => {
  it("shows the skeleton, not a login screen, while the session loads", async () => {
    // Held open, then released so the shared single-flight refresh doesn't leak into other tests.
    let release!: () => void;
    const held = new Promise<void>((resolve) => (release = resolve));
    server.use(
      http.post(`${API}/refresh`, async () => {
        await held;
        return HttpResponse.json({ detail: "Invalid" }, { status: 401 });
      }),
    );

    renderApp("/tasks");
    await delay(50);

    expect(screen.getByLabelText("Loading")).toBeInTheDocument();
    expect(screen.queryByText("page content")).not.toBeInTheDocument();
    expect(navigation.replace).not.toHaveBeenCalled();

    release();
    await waitFor(() => expect(navigation.replace).toHaveBeenCalled());
  });

  it("sends a signed-out visitor to /login with the page as `next`", async () => {
    server.use(http.post(`${API}/refresh`, () => HttpResponse.json({ detail: "Invalid" }, { status: 401 })));

    renderApp("/tasks");

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/login?next=%2Ftasks"));
    expect(screen.queryByText("page content")).not.toBeInTheDocument();
  });

  it("sends a user who hasn't finished onboarding to /onboarding", async () => {
    onboardingStatus("not_started");

    renderApp("/chat");

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/onboarding"));
    expect(screen.queryByText("page content")).not.toBeInTheDocument();
  });

  it("renders the page and tab bar for an onboarded user, with the current tab marked", async () => {
    renderApp("/tasks");

    expect(await screen.findByText("page content")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Main" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tasks" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Chat" })).not.toHaveAttribute("aria-current");
    expect(navigation.replace).not.toHaveBeenCalled();
  });

  it("sends the user to plain /login after they log out", async () => {
    navigation.pathname = "/settings";
    renderWithProviders(
      <AppLayout>
        <LogoutButton />
      </AppLayout>,
    );

    await userEvent.click(await screen.findByRole("button", { name: "Log out" }));

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/login"));
  });
});

describe("/onboarding guard", () => {
  it("sends an onboarded user to /chat", async () => {
    renderWithProviders(<OnboardingPage />);

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/chat"));
  });

  it("shows the page to a user who hasn't finished onboarding", async () => {
    onboardingStatus("pending");

    renderWithProviders(<OnboardingPage />);

    expect(await screen.findByRole("heading", { name: "Welcome, Ada." })).toBeInTheDocument();
    expect(navigation.replace).not.toHaveBeenCalled();
  });
});

describe("safeNext", () => {
  it.each(["/tasks", "/goals?view=all"])("follows the internal path %s", (next) => {
    expect(safeNext(next)).toBe(next);
  });

  it.each(["//evil.com", "https://evil.com", "/\\evil.com", "javascript:alert(1)", "", null])(
    "rejects %s",
    (next) => {
      expect(safeNext(next)).toBeNull();
    },
  );
});
