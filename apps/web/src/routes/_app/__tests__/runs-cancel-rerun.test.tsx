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
import { ZERO_CAPS, resetCaps, setCaps } from "@/test/capabilities";

// M1d-33 — cancel/re-run buttons wired to the M1c-shipped
// `POST /runs/:id/cancel` and `POST /runs/:id/rerun` endpoints. These tests
// pin the rewire so the stale "ships in M1c" `<DisabledTooltip>` can never
// regress back in.

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

// MSW matches `/runs/summary` against the `/runs/:runId` param route, so any
// override of the detail handler must re-declare the summary handler first or
// the suspense summary query 500s and the whole panel falls into the error
// boundary before the detail (and its cancel/re-run buttons) can mount.
const summaryHandler = http.get("*/api/v1/runs/summary", () =>
  HttpResponse.json({ activeNow: 1, today: 24, passed: 22, failed: 2, avgDurationMs: 84000, queue: 3 }),
);

// Build a run-detail body in the given status so we can flip a run between
// "live" (cancellable) and "terminal" (re-runnable).
function runDetail(publicId: string, status: string) {
  return {
    id: `run_${publicId}`,
    public_id: publicId,
    project_id: "prj_demo",
    name: "Checkout flow rejects expired cards",
    branch: "main",
    commit_sha: "abcd123",
    env: "staging",
    status,
    trigger: "MANUAL",
    tier_at_runtime: "ZERO",
    started_at: "2026-05-27T10:00:00Z",
    completed_at: status === "RUNNING" || status === "QUEUED" ? null : "2026-05-27T10:01:14Z",
    duration_ms: status === "RUNNING" || status === "QUEUED" ? null : 74000,
    summary:
      status === "RUNNING" || status === "QUEUED"
        ? null
        : { total_steps: 4, passed_steps: 3, failed_steps: 1, duration_ms: 74000 },
    created_at: "2026-05-27T10:00:00Z",
    updated_at: "2026-05-27T10:01:14Z",
  };
}

describe("M1d-33: run cancel/re-run rewire", () => {
  beforeEach(() => {
    setCaps(ZERO_CAPS);
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({ id: "u_demo", email: "demo@suitest.dev", name: "Maya", memberships: [{ workspace_id: "ws_1", role: "OWNER", workspace: { id: "ws_1", slug: "demo", name: "Demo" } }] }),
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

  it("cancel_button_clickable_not_disabled", async () => {
    // A live (RUNNING) run is cancellable — the button must be enabled, not a
    // disabled placeholder.
    server.use(
      summaryHandler,
      http.get("*/api/v1/runs/:runId", ({ params }) =>
        HttpResponse.json(runDetail(String(params["runId"]), "RUNNING")),
      ),
    );
    renderRuns("/runs?run=RUN-1001");
    const cancelButton = await screen.findByTestId("run-cancel-button", undefined, {
      timeout: 3000,
    });
    expect(cancelButton).not.toBeDisabled();
    expect(cancelButton).toHaveTextContent(/Cancel/i);
  });

  it("cancel_button_calls_POST_runs_id_cancel_then_invalidates_run_query", async () => {
    let cancelCalls = 0;
    let detailCalls = 0;
    // The button sends the run's *internal* id (`run.id`) to the endpoint; the
    // backend echoes back the run with its *public* id. The detail query is
    // keyed by public id, so the cancel response must carry `public_id:
    // RUN-1001` for the invalidation to hit and trigger a refetch.
    server.use(
      summaryHandler,
      http.get("*/api/v1/runs/:runId", ({ params }) => {
        detailCalls += 1;
        return HttpResponse.json(runDetail(String(params["runId"]), "RUNNING"));
      }),
      http.post("*/api/v1/runs/:runId/cancel", () => {
        cancelCalls += 1;
        return HttpResponse.json(runDetail("RUN-1001", "CANCELED"));
      }),
    );
    const user = userEvent.setup();
    renderRuns("/runs?run=RUN-1001");
    const cancelButton = await screen.findByTestId("run-cancel-button", undefined, {
      timeout: 3000,
    });
    const detailCallsBefore = detailCalls;
    await user.click(cancelButton);
    // The cancel endpoint fired exactly once with the selected run id…
    await waitFor(() => expect(cancelCalls).toBe(1));
    // …and the run detail query was invalidated, triggering a refetch.
    await waitFor(() => expect(detailCalls).toBeGreaterThan(detailCallsBefore), {
      timeout: 3000,
    });
  });

  it("cancel_button_403_role_VIEWER_renders_capability_banner", async () => {
    server.use(
      summaryHandler,
      http.get("*/api/v1/runs/:runId", ({ params }) =>
        HttpResponse.json(runDetail(String(params["runId"]), "RUNNING")),
      ),
      http.post("*/api/v1/runs/:runId/cancel", () =>
        HttpResponse.json(
          { code: "FORBIDDEN", message: "VIEWER role cannot cancel runs" },
          { status: 403 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderRuns("/runs?run=RUN-1001");
    const cancelButton = await screen.findByTestId("run-cancel-button", undefined, {
      timeout: 3000,
    });
    await user.click(cancelButton);
    expect(
      await screen.findByTestId("run-cancel-forbidden-banner", undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("rerun_button_calls_POST_runs_id_rerun_navigates_to_new_run_id_on_success", async () => {
    let rerunCalls = 0;
    server.use(
      summaryHandler,
      // Default detail is a terminal FAIL run — re-run is enabled.
      http.get("*/api/v1/runs/:runId", ({ params }) =>
        HttpResponse.json(runDetail(String(params["runId"]), "FAIL")),
      ),
      http.post("*/api/v1/runs/:runId/rerun", () => {
        rerunCalls += 1;
        return HttpResponse.json(runDetail("RUN-502", "QUEUED"), { status: 201 });
      }),
    );
    const user = userEvent.setup();
    const router = renderRuns("/runs?run=RUN-1001");
    const rerunButton = await screen.findByTestId("run-rerun-button", undefined, {
      timeout: 3000,
    });
    expect(rerunButton).not.toBeDisabled();
    await user.click(rerunButton);
    await waitFor(() => expect(rerunCalls).toBe(1));
    // On success the panel navigates to the freshly-queued run.
    await waitFor(() =>
      expect((router.state.location.search as { run?: string }).run).toBe("RUN-502"),
    );
  });

  it("defects_page_no_longer_shows_ships_in_M1c_tooltip", async () => {
    renderRuns("/defects");
    // Wait for the defects screen to settle, then assert the stale copy is gone.
    await screen.findByTestId("defects-screen", undefined, { timeout: 3000 }).catch(() => null);
    await waitFor(() => {
      expect(screen.queryByText(/ships in M1c/i)).toBeNull();
    });
  });
});
