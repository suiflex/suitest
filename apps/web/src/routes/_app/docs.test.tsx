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

function renderDocs() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/docs"] }),
    context: { queryClient },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("Docs screen", () => {
  beforeEach(() => {
    setCaps(ZERO_CAPS);
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({ id: "u_demo", email: "demo@suitest.dev", name: "Maya", memberships: [] }),
      ),
    );
    vi.stubGlobal("location", { pathname: "/docs", assign: vi.fn(), origin: "http://localhost" });
  });
  afterEach(() => {
    resetCaps();
    vi.unstubAllGlobals();
  });

  it("renders the skeleton before /documents resolves", async () => {
    server.use(
      http.get("*/api/v1/documents", async () => {
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json({ items: [], meta: { limit: 50, nextCursor: null } });
      }),
    );
    renderDocs();
    expect(await screen.findByTestId("docs-skeleton")).toBeInTheDocument();
  });

  it("renders 2-col grid of doc cards when data resolves", async () => {
    renderDocs();
    await screen.findByTestId("docs-grid", undefined, { timeout: 3000 });
    expect(screen.getAllByTestId("doc-card").length).toBeGreaterThan(0);
  });

  it("renders the empty state when there are no docs", async () => {
    server.use(
      http.get("*/api/v1/documents", () =>
        HttpResponse.json({ items: [], meta: { limit: 50, nextCursor: null } }),
      ),
    );
    renderDocs();
    expect(
      await screen.findByText(/No sources connected/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("renders the error fallback when /documents 500s", async () => {
    server.use(
      http.get("*/api/v1/documents", () =>
        HttpResponse.json({ code: "BOOM", message: "nope" }, { status: 500 }),
      ),
    );
    renderDocs();
    expect(
      await screen.findByText(/Couldn't load documents/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("ZERO tier: every card uses 'FTS' indexing label", async () => {
    renderDocs();
    await screen.findByTestId("docs-grid", undefined, { timeout: 3000 });
    const labels = screen.getAllByTestId("doc-indexing-label");
    expect(labels.length).toBeGreaterThan(0);
    for (const el of labels) {
      expect(el.textContent).toBe("FTS");
    }
  });

  it("CLOUD tier: cards use 'Semantic' indexing label", async () => {
    setCaps(CLOUD_CAPS);
    server.use(
      http.get("*/capabilities", () => HttpResponse.json(CLOUD_CAPS)),
      http.get("*/api/v1/capabilities", () => HttpResponse.json(CLOUD_CAPS)),
    );
    renderDocs();
    await screen.findByTestId("docs-grid", undefined, { timeout: 3000 });
    const labels = screen.getAllByTestId("doc-indexing-label");
    for (const el of labels) {
      expect(el.textContent).toBe("Semantic");
    }
  });
});
