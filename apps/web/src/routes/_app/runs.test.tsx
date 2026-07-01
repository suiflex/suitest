import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/mocks/server";
import { routeTree } from "@/routeTree.gen";
import { ZERO_CAPS, resetCaps, setCaps } from "@/test/capabilities";

function renderRuns(path = "/runs") {
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

describe("Test Runs screen", () => {
  beforeEach(() => {
    setCaps(ZERO_CAPS);
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({
          id: "u_demo",
          email: "demo@suitest.dev",
          name: "Maya",
          memberships: [
            {
              workspace_id: "ws_1",
              role: "OWNER",
              workspace: { id: "ws_1", slug: "demo", name: "Demo" },
            },
          ],
        }),
      ),
    );
    vi.stubGlobal("location", {
      pathname: "/runs",
      assign: vi.fn(),
      origin: "http://localhost",
    });
  });
  afterEach(() => {
    resetCaps();
    vi.unstubAllGlobals();
  });

  it("renders the skeleton before the summary/list resolve", async () => {
    server.use(
      http.get("*/api/v1/runs/summary", async () => {
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json({
          activeNow: 0,
          today: 0,
          passed: 0,
          failed: 0,
          avgDurationMs: 0,
          queue: 0,
        });
      }),
    );
    renderRuns();
    expect(await screen.findByTestId("runs-skeleton")).toBeInTheDocument();
  });

  it("renders the summary bar + list when data resolves", async () => {
    renderRuns();
    await screen.findByTestId("runs-summary", undefined, { timeout: 3000 });
    expect(screen.getByTestId("runs-list")).toBeInTheDocument();
    expect(screen.getAllByTestId("runs-row").length).toBeGreaterThan(0);
  });

  it("renders the empty state when there are no runs", async () => {
    server.use(
      http.get("*/api/v1/runs", () =>
        HttpResponse.json({ items: [], meta: { limit: 50, nextCursor: null } }),
      ),
    );
    renderRuns();
    expect(
      await screen.findByText(/No runs yet/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("renders the error fallback when /runs/summary 500s", async () => {
    server.use(
      http.get("*/api/v1/runs/summary", () =>
        HttpResponse.json({ code: "BOOM", message: "nope" }, { status: 500 }),
      ),
    );
    renderRuns();
    expect(
      await screen.findByText(/Couldn't load runs/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("run detail panel shows the case-first evidence view", async () => {
    const user = userEvent.setup();
    renderRuns();
    const rows = await screen.findAllByTestId("runs-row", undefined, { timeout: 3000 });
    await user.click(rows[0] as HTMLElement);
    await screen.findByTestId("run-detail", undefined, { timeout: 3000 });
    // The panel now renders the shared case master-detail (not raw step tabs).
    expect(
      await screen.findByTestId("run-case-master", undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
    expect(
      await screen.findByTestId("case-list", undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("renders the cost footer with '$0 · deterministic' in ZERO", async () => {
    const user = userEvent.setup();
    renderRuns();
    const rows = await screen.findAllByTestId("runs-row", undefined, { timeout: 3000 });
    await user.click(rows[0] as HTMLElement);
    const footer = await screen.findByTestId("run-cost-footer", undefined, { timeout: 3000 });
    expect(footer).toHaveTextContent(/deterministic/i);
  });
});
