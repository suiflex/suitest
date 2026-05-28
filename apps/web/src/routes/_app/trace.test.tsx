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
import { ZERO_CAPS, resetCaps, setCaps } from "@/test/capabilities";

function renderTrace() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ["/trace"] }),
    context: { queryClient },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

describe("Traceability screen", () => {
  beforeEach(() => {
    setCaps(ZERO_CAPS);
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({ id: "u_demo", email: "demo@suitest.dev", name: "Maya", memberships: [] }),
      ),
    );
    vi.stubGlobal("location", { pathname: "/trace", assign: vi.fn(), origin: "http://localhost" });
  });
  afterEach(() => {
    resetCaps();
    vi.unstubAllGlobals();
  });

  it("renders the skeleton before the matrix resolves", async () => {
    server.use(
      http.get("*/api/v1/traceability/matrix", async () => {
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json({ requirements: [], cases: [], defects: [] });
      }),
    );
    renderTrace();
    expect(await screen.findByTestId("trace-skeleton")).toBeInTheDocument();
  });

  it("renders 3 columns with requirements/cases/defects when data resolves", async () => {
    renderTrace();
    await screen.findByTestId("trace-grid", undefined, { timeout: 3000 });
    expect(screen.getAllByTestId("trace-req-row").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByTestId("trace-case-row").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByTestId("trace-defect-row").length).toBeGreaterThanOrEqual(1);
  });

  it("renders the empty state when there are no requirements", async () => {
    server.use(
      http.get("*/api/v1/traceability/matrix", () =>
        HttpResponse.json({ requirements: [], cases: [], defects: [] }),
      ),
    );
    renderTrace();
    expect(
      await screen.findByText(/No requirements imported/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("renders the error fallback when /traceability/matrix 500s", async () => {
    server.use(
      http.get("*/api/v1/traceability/matrix", () =>
        HttpResponse.json({ code: "BOOM", message: "nope" }, { status: 500 }),
      ),
    );
    renderTrace();
    expect(
      await screen.findByText(/Couldn't load traceability/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("clicking a requirement highlights its linked cases and defects", async () => {
    const user = userEvent.setup();
    renderTrace();
    const reqRows = await screen.findAllByTestId("trace-req-row", undefined, { timeout: 3000 });
    const req002 = reqRows.find((r) => r.getAttribute("data-req-id") === "REQ-002");
    expect(req002).toBeTruthy();
    await user.click(req002 as HTMLElement);
    // REQ-002 links to TC-204 + DEF-202 in the fixture.
    const caseRows = screen.getAllByTestId("trace-case-row");
    const tc204 = caseRows.find((r) => r.getAttribute("data-case-id") === "TC-204");
    expect(tc204?.getAttribute("data-linked")).toBe("true");
    const defectRows = screen.getAllByTestId("trace-defect-row");
    expect(
      defectRows.find((r) => r.getAttribute("data-defect-id") === "DEF-202")?.getAttribute("data-linked"),
    ).toBe("true");
  });
});
