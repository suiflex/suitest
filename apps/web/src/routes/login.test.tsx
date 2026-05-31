import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/mocks/server";
import { routeTree } from "@/routeTree.gen";
import { type Capabilities, useCapabilities } from "@/stores/use-capabilities";

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

/**
 * Seed the capabilities store directly so the Google-button visibility is
 * deterministic. (The login route also lazy-fetches capabilities, but seeding
 * avoids a fetch race when `window.fetch` is stubbed for the Google flow.)
 */
function mockOAuth(enabled: boolean): void {
  const caps: Capabilities = {
    tier: "ZERO",
    llm: { provider: null, model: null, base_url: null, is_test_provider: false },
    embeddings: { enabled: false, backend: "none", model: null, dim: null },
    features: {
      manual_tcm: true,
      deterministic_runner: true,
      deterministic_generator_openapi: true,
      deterministic_generator_recorder: false,
      deterministic_generator_crawler: false,
      ai_generation: false,
      ai_execution_agentic: false,
      ai_diagnose: false,
      ai_conversation: false,
      semantic_search: false,
      fts_search: true,
      auto_defect_filing_ai: false,
      auto_defect_filing_rule: true,
    },
    autonomy: { available: ["manual"], default: "manual" },
    auth: { google_oauth_enabled: enabled },
    version: "0.5.0",
    build: null,
  };
  // Seed the store AND override the MSW `/capabilities` handler so the login
  // route's lazy fetch (which runs because the store may have been reset to
  // null by another test) resolves to the same auth config instead of the
  // default fixture (which has no `auth` section).
  useCapabilities.setState({ capabilities: caps, loading: false, error: null });
  server.use(http.get("*/capabilities", () => HttpResponse.json(caps)));
}

describe("<LoginRoute>", () => {
  beforeEach(() => {
    // Reset the global capabilities store between tests so OAuth visibility is
    // driven by each test's mock, not a previous test's fetch.
    useCapabilities.setState({ capabilities: null, loading: true, error: null });
    vi.stubGlobal("location", {
      pathname: "/login",
      assign: vi.fn(),
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders email/password login first", async () => {
    renderLogin();
    expect(await screen.findByRole("textbox", { name: /email/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^sign in$/i })).toBeInTheDocument();
  });

  it("renders the Google button only when OAuth is configured", async () => {
    mockOAuth(true);
    renderLogin();
    expect(await screen.findByRole("button", { name: /sign in with google/i })).toBeInTheDocument();
  });

  it("hides the Google button when OAuth is not configured", async () => {
    mockOAuth(false);
    renderLogin();
    await screen.findByRole("textbox", { name: /email/i });
    expect(screen.queryByRole("button", { name: /sign in with google/i })).not.toBeInTheDocument();
  });

  it("hides the Google button while capabilities are still loading", async () => {
    // Store left null by beforeEach. The default `/capabilities` fixture has no
    // `auth` section, so the button stays hidden after the lazy fetch resolves.
    renderLogin();
    await screen.findByRole("textbox", { name: /email/i });
    expect(screen.queryByRole("button", { name: /sign in with google/i })).not.toBeInTheDocument();
  });

  it("posts form-encoded credentials to cookie login and redirects to dashboard", async () => {
    const fetchSpy = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.resolve(new Response(null, { status: 204 })),
    );
    vi.stubGlobal("fetch", fetchSpy);

    renderLogin();

    const user = userEvent.setup();
    await user.type(await screen.findByRole("textbox", { name: /email/i }), "maya@example.test");
    await user.type(screen.getByLabelText(/password/i), "correct horse");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/auth/cookie/login",
        expect.objectContaining({
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
        }),
      );
    });
    const body = fetchSpy.mock.calls[0]?.[1]?.body;
    expect(body).toBeInstanceOf(URLSearchParams);
    expect((body as URLSearchParams).get("username")).toBe("maya@example.test");
    expect((body as URLSearchParams).get("password")).toBe("correct horse");
    expect(window.location.assign).toHaveBeenCalledWith("/dashboard");
  });

  it("uses `next` search param after password login", async () => {
    const fetchSpy = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));
    vi.stubGlobal("fetch", fetchSpy);

    renderLogin("/login?next=%2Fcases");

    const user = userEvent.setup();
    await user.type(await screen.findByRole("textbox", { name: /email/i }), "maya@example.test");
    await user.type(screen.getByLabelText(/password/i), "correct horse");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));

    await waitFor(() => {
      expect(window.location.assign).toHaveBeenCalledWith("/cases");
    });
  });

  it("renders a friendly error when password login fails", async () => {
    const fetchSpy = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ detail: "LOGIN_BAD_CREDENTIALS" }), {
          status: 400,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchSpy);

    renderLogin();

    const user = userEvent.setup();
    await user.type(await screen.findByRole("textbox", { name: /email/i }), "maya@example.test");
    await user.type(screen.getByLabelText(/password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /^sign in$/i }));

    expect(await screen.findByText(/email or password did not match/i)).toBeInTheDocument();
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("fetches authorize endpoint and assigns returned URL on click", async () => {
    mockOAuth(true);
    const authorizeUrl = "https://accounts.google.com/o/oauth2/v2/auth?client_id=abc";
    const fetchSpy = vi.fn((url: string) => {
      // The capabilities fetch goes through axios (not window.fetch); the only
      // window.fetch caller here is the Google authorize click.
      if (typeof url === "string" && url.includes("/auth/google/authorize")) {
        return Promise.resolve(
          new Response(JSON.stringify({ authorization_url: authorizeUrl }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(new Response(null, { status: 204 }));
    });
    vi.stubGlobal("fetch", fetchSpy);

    renderLogin();

    const btn = await screen.findByRole("button", { name: /sign in with google/i });
    await userEvent.click(btn);

    await waitFor(() => {
      expect(window.location.assign).toHaveBeenCalledWith(authorizeUrl);
    });
    const calledUrl = fetchSpy.mock.calls.find((c) =>
      String(c[0]).includes("/auth/google/authorize"),
    )?.[0];
    // Backend mounts the OAuth router at the application root, NOT under /api/v1.
    expect(calledUrl).toContain("/auth/google/authorize");
    expect(calledUrl).not.toContain("/api/v1/auth/google/authorize");
    expect(calledUrl).toContain("next=%2Fdashboard");
  });

  it("uses `next` search param as the redirect target", async () => {
    mockOAuth(true);
    const fetchSpy = vi.fn((url: string) => {
      if (typeof url === "string" && url.includes("/auth/google/authorize")) {
        return Promise.resolve(
          new Response(JSON.stringify({ authorization_url: "https://x.test/" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(new Response(null, { status: 204 }));
    });
    vi.stubGlobal("fetch", fetchSpy);

    renderLogin("/login?next=%2Fcases");

    const btn = await screen.findByRole("button", { name: /sign in with google/i });
    await userEvent.click(btn);

    await waitFor(() => {
      const calledUrl = fetchSpy.mock.calls.find((c) =>
        String(c[0]).includes("/auth/google/authorize"),
      )?.[0];
      expect(calledUrl).toContain("next=%2Fcases");
    });
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
    await screen.findByRole("textbox", { name: /email/i });
    expect(authHit).toBe(false);
  });
});
