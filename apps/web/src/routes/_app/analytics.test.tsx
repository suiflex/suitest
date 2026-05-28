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

vi.mock("recharts", () => {
  const Pass = (props: { children?: React.ReactNode }) => <>{props.children}</>;
  return {
    ResponsiveContainer: Pass,
    LineChart: Pass,
    Line: () => null,
    XAxis: () => null,
    YAxis: () => null,
    Tooltip: () => null,
  };
});

function renderAnalytics() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/analytics"] }),
    context: { queryClient },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("Analytics screen", () => {
  beforeEach(() => {
    setCaps(ZERO_CAPS);
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({ id: "u_demo", email: "demo@suitest.dev", name: "Maya", memberships: [] }),
      ),
    );
    vi.stubGlobal("location", { pathname: "/analytics", assign: vi.fn(), origin: "http://localhost" });
  });
  afterEach(() => {
    resetCaps();
    vi.unstubAllGlobals();
  });

  it("renders the skeleton before analytics resolve", async () => {
    server.use(
      http.get("*/api/v1/analytics/readiness", async () => {
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json({ score: 0, blockers: [] });
      }),
    );
    renderAnalytics();
    expect(await screen.findByTestId("analytics-skeleton")).toBeInTheDocument();
  });

  it("renders gauges + trend + flaky + heatmap when data resolves", async () => {
    renderAnalytics();
    await screen.findByTestId("analytics-gauges", undefined, { timeout: 3000 });
    expect(screen.getAllByTestId("analytics-gauge-block").length).toBe(3);
    expect(screen.getByTestId("analytics-trend")).toBeInTheDocument();
    expect(screen.getByTestId("analytics-flaky")).toBeInTheDocument();
    expect(screen.getByTestId("analytics-heatmap-card")).toBeInTheDocument();
  });

  it("renders 14×20 = 280 heatmap cells", async () => {
    renderAnalytics();
    await screen.findByTestId("heatmap", undefined, { timeout: 3000 });
    const cells = screen.getAllByTestId("heatmap-cell");
    expect(cells.length).toBe(280);
  });

  it("renders empty flaky list when /analytics/flaky returns []", async () => {
    server.use(
      http.get("*/api/v1/analytics/flaky", () => HttpResponse.json({ items: [] })),
    );
    renderAnalytics();
    await screen.findByTestId("analytics-flaky", undefined, { timeout: 3000 });
    expect(screen.queryAllByTestId("analytics-flaky-row").length).toBe(0);
  });

  it("renders the error fallback when /analytics/readiness 500s", async () => {
    server.use(
      http.get("*/api/v1/analytics/readiness", () =>
        HttpResponse.json({ code: "BOOM", message: "nope" }, { status: 500 }),
      ),
    );
    renderAnalytics();
    expect(
      await screen.findByText(/Couldn't load analytics/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });
});
