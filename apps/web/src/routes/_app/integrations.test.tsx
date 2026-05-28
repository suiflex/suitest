import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  RouterProvider,
  createMemoryHistory,
  createRouter,
} from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/mocks/server";
import { routeTree } from "@/routeTree.gen";
import { ZERO_CAPS, resetCaps, setCaps } from "@/test/capabilities";

function renderIntegrations() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/integrations"] }),
    context: { queryClient },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("Integrations screen", () => {
  beforeEach(() => {
    setCaps(ZERO_CAPS);
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({ id: "u_demo", email: "demo@suitest.dev", name: "Maya", memberships: [] }),
      ),
    );
    vi.stubGlobal("location", { pathname: "/integrations", assign: vi.fn(), origin: "http://localhost" });
  });
  afterEach(() => {
    resetCaps();
    vi.unstubAllGlobals();
  });

  it("renders the skeleton before integrations resolve", async () => {
    server.use(
      http.get("*/api/v1/integrations", async () => {
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json({ items: [], meta: { limit: 50, nextCursor: null } });
      }),
    );
    renderIntegrations();
    expect(await screen.findByTestId("integrations-skeleton")).toBeInTheDocument();
  });

  it("renders integrations grid + MCP grid when data resolves", async () => {
    renderIntegrations();
    await screen.findByTestId("integrations-grid", undefined, { timeout: 3000 });
    expect(screen.getAllByTestId("integration-card").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("mcp-card").length).toBeGreaterThan(0);
  });

  it("renders empty state when there are zero integrations in a filtered tab", async () => {
    server.use(
      http.get("*/api/v1/integrations", () =>
        HttpResponse.json({ items: [], meta: { limit: 50, nextCursor: null } }),
      ),
      http.get("*/api/v1/mcp/providers", () => HttpResponse.json({ items: [] })),
    );
    renderIntegrations();
    expect(
      await screen.findByText(/No integrations in this category/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("renders the error fallback when /integrations 500s", async () => {
    server.use(
      http.get("*/api/v1/integrations", () =>
        HttpResponse.json({ code: "BOOM", message: "nope" }, { status: 500 }),
      ),
    );
    renderIntegrations();
    expect(
      await screen.findByText(/Couldn't load integrations/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("ZERO tier: MCP tab is visible (deterministic, not AI-gated)", async () => {
    renderIntegrations();
    expect(
      await screen.findByTestId("integrations-tab-mcp", undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("MCP cards render with BUNDLED badge", async () => {
    renderIntegrations();
    await screen.findByTestId("mcp-grid", undefined, { timeout: 3000 });
    expect(screen.getAllByTestId("mcp-bundled").length).toBeGreaterThan(0);
  });
});
