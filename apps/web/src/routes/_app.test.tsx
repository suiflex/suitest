import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/mocks/server";
import { routeTree } from "@/routeTree.gen";
import { useActiveWorkspace } from "@/stores/use-active-workspace";
import { useCapabilities } from "@/stores/use-capabilities";

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
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
  return { router, queryClient };
}

describe("<_app> route guard", () => {
  beforeEach(() => {
    // Reset cross-test global stores so a prior test's seeded workspace /
    // capabilities don't leak into this one (zustand stores are module-level).
    useActiveWorkspace.setState({ workspaceId: null });
    useCapabilities.setState({ capabilities: null, loading: true, error: null });
    // axios api-client interceptor will call window.location.assign on 401;
    // stub it so the test doesn't navigate the jsdom window itself (we want
    // to assert the router-level redirect, not the interceptor's).
    vi.stubGlobal("location", {
      pathname: "/dashboard",
      assign: vi.fn(),
      origin: "http://localhost",
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("redirects to /login when /auth/me returns 401", async () => {
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({ code: "UNAUTHORIZED", message: "nope" }, { status: 401 }),
      ),
    );

    const { router } = renderAt("/dashboard");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/login");
    });
    // Search should carry `next` so login can bounce the user back.
    expect(router.state.location.search).toMatchObject({ next: "/dashboard" });
  });

  it("renders the protected child when /auth/me returns 200", async () => {
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({
          id: "u_demo",
          email: "demo@suitest.dev",
          name: "Demo",
          avatar_url: null,
          memberships: [],
        }),
      ),
    );

    const { router } = renderAt("/dashboard");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/dashboard");
    });
    // A user with zero workspaces is NOT bounced to /login (the guard skips the
    // workspace-scoped /projects fetch); the protected shell renders and the
    // create-workspace flow auto-opens so they can bootstrap from the UI.
    expect(await screen.findByTestId("create-workspace-dialog")).toBeInTheDocument();
  });

  it("redirects on network failure (no response)", async () => {
    server.use(http.get("*/api/v1/auth/me", () => HttpResponse.error()));

    const { router } = renderAt("/dashboard");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/login");
    });
  });

  it("redirects to /settings?force_password=1 when must_change_password is set", async () => {
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({
          id: "u_reset",
          email: "reset@suitest.dev",
          name: "Reset User",
          avatar_url: null,
          must_change_password: true,
          is_superuser: false,
          memberships: [],
        }),
      ),
    );

    const { router } = renderAt("/dashboard");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/settings");
    });
    expect(router.state.location.search).toMatchObject({ force_password: "1" });
  });

  it("does NOT bounce a must_change_password user already on /settings", async () => {
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({
          id: "u_reset",
          email: "reset@suitest.dev",
          name: "Reset User",
          avatar_url: null,
          must_change_password: true,
          is_superuser: false,
          memberships: [],
        }),
      ),
    );

    const { router } = renderAt("/settings");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/settings");
    });
  });
});

describe("<index> redirect", () => {
  beforeEach(() => {
    vi.stubGlobal("location", {
      pathname: "/",
      assign: vi.fn(),
      origin: "http://localhost",
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("redirects / → /dashboard (then through _app guard)", async () => {
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({
          id: "u_demo",
          email: "demo@suitest.dev",
          name: null,
          avatar_url: null,
          memberships: [],
        }),
      ),
    );

    const { router } = renderAt("/");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/dashboard");
    });
  });
});
