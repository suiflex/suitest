import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/mocks/server";
import { routeTree } from "@/routeTree.gen";
import { useActiveWorkspace } from "@/stores/use-active-workspace";
import { useCapabilities } from "@/stores/use-capabilities";
import { ZERO_CAPS } from "@/test/capabilities";

function meHandler(isSuperuser: boolean) {
  return http.get("*/api/v1/auth/me", () =>
    HttpResponse.json({
      id: "u_admin",
      email: "admin@suitest.dev",
      name: "Admin",
      avatar_url: null,
      must_change_password: false,
      is_superuser: isSuperuser,
      memberships: [
        {
          workspace_id: "ws_1",
          role: "OWNER",
          workspace: { id: "ws_1", slug: "nusantara", name: "Nusantara Retail" },
        },
      ],
    }),
  );
}

const member = {
  user_id: "u_target",
  email: "qa@example.test",
  name: "QA Person",
  role: "QA",
  joined_at: "2026-05-01T00:00:00Z",
};

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

describe("Admin → Users", () => {
  beforeEach(() => {
    useActiveWorkspace.setState({ workspaceId: "ws_1" });
    useCapabilities.setState({ capabilities: ZERO_CAPS, loading: false, error: null });
    server.use(http.get("*/api/v1/workspaces/ws_1/members", () => HttpResponse.json([member])));
    vi.stubGlobal("location", { pathname: "/admin", assign: vi.fn(), origin: "http://localhost" });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    useActiveWorkspace.setState({ workspaceId: null });
  });

  it("redirects non-superusers to /dashboard", async () => {
    server.use(meHandler(false));
    const { router } = renderAt("/admin");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/dashboard");
    });
  });

  it("renders the users table for a superuser", async () => {
    server.use(meHandler(true));
    renderAt("/admin");
    expect(await screen.findByText("qa@example.test")).toBeInTheDocument();
  });

  it("resets a user's password and shows the one-time temp password", async () => {
    server.use(
      meHandler(true),
      http.post("*/api/v1/admin/users/u_target/reset-password", () =>
        HttpResponse.json({ temporaryPassword: "Tmp-One-Time-9" }),
      ),
    );
    renderAt("/admin");
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("reset-u_target"));
    const temp = await screen.findByTestId("temp-password");
    expect(temp).toHaveTextContent("Tmp-One-Time-9");
    expect(screen.getByText(/will not be shown again/i)).toBeInTheDocument();

    await user.click(screen.getByTestId("copy-button"));
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });

  it("shows the empty state when encryption is not configured", async () => {
    server.use(
      meHandler(true),
      http.get("*/api/v1/admin/password-reset-requests", () =>
        HttpResponse.json(
          { code: "ENCRYPTION_NOT_CONFIGURED", message: "no key" },
          { status: 503 },
        ),
      ),
    );
    renderAt("/admin");
    expect(await screen.findByTestId("encryption-not-configured")).toBeInTheDocument();
  });

  it("lists reset requests with copyable links when encryption is configured", async () => {
    server.use(
      meHandler(true),
      http.get("*/api/v1/admin/password-reset-requests", () =>
        HttpResponse.json({
          items: [
            {
              id: "prr_1",
              email: "lost@example.test",
              expires_at: "2099-06-01T00:00:00Z",
              created_at: "2026-05-31T00:00:00Z",
              used_at: null,
              resetLink: "http://localhost/reset?token=abc",
            },
          ],
        }),
      ),
    );
    renderAt("/admin");
    const row = await screen.findByTestId("reset-request-row");
    expect(within(row).getByText(/reset\?token=abc/)).toBeInTheDocument();
  });
});
