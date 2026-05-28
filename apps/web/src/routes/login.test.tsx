import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  RouterProvider,
  createMemoryHistory,
  createRouter,
} from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/mocks/server";
import { routeTree } from "@/routeTree.gen";

function makeRouter(initialPath: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [initialPath] }),
    context: { queryClient },
  });
}

function renderLogin(initialPath = "/login"): { queryClient: QueryClient } {
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
  return { queryClient };
}

describe("<LoginRoute>", () => {
  beforeEach(() => {
    vi.stubGlobal("location", {
      pathname: "/login",
      assign: vi.fn(),
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders 'Sign in with Google' button", async () => {
    renderLogin();
    expect(
      await screen.findByRole("button", { name: /sign in with google/i }),
    ).toBeInTheDocument();
  });

  it("fetches authorize endpoint and assigns returned URL on click", async () => {
    const authorizeUrl = "https://accounts.google.com/o/oauth2/v2/auth?client_id=abc";
    const fetchSpy = vi.fn((_url: string) =>
      Promise.resolve(
        new Response(JSON.stringify({ authorization_url: authorizeUrl }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchSpy);

    renderLogin();

    const btn = await screen.findByRole("button", { name: /sign in with google/i });
    await userEvent.click(btn);

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledTimes(1);
    });
    const calledUrl = fetchSpy.mock.calls[0]?.[0] ?? "";
    // Backend mounts the OAuth router at the application root, NOT under
    // `/api/v1` (verified in packages/shared/openapi.json).
    expect(calledUrl).toContain("/auth/google/authorize");
    expect(calledUrl).not.toContain("/api/v1/auth/google/authorize");
    expect(calledUrl).toContain("next=%2Fdashboard");

    await waitFor(() => {
      expect(window.location.assign).toHaveBeenCalledWith(authorizeUrl);
    });
  });

  it("uses `next` search param as the redirect target", async () => {
    const fetchSpy = vi.fn((_url: string) =>
      Promise.resolve(
        new Response(JSON.stringify({ authorization_url: "https://x.test/" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchSpy);

    renderLogin("/login?next=%2Fcases");

    const btn = await screen.findByRole("button", { name: /sign in with google/i });
    expect(screen.getByText("/cases")).toBeInTheDocument();
    await userEvent.click(btn);

    await waitFor(() => {
      const calledUrl = fetchSpy.mock.calls[0]?.[0] ?? "";
      expect(calledUrl).toContain("next=%2Fcases");
    });
  });

  it("does not assign when authorize endpoint errors", async () => {
    const fetchSpy = vi.fn((_url: string) =>
      Promise.resolve(new Response("server down", { status: 500 })),
    );
    vi.stubGlobal("fetch", fetchSpy);
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    renderLogin();
    await userEvent.click(
      await screen.findByRole("button", { name: /sign in with google/i }),
    );

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });
    expect(window.location.assign).not.toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  // Smoke check that the route tree builds and the router can render this
  // public route without the auth handlers firing.
  it("route tree resolves without invoking /auth/me on /login", async () => {
    let authHit = false;
    server.use(
      http.get("*/api/v1/auth/me", () => {
        authHit = true;
        return HttpResponse.json({}, { status: 401 });
      }),
    );

    const router = makeRouter("/login");
    expect(router).toBeDefined();
    renderLogin("/login");
    await screen.findByRole("button", { name: /sign in with google/i });
    expect(authHit).toBe(false);
  });
});
