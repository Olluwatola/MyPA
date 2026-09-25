import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";

import { navigation } from "@/test/navigation-mock";
import { renderWithProviders } from "@/test/render";
import { API, server } from "@/test/server";
import { AuthGate } from "../auth-gate";
import SignupPage from "../signup/page";
import LoginPage from "./page";

beforeEach(() => {
  // Start signed out so the forms render.
  server.use(http.post(`${API}/refresh`, () => HttpResponse.json({ detail: "Invalid" }, { status: 401 })));
});

describe("login page", () => {
  it("shows a 401 inline under the form, keeping what was typed", async () => {
    server.use(
      http.post(`${API}/login`, () => HttpResponse.json({ detail: "Wrong email or password." }, { status: 401 })),
    );
    renderWithProviders(<LoginPage />);

    await userEvent.type(await screen.findByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong email or password.");
    expect(screen.getByLabelText("Email")).toHaveValue("ada@example.com");
  });

  it("says the user is offline when the request can't be sent", async () => {
    server.use(http.post(`${API}/login`, () => HttpResponse.error()));
    renderWithProviders(<LoginPage />);

    await userEvent.type(await screen.findByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "whatever");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("You're offline");
  });

  it("goes to a safe `next` after signing in", async () => {
    navigation.search = "next=%2Ftasks";
    renderWithProviders(
      <AuthGate>
        <LoginPage />
      </AuthGate>,
    );

    await userEvent.type(await screen.findByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "right-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/tasks"));
  });

  it("ignores an unsafe `next` and goes to /chat", async () => {
    navigation.search = "next=%2F%2Fevil.com";
    renderWithProviders(
      <AuthGate>
        <LoginPage />
      </AuthGate>,
    );

    await userEvent.type(await screen.findByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "right-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/chat"));
  });
});

describe("signup page", () => {
  it("shows a duplicate email (422) on the email field", async () => {
    server.use(
      http.post(`${API}/register`, () => HttpResponse.json({ detail: "Email is already registered" }, { status: 422 })),
    );
    renderWithProviders(<SignupPage />);

    await userEvent.type(await screen.findByLabelText("First name"), "Ada");
    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "long-enough");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("An account with this email already exists.")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
  });

  it("shows the password rule as a hint before any error", async () => {
    renderWithProviders(<SignupPage />);

    expect(await screen.findByText("At least 8 characters.")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("First name"), "Ada");
    await userEvent.type(screen.getByLabelText("Email"), "ada@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("Use at least 8 characters.")).toBeInTheDocument();
    expect(screen.queryByText("At least 8 characters.")).not.toBeInTheDocument();
  });
});
