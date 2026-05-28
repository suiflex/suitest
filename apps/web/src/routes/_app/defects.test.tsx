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
import { CLOUD_CAPS, ZERO_CAPS, resetCaps, setCaps } from "@/test/capabilities";

function renderDefects() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/defects"] }),
    context: { queryClient },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("Defects screen", () => {
  beforeEach(() => {
    setCaps(ZERO_CAPS);
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({ id: "u_demo", email: "demo@suitest.dev", name: "Maya", memberships: [] }),
      ),
    );
    vi.stubGlobal("location", { pathname: "/defects", assign: vi.fn(), origin: "http://localhost" });
  });
  afterEach(() => {
    resetCaps();
    vi.unstubAllGlobals();
  });

  it("renders the skeleton before /defects resolves", async () => {
    server.use(
      http.get("*/api/v1/defects", async () => {
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json({ items: [], meta: { limit: 50, nextCursor: null } });
      }),
    );
    renderDefects();
    expect(await screen.findByTestId("defects-skeleton")).toBeInTheDocument();
  });

  it("renders defect cards when there is data", async () => {
    renderDefects();
    const list = await screen.findByTestId("defects-list", undefined, { timeout: 3000 });
    expect(list.querySelectorAll('[data-testid="defect-card"]').length).toBeGreaterThanOrEqual(2);
  });

  it("renders the empty state when there are no defects", async () => {
    server.use(
      http.get("*/api/v1/defects", () =>
        HttpResponse.json({ items: [], meta: { limit: 50, nextCursor: null } }),
      ),
    );
    renderDefects();
    expect(
      await screen.findByText(/No open defects/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("renders the error fallback when /defects 500s", async () => {
    server.use(
      http.get("*/api/v1/defects", () =>
        HttpResponse.json({ code: "BOOM", message: "nope" }, { status: 500 }),
      ),
    );
    renderDefects();
    expect(
      await screen.findByText(/Couldn't load defects/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("ZERO tier: each defect renders 'Manual triage' card, no agent callout, no auto-filed badge", async () => {
    renderDefects();
    await screen.findByTestId("defects-list", undefined, { timeout: 3000 });
    expect(screen.getAllByTestId("defect-manual-triage").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("agent-insight")).toBeNull();
    expect(screen.queryByTestId("defects-auto-filed")).toBeNull();
  });

  it("CLOUD tier: agent diagnosis callout + auto-filed badge render", async () => {
    setCaps(CLOUD_CAPS);
    server.use(
      http.get("*/capabilities", () => HttpResponse.json(CLOUD_CAPS)),
      http.get("*/api/v1/capabilities", () => HttpResponse.json(CLOUD_CAPS)),
    );
    renderDefects();
    await screen.findByTestId("defects-list", undefined, { timeout: 3000 });
    expect(screen.getAllByTestId("agent-insight").length).toBeGreaterThan(0);
    expect(screen.queryByTestId("defects-auto-filed")).toBeInTheDocument();
  });
});
