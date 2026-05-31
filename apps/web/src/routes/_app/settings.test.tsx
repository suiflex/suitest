import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/mocks/server";
import { routeTree } from "@/routeTree.gen";
import { useActiveWorkspace } from "@/stores/use-active-workspace";
import { useCapabilities } from "@/stores/use-capabilities";
import { ZERO_CAPS } from "@/test/capabilities";

function meHandler(over: Record<string, unknown> = {}) {
  return http.get("*/api/v1/auth/me", () =>
    HttpResponse.json({
      id: "u_owner",
      email: "owner@suitest.dev",
      name: "Owner",
      avatar_url: null,
      must_change_password: false,
      is_superuser: false,
      memberships: [
        {
          workspace_id: "ws_1",
          role: "OWNER",
          workspace: { id: "ws_1", slug: "nusantara", name: "Nusantara Retail" },
        },
      ],
      ...over,
    }),
  );
}

function renderAt(path: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [path] }),
    context: { queryClient },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router };
}

describe("Settings → Account", () => {
  beforeEach(() => {
    useActiveWorkspace.setState({ workspaceId: "ws_1" });
    useCapabilities.setState({ capabilities: ZERO_CAPS, loading: false, error: null });
    server.use(meHandler());
    vi.stubGlobal("location", { pathname: "/settings", assign: vi.fn(), origin: "http://localhost" });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    useActiveWorkspace.setState({ workspaceId: null });
  });

  it("renders the password-change form", async () => {
    renderAt("/settings");
    expect(await screen.findByLabelText(/current password/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/^new password$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/confirm new password/i)).toBeInTheDocument();
  });

  it("validates the confirmation match before submitting", async () => {
    renderAt("/settings");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/current password/i), "oldpassword");
    await user.type(screen.getByLabelText(/^new password$/i), "newpassword1");
    await user.type(screen.getByLabelText(/confirm new password/i), "different123");
    await user.click(screen.getByTestId("change-password-submit"));
    expect(await screen.findByText(/do not match/i)).toBeInTheDocument();
  });

  it("submits a valid password change and shows success", async () => {
    let body: unknown = null;
    server.use(
      http.patch("*/api/v1/users/me/password", async ({ request }) => {
        body = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderAt("/settings");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/current password/i), "oldpassword");
    await user.type(screen.getByLabelText(/^new password$/i), "newpassword1");
    await user.type(screen.getByLabelText(/confirm new password/i), "newpassword1");
    await user.click(screen.getByTestId("change-password-submit"));
    await waitFor(() => {
      expect(body).toEqual({ current_password: "oldpassword", new_password: "newpassword1" });
    });
    expect(await screen.findByText(/password changed/i)).toBeInTheDocument();
  });

  it("surfaces a wrong-current-password 400 as an error", async () => {
    server.use(
      http.patch("*/api/v1/users/me/password", () =>
        HttpResponse.json({ code: "INVALID_PASSWORD", message: "wrong" }, { status: 400 }),
      ),
    );
    renderAt("/settings");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/current password/i), "wrongpassword");
    await user.type(screen.getByLabelText(/^new password$/i), "newpassword1");
    await user.type(screen.getByLabelText(/confirm new password/i), "newpassword1");
    await user.click(screen.getByTestId("change-password-submit"));
    expect(await screen.findByText(/current password is incorrect/i)).toBeInTheDocument();
  });

  it("shows the force-password banner when must_change_password is set", async () => {
    server.use(meHandler({ must_change_password: true }));
    renderAt("/settings?force_password=1");
    expect(await screen.findByTestId("force-password-banner")).toBeInTheDocument();
  });
});
