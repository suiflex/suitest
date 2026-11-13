import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { routeTree } from "@/routeTree.gen";

function renderResetPassword(initialPath = "/reset-password?token=valid-token"): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [initialPath] }),
    context: { queryClient },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("<ResetPasswordRoute>", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("displays missing token warning when no token in search params", async () => {
    renderResetPassword("/reset-password");
    expect(await screen.findByTestId("missing-token-warning")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to sign in/i })).toHaveAttribute(
      "href",
      "/login",
    );
  });

  it("renders new password inputs when token is provided", async () => {
    renderResetPassword("/reset-password?token=valid-token");
    expect(await screen.findByLabelText(/^new password$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^confirm new password$/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /reset password/i }),
    ).toBeInTheDocument();
  });

  it("validates password length and match before submitting", async () => {
    const user = userEvent.setup();
    renderResetPassword("/reset-password?token=valid-token");

    const passInput = await screen.findByLabelText(/^new password$/i);
    const confirmInput = screen.getByLabelText(/^confirm new password$/i);
    const submitBtn = screen.getByRole("button", { name: /reset password/i });

    // Short password
    await user.type(passInput, "short");
    await user.type(confirmInput, "short");
    await user.click(submitBtn);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /must be at least 8 characters/i,
    );

    // Mismatched password
    await user.clear(passInput);
    await user.clear(confirmInput);
    await user.type(passInput, "validpassword123");
    await user.type(confirmInput, "differentpassword123");
    await user.click(submitBtn);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /passwords do not match/i,
    );
  });

  it("submits token and password to /auth/reset-password and displays success state", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.resolve(new Response(null, { status: 200 })),
    );
    vi.stubGlobal("fetch", fetchSpy);

    renderResetPassword("/reset-password?token=valid-token");

    const passInput = await screen.findByLabelText(/^new password$/i);
    const confirmInput = screen.getByLabelText(/^confirm new password$/i);
    const submitBtn = screen.getByRole("button", { name: /reset password/i });

    await user.type(passInput, "newPassword123!");
    await user.type(confirmInput, "newPassword123!");
    await user.click(submitBtn);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/auth/reset-password",
        expect.objectContaining({
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            token: "valid-token",
            password: "newPassword123!",
          }),
        }),
      );
    });

    expect(
      await screen.findByTestId("reset-password-success-title"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /back to sign in/i }),
    ).toBeInTheDocument();
  });

  it("displays error message when token is invalid or expired", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.resolve(new Response("Bad token", { status: 400 })),
    );
    vi.stubGlobal("fetch", fetchSpy);

    renderResetPassword("/reset-password?token=expired-token");

    const passInput = await screen.findByLabelText(/^new password$/i);
    const confirmInput = screen.getByLabelText(/^confirm new password$/i);
    const submitBtn = screen.getByRole("button", { name: /reset password/i });

    await user.type(passInput, "newPassword123!");
    await user.type(confirmInput, "newPassword123!");
    await user.click(submitBtn);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /invalid or has expired/i,
    );
  });

  it("handles whitespace-only token as missing token", async () => {
    renderResetPassword("/reset-password?token=%20%20%20");
    expect(await screen.findByTestId("missing-token-warning")).toBeInTheDocument();
  });

  it("handles network failure / connection drop gracefully", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.reject(new TypeError("Failed to fetch")),
    );
    vi.stubGlobal("fetch", fetchSpy);

    renderResetPassword("/reset-password?token=valid-token");

    const passInput = await screen.findByLabelText(/^new password$/i);
    const confirmInput = screen.getByLabelText(/^confirm new password$/i);
    const submitBtn = screen.getByRole("button", { name: /reset password/i });

    await user.type(passInput, "newPassword123!");
    await user.type(confirmInput, "newPassword123!");
    await user.click(submitBtn);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
