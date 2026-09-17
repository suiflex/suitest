import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { render, screen, act, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/mocks/server";
import { routeTree } from "@/routeTree.gen";
import { useActiveProject } from "@/stores/use-active-project";
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
      http.get("*/api/v1/projects", () =>
        HttpResponse.json({
          items: [
            { id: "prj_demo", name: "Demo" },
            { id: "prj_empty", name: "Empty Project" },
            { id: "prj_1", name: "Project 1" },
            { id: "prj_2", name: "Project 2" },
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

  it("renders load more button when nextCursor is available and appends runs", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("*/api/v1/runs", ({ request }) => {
        const url = new URL(request.url);
        const cursor = url.searchParams.get("cursor");
        if (!cursor) {
          return HttpResponse.json({
            items: [
              {
                id: "run_p1",
                public_id: "RUN-P1",
                project_id: "prj_demo",
                name: "Page 1 Run",
                branch: "main",
                commit_sha: "1111111",
                env: "staging",
                status: "PASS",
                trigger: "MANUAL",
                started_at: "2026-05-27T10:00:00Z",
                completed_at: "2026-05-27T10:01:00Z",
                duration_ms: 60000,
                created_at: "2026-05-27T10:00:00Z",
                updated_at: "2026-05-27T10:01:00Z",
              },
            ],
            meta: { limit: 30, nextCursor: "cur_page_2" },
          });
        }
        return HttpResponse.json({
          items: [
            {
              id: "run_p2",
              public_id: "RUN-P2",
              project_id: "prj_demo",
              name: "Page 2 Run",
              branch: "main",
              commit_sha: "2222222",
              env: "staging",
              status: "FAIL",
              trigger: "MANUAL",
              started_at: "2026-05-27T09:00:00Z",
              completed_at: "2026-05-27T09:01:00Z",
              duration_ms: 60000,
              created_at: "2026-05-27T09:00:00Z",
              updated_at: "2026-05-27T09:01:00Z",
            },
          ],
          meta: { limit: 30, nextCursor: null },
        });
      }),
    );

    renderRuns();
    const loadMoreBtn = await screen.findByTestId("runs-load-more-button", undefined, {
      timeout: 3000,
    });
    expect(loadMoreBtn).toBeInTheDocument();
    expect(screen.getByText("Page 1 Run")).toBeInTheDocument();

    await user.click(loadMoreBtn);

    expect(await screen.findByText("Page 2 Run", undefined, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.queryByTestId("runs-load-more-button")).not.toBeInTheDocument();
  });

  it("run detail panel renders Edit case link targeting the active case", async () => {
    const user = userEvent.setup();
    renderRuns();
    const rows = await screen.findAllByTestId("runs-row", undefined, { timeout: 3000 });
    await user.click(rows[0] as HTMLElement);
    await screen.findByTestId("run-detail", undefined, { timeout: 3000 });

    const editLink = await screen.findByTestId("run-edit-cases-link", undefined, { timeout: 3000 });
    expect(editLink).toHaveAttribute("href", expect.stringContaining("/cases?case="));
  });

  it("summary bar counters have tooltips explaining the counts", async () => {
    renderRuns();
    await screen.findByTestId("runs-summary", undefined, { timeout: 3000 });
    const passedCounter = screen.getByText("Passed");
    expect(passedCounter).toBeInTheDocument();
    const counters = screen.getAllByTestId("runs-counter");
    expect(counters.length).toBe(6);
  });

  it("filters runs list by search query and supports clear", async () => {
    const user = userEvent.setup();
    renderRuns();
    await screen.findByTestId("runs-summary", undefined, { timeout: 3000 });
    const searchInput = screen.getByTestId("runs-search-input");
    expect(searchInput).toBeInTheDocument();

    const initialRows = screen.getAllByTestId("runs-row");
    expect(initialRows.length).toBeGreaterThan(0);

    // Filter with no match
    await user.type(searchInput, "nonexistent-query-xyz");
    expect(screen.queryAllByTestId("runs-row")).toHaveLength(0);
    expect(screen.getByTestId("runs-list-no-search-results")).toHaveTextContent(
      /No runs matching .nonexistent-query-xyz. found./,
    );

    // Clear search
    const clearBtn = screen.getByTestId("runs-search-clear");
    await user.click(clearBtn);
    expect(screen.getAllByTestId("runs-row").length).toBe(initialRows.length);
  });

  it("renders step outcome counts on each run row in the list", async () => {
    renderRuns();
    await screen.findByTestId("runs-summary", undefined, { timeout: 3000 });
    const rowCounts = await screen.findAllByTestId("runs-row-counts", undefined, { timeout: 3000 });
    expect(rowCounts.length).toBeGreaterThan(0);
    // Verified that each row displays step counts (e.g. "2 steps · 2 passed")
    expect(rowCounts[0]).toHaveTextContent(/steps/);

    const runsCount = screen.getByTestId("runs-count");
    expect(runsCount).toBeInTheDocument();
    expect(runsCount).toHaveTextContent(/Showing/);
  });

  it("clears runs-right-pane and search param when switching to a project with zero runs", async () => {
    useActiveProject.setState({ projectId: "prj_demo" });
    const router = renderRuns("/runs?run=RUN-1001");
    expect(await screen.findByTestId("run-detail", undefined, { timeout: 3000 })).toBeInTheDocument();

    // Now user switches to a fresh project that has 0 runs
    server.use(
      http.get("*/api/v1/runs", ({ request }) => {
        const url = new URL(request.url);
        if (url.searchParams.get("projectId") === "prj_empty") {
          return HttpResponse.json({ items: [], meta: { limit: 10, nextCursor: null } });
        }
        return HttpResponse.json({ items: [], meta: { limit: 10, nextCursor: null } });
      }),
    );

    act(() => {
      useActiveProject.setState({ projectId: "prj_empty" });
    });

    // Right pane must clear its detail container and render empty state
    await waitFor(() => {
      expect(screen.queryByTestId("run-detail")).not.toBeInTheDocument();
      expect(screen.getByTestId("runs-right-pane")).toHaveTextContent(/Select a run/i);
    });

    // Left pane must reflect 0 runs
    expect(await screen.findByText(/No runs yet/i)).toBeInTheDocument();

    // URL search param must be cleared
    await waitFor(() => {
      expect((router.state.location.search as { run?: string }).run).toBeUndefined();
    });
  });

  it("does not render foreign run in right pane if run project_id does not match active project", async () => {
    useActiveProject.setState({ projectId: "prj_demo" });
    server.use(
      http.get("*/api/v1/runs/RUN-FOREIGN", () =>
        HttpResponse.json({
          id: "run_foreign",
          public_id: "RUN-FOREIGN",
          project_id: "prj_different",
          name: "Foreign project run",
          branch: "main",
          status: "PASS",
          trigger: "MANUAL",
          tier_at_runtime: "ZERO",
          summary: { total_steps: 1, passed_steps: 1, failed_steps: 0, duration_ms: 1000 },
          created_at: "2026-05-27T10:00:00Z",
          updated_at: "2026-05-27T10:00:01Z",
        }),
      ),
    );

    renderRuns("/runs?run=RUN-FOREIGN");
    await waitFor(() => {
      expect(screen.queryByTestId("run-detail")).not.toBeInTheDocument();
      expect(screen.getByTestId("runs-right-pane")).toHaveTextContent(/Select a run/i);
    });
  });

  it("switches right pane selection to new project runs when switching between projects with runs", async () => {
    useActiveProject.setState({ projectId: "prj_1" });
    server.use(
      http.get("*/api/v1/runs", ({ request }) => {
        const url = new URL(request.url);
        const pid = url.searchParams.get("projectId");
        if (pid === "prj_2") {
          return HttpResponse.json({
            items: [
              {
                id: "run_201",
                public_id: "RUN-2001",
                project_id: "prj_2",
                name: "Project 2 Checkout Run",
                status: "PASS",
                branch: "main",
                commit_sha: "2222222",
                duration_ms: 25000,
                created_at: "2026-06-01T00:00:00Z",
                summary: { total_steps: 2, passed_steps: 2, failed_steps: 0, duration_ms: 25000 },
              },
            ],
            meta: { limit: 10, nextCursor: null },
          });
        }
        return HttpResponse.json({
          items: [
            {
              id: "run_101",
              public_id: "RUN-1001",
              project_id: "prj_1",
              name: "Project 1 Run",
              status: "FAIL",
              branch: "main",
              commit_sha: "1111111",
              duration_ms: 50000,
              created_at: "2026-05-01T00:00:00Z",
              summary: { total_steps: 4, passed_steps: 3, failed_steps: 1, duration_ms: 50000 },
            },
          ],
          meta: { limit: 10, nextCursor: null },
        });
      }),
      http.get("*/api/v1/runs/RUN-1001", () =>
        HttpResponse.json({
          id: "run_101",
          public_id: "RUN-1001",
          project_id: "prj_1",
          name: "Project 1 Run",
          branch: "main",
          status: "FAIL",
          trigger: "MANUAL",
          tier_at_runtime: "ZERO",
          summary: { total_steps: 4, passed_steps: 3, failed_steps: 1, duration_ms: 50000 },
          created_at: "2026-05-01T00:00:00Z",
          updated_at: "2026-05-01T00:00:50Z",
        }),
      ),
      http.get("*/api/v1/runs/RUN-2001", () =>
        HttpResponse.json({
          id: "run_201",
          public_id: "RUN-2001",
          project_id: "prj_2",
          name: "Project 2 Checkout Run",
          branch: "main",
          status: "PASS",
          trigger: "MANUAL",
          tier_at_runtime: "ZERO",
          summary: { total_steps: 2, passed_steps: 2, failed_steps: 0, duration_ms: 25000 },
          created_at: "2026-06-01T00:00:00Z",
          updated_at: "2026-06-01T00:00:25Z",
        }),
      ),
    );

    const router = renderRuns("/runs?run=RUN-1001");
    expect(await screen.findByTestId("run-detail", undefined, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByTestId("runs-right-pane")).toHaveTextContent("RUN-1001");

    // Switch active project to prj_2
    act(() => {
      useActiveProject.setState({ projectId: "prj_2" });
    });

    // Right pane should now render RUN-2001, not RUN-1001
    await waitFor(() => {
      expect(screen.getByTestId("runs-right-pane")).toHaveTextContent("RUN-2001");
      expect(screen.getByTestId("runs-right-pane")).not.toHaveTextContent("RUN-1001");
    });

    // Router search should be updated to RUN-2001
    await waitFor(() => {
      expect((router.state.location.search as { run?: string }).run).toBe("RUN-2001");
    });
  });
});

