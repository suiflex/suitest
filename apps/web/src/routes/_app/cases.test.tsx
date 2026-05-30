import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  RouterProvider,
  createMemoryHistory,
  createRouter,
} from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/mocks/server";
import { routeTree } from "@/routeTree.gen";
import { CLOUD_CAPS, ZERO_CAPS, resetCaps, setCaps } from "@/test/capabilities";

function renderCases(path = "/cases") {
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
  return router;
}

describe("Test Cases screen", () => {
  beforeEach(() => {
    setCaps(ZERO_CAPS);
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({ id: "u_demo", email: "demo@suitest.dev", name: "Maya", memberships: [] }),
      ),
    );
    vi.stubGlobal("location", {
      pathname: "/cases",
      assign: vi.fn(),
      origin: "http://localhost",
    });
  });
  afterEach(() => {
    resetCaps();
    vi.unstubAllGlobals();
  });

  it("renders the skeleton before suites/cases resolve", async () => {
    server.use(
      http.get("*/api/v1/suites", async () => {
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json({ items: [] });
      }),
    );
    renderCases();
    expect(await screen.findByTestId("cases-skeleton")).toBeInTheDocument();
  });

  it("ZERO tier: shows 4 tabs (no AI-generated)", async () => {
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });
    expect(screen.getByTestId("cases-tab-all")).toBeInTheDocument();
    expect(screen.getByTestId("cases-tab-manual")).toBeInTheDocument();
    expect(screen.queryByTestId("cases-tab-ai")).toBeNull();
    expect(screen.getByTestId("cases-tab-mcp")).toBeInTheDocument();
    expect(screen.getByTestId("cases-tab-failing")).toBeInTheDocument();
  });

  it("CLOUD tier: shows 5 tabs including AI-generated", async () => {
    setCaps(CLOUD_CAPS);
    server.use(
      http.get("*/capabilities", () => HttpResponse.json(CLOUD_CAPS)),
      http.get("*/api/v1/capabilities", () => HttpResponse.json(CLOUD_CAPS)),
    );
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });
    expect(screen.getByTestId("cases-tab-ai")).toBeInTheDocument();
  });

  it("renders the tree grouped by suite", async () => {
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });
    const rows = screen.getAllByTestId("cases-tree-row");
    expect(rows.length).toBeGreaterThan(0);
    expect(rows[0]?.getAttribute("data-public-id")).toBe("TC-101");
  });

  it("renders the empty state when there are zero cases", async () => {
    server.use(
      http.get("*/api/v1/test-cases", () =>
        HttpResponse.json({ items: [], meta: { limit: 50, nextCursor: null } }),
      ),
    );
    renderCases();
    expect(
      await screen.findByText(/No cases yet/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("renders the error fallback when /suites 500s", async () => {
    server.use(
      http.get("*/api/v1/suites", () =>
        HttpResponse.json({ code: "BOOM", message: "nope" }, { status: 500 }),
      ),
    );
    renderCases();
    expect(
      await screen.findByText(/Couldn't load cases/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("clicking a tree row loads detail panel via ?case= param", async () => {
    const user = userEvent.setup();
    renderCases();
    const rows = await screen.findAllByTestId("cases-tree-row", undefined, { timeout: 3000 });
    await user.click(rows[0] as HTMLElement);
    expect(
      await screen.findByTestId("case-detail", undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId("step-row").length).toBeGreaterThan(0);
  });
});
