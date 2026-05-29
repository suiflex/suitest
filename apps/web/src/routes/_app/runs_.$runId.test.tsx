import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  RouterProvider,
  createMemoryHistory,
  createRouter,
} from "@tanstack/react-router";
import { act, render, screen, waitFor } from "@testing-library/react";
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
            step_order: 1,
            outcome: "PASS",
            started_at: "2026-05-27T10:00:00Z",
            completed_at: "2026-05-27T10:00:10Z",
            duration_ms: 10000,
            error_message: null,
          },
        ],
      });
    }),
    http.get(`*/api/v1/runs/${RUN_ID}/artifacts`, () => {
      artifactsCallCount.value += 1;
      return HttpResponse.json({ items: [] });
    }),
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

  it("appends a log line when WS publishes run.step.log", async () => {
    renderRunDetail();
    await screen.findByTestId("run-detail-page", undefined, { timeout: 3000 });

    await act(async () => {
      refs.ws.emit({
        topic: `run:${RUN_ID}`,
        event: "run.step.log",
        data: {
          runId: RUN_ID,
          stepIndex: 0,
          level: "info",
          message: "hello from runner",
          time: "2026-05-27T10:00:05Z",
        },
      });
    });

    expect(await screen.findByText(/hello from runner/)).toBeInTheDocument();
  });

  it("preserves user scroll position when scrolled up (auto-scroll suspended)", async () => {
    renderRunDetail();
    await screen.findByTestId("run-detail-page", undefined, { timeout: 3000 });

    // Append one log line so the scroller has content.
    await act(async () => {
      refs.ws.emit({
        topic: `run:${RUN_ID}`,
        event: "run.step.log",
        data: {
          runId: RUN_ID,
          stepIndex: 0,
          level: "info",
          message: "first line",
          time: "2026-05-27T10:00:05Z",
        },
      });
    });

    const scroller = await screen.findByTestId("log-pane-scroller");
    // Simulate the user scrolling away from the bottom — set scrollTop and
    // dispatch a scroll event so the handler flips `autoScrollRef`.
    Object.defineProperty(scroller, "scrollHeight", { configurable: true, value: 500 });
    Object.defineProperty(scroller, "clientHeight", { configurable: true, value: 100 });
    scroller.scrollTop = 50;
    await act(async () => {
      scroller.dispatchEvent(new Event("scroll"));
    });

    // Emit a new log line. The auto-scroll effect must NOT yank scrollTop
    // back to scrollHeight — it should stay at 50.
    await act(async () => {
      refs.ws.emit({
        topic: `run:${RUN_ID}`,
        event: "run.step.log",
        data: {
          runId: RUN_ID,
          stepIndex: 0,
          level: "info",
          message: "second line",
          time: "2026-05-27T10:00:06Z",
        },
      });
    });

    expect(scroller.scrollTop).toBe(50);
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
          totalSteps: 1,
          passedSteps: 1,
          failedSteps: 0,
          durationMs: 11000,
        },
      });
    });

    await waitFor(() => {
      expect(refs.artifactsCallCount.value).toBeGreaterThan(beforeArtifacts);
      expect(refs.stepsCallCount.value).toBeGreaterThan(beforeSteps);
    });
  });
});
