import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { routeTree } from "@/routeTree.gen";

function renderForgotPassword(): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/forgot-password"] }),
    context: { queryClient },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("<ForgotPasswordRoute>", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders email input and submit button", async () => {
    renderForgotPassword();
    expect(await screen.findByRole("textbox", { name: /email/i })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /send reset link/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to sign in/i })).toHaveAttribute(
      "href",
      "/login",
    );
  });

  it("submits email to /auth/forgot-password and displays success state", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.resolve(new Response(null, { status: 202 })),
    );
    vi.stubGlobal("fetch", fetchSpy);

    renderForgotPassword();
    const emailInput = await screen.findByRole("textbox", { name: /email/i });
    await user.type(emailInput, "user@example.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/auth/forgot-password",
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: "user@example.com" }),
        }),
      );
    });

    expect(
      await screen.findByTestId("forgot-password-success-title"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /back to sign in/i }),
    ).toBeInTheDocument();
  });

  it("displays error message when request fails", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.resolve(new Response("Failed", { status: 500 })),
    );
    vi.stubGlobal("fetch", fetchSpy);

    renderForgotPassword();
    const emailInput = await screen.findByRole("textbox", { name: /email/i });
    await user.type(emailInput, "user@example.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("trims whitespace from email before submitting", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.resolve(new Response(null, { status: 202 })),
    );
    vi.stubGlobal("fetch", fetchSpy);

    renderForgotPassword();
    const emailInput = await screen.findByRole("textbox", { name: /email/i });
    await user.type(emailInput, "   spaced@example.com   ");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/auth/forgot-password",
        expect.objectContaining({
          body: JSON.stringify({ email: "spaced@example.com" }),
        }),
      );
    });
  });

  it("handles network offline/connection drop gracefully", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.reject(new TypeError("Failed to fetch")),
    );
    vi.stubGlobal("fetch", fetchSpy);

    renderForgotPassword();
    const emailInput = await screen.findByRole("textbox", { name: /email/i });
    await user.type(emailInput, "offline@example.com");
    await user.click(screen.getByRole("button", { name: /send reset link/i }));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
