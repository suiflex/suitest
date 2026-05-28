import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  RouterProvider,
  createMemoryHistory,
  createRouter,
} from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/mocks/server";
import { routeTree } from "@/routeTree.gen";
import { CLOUD_CAPS, ZERO_CAPS, resetCaps, setCaps } from "@/test/capabilities";

// Recharts doesn't play well with jsdom (ResponsiveContainer needs layout).
// Stub the modules used by the dashboard chart so the lazy import resolves
// to noop components that still render their children.
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

const ME = {
  id: "u_demo",
  email: "demo@suitest.dev",
  name: "Maya Demo",
  avatar_url: null,
  memberships: [],
};

function meHandler() {
  return http.get("*/api/v1/auth/me", () => HttpResponse.json(ME));
}

function renderDashboard() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/dashboard"] }),
    context: { queryClient },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("Dashboard screen", () => {
  beforeEach(() => {
    setCaps(ZERO_CAPS);
    server.use(meHandler());
    vi.stubGlobal("location", {
      pathname: "/dashboard",
      assign: vi.fn(),
      origin: "http://localhost",
    });
  });
  afterEach(() => {
    resetCaps();
    vi.unstubAllGlobals();
  });

  it("renders the loading skeleton before data resolves", async () => {
    // Delay every analytics call so we observe the Suspense fallback.
    server.use(
      http.get("*/api/v1/analytics/*", async () => {
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json({});
      }),
    );
    renderDashboard();
    expect(await screen.findByTestId("dashboard-skeleton")).toBeInTheDocument();
  });

  it("renders KPI cards, charts, recent runs, readiness when data resolves (ZERO)", async () => {
    renderDashboard();
    // KPI values from fixtures: passRate=0.92, runCount=84.
    const kpis = await screen.findByTestId("dashboard-kpis", undefined, { timeout: 3000 });
    expect(kpis.textContent).toContain("92%");
    expect(screen.getByTestId("dashboard-pass-rate")).toBeInTheDocument();
    expect(screen.getByTestId("dashboard-coverage")).toBeInTheDocument();
    expect(screen.getByTestId("dashboard-recent-runs")).toBeInTheDocument();
    expect(screen.getByTestId("dashboard-readiness")).toBeInTheDocument();
  });

  it("shows '—' placeholders in KPI cards when there are zero runs", async () => {
    server.use(
      http.get("*/api/v1/analytics/kpis", () =>
        HttpResponse.json({ passRate: 0, runCount: 0, avgDurationMs: 0, defectsOpen: 0 }),
      ),
    );
    renderDashboard();
    const kpis = await screen.findByTestId("dashboard-kpis", undefined, { timeout: 3000 });
    expect(kpis.textContent).toContain("—");
  });

  it("renders the ErrorBoundary fallback when an analytics call 500s", async () => {
    server.use(
      http.get("*/api/v1/analytics/kpis", () =>
        HttpResponse.json({ code: "BOOM", message: "nope" }, { status: 500 }),
      ),
    );
    renderDashboard();
    expect(
      await screen.findByText(/Couldn't load dashboard/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("ZERO tier: agent activity card shows 'Agent disabled' empty state", async () => {
    renderDashboard();
    const card = await screen.findByTestId("dashboard-agent-activity", undefined, {
      timeout: 3000,
    });
    expect(card).toHaveTextContent(/Agent disabled/i);
  });

  it("CLOUD tier: agent activity card renders feed items when present", async () => {
    setCaps(CLOUD_CAPS);
    server.use(
      http.get("*/api/v1/audit-logs", () =>
        HttpResponse.json({
          items: [
            {
              id: "evt_1",
              action: "agent.diagnose",
              actor: "agent",
              message: "Diagnosed RUN-1002 as REGRESSION",
              at: "2026-05-29T10:00:00Z",
            },
          ],
        }),
      ),
    );
    renderDashboard();
    await waitFor(
      () => {
        expect(screen.getByTestId("dashboard-agent-activity")).toHaveTextContent(
          /Diagnosed RUN-1002/,
        );
      },
      { timeout: 3000 },
    );
  });
});
