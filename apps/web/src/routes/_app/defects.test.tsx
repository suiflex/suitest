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

  it("M1d-32: clicking 'Open run' fetches defect detail and navigates to /runs/$runId", async () => {
    const user = userEvent.setup();
    let detailFetched = false;
    server.use(
      http.get("*/api/v1/defects/:defectId", ({ params }) => {
        detailFetched = true;
        return HttpResponse.json({
          id: `def_${String(params["defectId"])}`,
          public_id: String(params["defectId"]),
          title: "Linked defect",
          description: null,
          severity: "HIGH",
          status: "OPEN",
          agent_diagnosis_kind: "MANUAL_TRIAGE",
          run_public_id: "RUN-777",
          test_case_public_id: "TC-101",
          requirement_public_id: null,
          assignee_id: null,
          component: null,
          workspace_id: "ws_demo",
          external_issues: [],
          created_at: "2026-05-01T08:00:00Z",
          updated_at: "2026-05-25T14:30:00Z",
        });
      }),
    );

    const router = renderDefects();
    await screen.findByTestId("defects-list", undefined, { timeout: 3000 });
    const openRunBtns = await screen.findAllByTestId("defect-open-run-btn");
    await user.click(openRunBtns[0] as HTMLElement);

    await waitFor(() => {
      expect(detailFetched).toBe(true);
    });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/runs/RUN-777");
    });
  });

  it("M1d-32: defect with null run_public_id falls back to disabled tooltip", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("*/api/v1/defects/:defectId", ({ params }) =>
        HttpResponse.json({
          id: `def_${String(params["defectId"])}`,
          public_id: String(params["defectId"]),
          title: "Defect without run",
          description: null,
          severity: "HIGH",
          status: "OPEN",
          agent_diagnosis_kind: "MANUAL_TRIAGE",
          run_public_id: null,
          test_case_public_id: null,
          requirement_public_id: null,
          assignee_id: null,
          component: null,
          workspace_id: "ws_demo",
          external_issues: [],
          created_at: "2026-05-01T08:00:00Z",
          updated_at: "2026-05-25T14:30:00Z",
        }),
      ),
    );

    renderDefects();
    await screen.findByTestId("defects-list", undefined, { timeout: 3000 });
    const openRunBtns = await screen.findAllByTestId("defect-open-run-btn");
    await user.click(openRunBtns[0] as HTMLElement);

    await waitFor(() => {
      // After the fetch resolves with null run_public_id, the active button
      // disappears and the DisabledTooltip wrapper takes over.
      expect(screen.queryAllByTestId("defect-open-run-btn").length).toBeLessThan(
        openRunBtns.length,
      );
    });
  });
});
