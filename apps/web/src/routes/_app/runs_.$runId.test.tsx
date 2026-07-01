import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/mocks/server";
import { routeTree } from "@/routeTree.gen";
import { installMockWs, type MockWs } from "@/test/mock-ws";
import { ZERO_CAPS, resetCaps, setCaps } from "@/test/capabilities";

const RUN_ID = "run_abc123";

function renderRunDetail(): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [`/runs/${RUN_ID}`] }),
    context: { queryClient },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

interface TestRefs {
  ws: MockWs;
  restore: () => void;
  stepsCallCount: { value: number };
  artifactsCallCount: { value: number };
}

function withFreshMocks(): TestRefs {
  const stepsCallCount = { value: 0 };
  const artifactsCallCount = { value: 0 };

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
            workspace: { id: "ws_1", slug: "demo", name: "Demo WS" },
          },
        ],
      }),
    ),
    http.get(`*/api/v1/runs/${RUN_ID}`, () =>
      HttpResponse.json({
        id: RUN_ID,
        public_id: "RUN-1001",
        project_id: "prj_demo",
        name: "Checkout flow rejects expired cards",
        branch: "main",
        commit_sha: "abcd123",
        env: "staging",
        status: "RUNNING",
        trigger: "MANUAL",
        tier_at_runtime: "ZERO",
        started_at: "2026-05-27T10:00:00Z",
        completed_at: null,
        duration_ms: null,
        summary: { total_steps: 4, passed_steps: 1, failed_steps: 0, duration_ms: null },
        created_at: "2026-05-27T10:00:00Z",
        updated_at: "2026-05-27T10:00:30Z",
      }),
    ),
    http.get(`*/api/v1/runs/${RUN_ID}/steps`, () => {
      stepsCallCount.value += 1;
      return HttpResponse.json({
        items: [
          {
            id: "rs_01",
            run_id: RUN_ID,
            case_id: "case_01",
            case_public_id: "TC-101",
            case_name: "successful_login_opens_the_dashboard",
            title: "Click 'Sign in'",
            type: "action",
            step_order: 1,
            outcome: "PASS",
            started_at: "2026-05-27T10:00:00Z",
            completed_at: "2026-05-27T10:00:10Z",
            duration_ms: 10000,
            error_message: null,
          },
          {
            id: "rs_02",
            run_id: RUN_ID,
            case_id: "case_02",
            case_public_id: "TC-102",
            case_name: "expired_card_is_rejected",
            // no title → falls back to `${type} · step N`
            type: "assertion",
            step_order: 2,
            outcome: "FAIL",
            started_at: "2026-05-27T10:00:10Z",
            completed_at: "2026-05-27T10:00:12Z",
            duration_ms: 2000,
            error_message: "expected 402 but got 200",
          },
        ],
      });
    }),
    http.get(`*/api/v1/runs/${RUN_ID}/artifacts`, () => {
      artifactsCallCount.value += 1;
      return HttpResponse.json({ items: [] });
    }),
    http.get(`*/api/v1/runs/${RUN_ID}/logs`, () =>
      HttpResponse.json({ items: [], hasMore: false, nextCursor: 0 }),
    ),
    http.get("*/api/v1/test-cases/:caseId", () =>
      HttpResponse.json({ automation_code: "await page.click('#signin')", description: null }),
    ),
  );

  const { ws, restore } = installMockWs();
  return { ws, restore, stepsCallCount, artifactsCallCount };
}

describe("RunDetailPage", () => {
  let refs: TestRefs;

  beforeEach(() => {
    setCaps(ZERO_CAPS);
    vi.stubGlobal("location", {
      pathname: `/runs/${RUN_ID}`,
      assign: vi.fn(),
      origin: "http://localhost",
    });
    refs = withFreshMocks();
  });
  afterEach(() => {
    refs.restore();
    resetCaps();
    vi.unstubAllGlobals();
  });

  it("renders a TEST CASE list grouped by case (not a flat step list)", async () => {
    renderRunDetail();
    await screen.findByTestId("run-detail-page", undefined, { timeout: 3000 });

    const rows = await screen.findAllByTestId("case-row");
    expect(rows).toHaveLength(2);
    // Case titles come from case_name, not the TC id.
    const titles = screen.getAllByTestId("case-row-title").map((el) => el.textContent);
    expect(titles).toContain("successful_login_opens_the_dashboard");
    expect(titles).toContain("expired_card_is_rejected");
  });

  it("defaults selection to the failing case and shows step titles + type badges", async () => {
    renderRunDetail();
    await screen.findByTestId("run-detail-page", undefined, { timeout: 3000 });

    // The failing case (TC-102) is auto-selected → its detail is shown.
    const detail = await screen.findByTestId("case-detail");
    expect(within(detail).getByTestId("case-detail-title")).toHaveTextContent(
      "expired_card_is_rejected",
    );
    // Step with no title falls back to `${type} · step N`, never the TC id.
    const stepTitle = within(detail).getByTestId("step-title");
    expect(stepTitle).toHaveTextContent("assertion · step 2");
    expect(stepTitle.textContent).not.toContain("TC-102");
    // Result summary surfaces the first failure message.
    expect(within(detail).getByTestId("case-result-summary")).toHaveTextContent(
      "expected 402 but got 200",
    );
  });

  it("switches case detail when another case row is clicked", async () => {
    renderRunDetail();
    await screen.findByTestId("run-detail-page", undefined, { timeout: 3000 });

    const rows = await screen.findAllByTestId("case-row");
    const passingRow = rows.find((r) => r.textContent?.includes("successful_login"));
    expect(passingRow).toBeDefined();
    await act(async () => {
      passingRow?.click();
    });

    const detail = screen.getByTestId("case-detail");
    expect(within(detail).getByTestId("case-detail-title")).toHaveTextContent(
      "successful_login_opens_the_dashboard",
    );
    expect(within(detail).getByTestId("step-title")).toHaveTextContent("Click 'Sign in'");
  });

  it("refetches steps when WS publishes run.step.completed", async () => {
    renderRunDetail();
    await screen.findByTestId("run-detail-page", undefined, { timeout: 3000 });
    await waitFor(() => {
      expect(refs.stepsCallCount.value).toBeGreaterThanOrEqual(1);
    });
    const before = refs.stepsCallCount.value;

    await act(async () => {
      refs.ws.emit({
        topic: `run:${RUN_ID}`,
        event: "run.step.completed",
        data: { runId: RUN_ID, stepIndex: 0, outcome: "PASS", durationMs: 1000 },
      });
    });

    await waitFor(() => {
      expect(refs.stepsCallCount.value).toBeGreaterThan(before);
    });
  });

  it("refetches artifacts when WS publishes run.completed", async () => {
    renderRunDetail();
    await screen.findByTestId("run-detail-page", undefined, { timeout: 3000 });
    await waitFor(() => {
      expect(refs.artifactsCallCount.value).toBeGreaterThanOrEqual(1);
    });
    const beforeArtifacts = refs.artifactsCallCount.value;
    const beforeSteps = refs.stepsCallCount.value;

    await act(async () => {
      refs.ws.emit({
        topic: `run:${RUN_ID}`,
        event: "run.completed",
        data: {
          runId: RUN_ID,
          status: "PASS",
          totalSteps: 2,
          passedSteps: 1,
          failedSteps: 1,
          durationMs: 12000,
        },
      });
    });

    await waitFor(() => {
      expect(refs.artifactsCallCount.value).toBeGreaterThan(beforeArtifacts);
      expect(refs.stepsCallCount.value).toBeGreaterThan(beforeSteps);
    });
  });
});
