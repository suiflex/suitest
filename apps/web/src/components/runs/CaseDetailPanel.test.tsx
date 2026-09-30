import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CaseDetailPanel } from "@/components/runs/CaseDetailPanel";
import type { CaseGroup } from "@/components/runs/case-grouping";
import type { components } from "@/lib/api-types";
import { server } from "@/mocks/server";

type RunStepPublic = components["schemas"]["RunStepPublic"];
type ArtifactPublic = components["schemas"]["ArtifactPublic"];

function makeStep(order: number, title: string, outcome: components["schemas"]["StepOutcome"]): RunStepPublic {
  return {
    id: `step_${order}`,
    run_id: "run_1",
    case_id: "tc_1",
    case_public_id: "TC-101",
    case_name: "Checkout",
    case_title: "Checkout test",
    step_order: order,
    title,
    type: "action",
    outcome,
    duration_ms: 200,
  };
}

function renderPanel(
  group: CaseGroup,
  runStatus: components["schemas"]["RunStatus"] = "PASS",
  onRerunCase?: (caseId: string) => void,
  hasMultipleCases = true,
  artifacts: ArtifactPublic[] = [],
  playwrightConfig?: {
    headless?: boolean;
    screenshot?: "off" | "only-on-failure" | "on";
    video?: "off" | "retain-on-failure" | "on";
    highlightSteps?: boolean;
  } | null,
) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  const rootRoute = createRootRoute({
    component: () => (
      <CaseDetailPanel
        runId="run_1"
        group={group}
        artifacts={artifacts}
        runStatus={runStatus}
        onRerunCase={onRerunCase}
        hasMultipleCases={hasMultipleCases}
        playwrightConfig={playwrightConfig}
      />
    ),
  });

  const casesRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/cases",
    component: () => <div />,
  });

  const router = createRouter({
    routeTree: rootRoute.addChildren([casesRoute]),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });

  return render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("<CaseDetailPanel>", () => {
  beforeEach(() => {
    server.use(
      http.get("*/api/v1/test-cases/:id", () =>
        HttpResponse.json({
          id: "tc_1",
          description: "A test case description",
          automation_code: "test('checkout', async () => {});",
        }),
      ),
      http.get("*/api/v1/runs/:id/logs", () =>
        HttpResponse.json({ items: [], total: 0 }),
      ),
    );
  });

  it("Terminal Freeze Guard: does NOT query planned steps when run is completed", async () => {
    let stepsEndpointQueried = false;
    server.use(
      http.get("*/api/v1/test-cases/:id/steps", () => {
        stepsEndpointQueried = true;
        return HttpResponse.json([
          { id: "new_step", order: 99, action: "Newly added step in editor" },
        ]);
      }),
    );

    const group: CaseGroup = {
      caseId: "tc_1",
      casePublicId: "TC-101",
      caseName: "Checkout",
      steps: [makeStep(1, "Recorded step in history", "PASS")],
      total: 1,
      passed: 1,
      failed: 0,
      rollup: "pass",
      durationMs: 200,
      kind: "frontend",
      firstFailure: null,
    };

    renderPanel(group, "PASS");

    // History preserves the step recorded at run time
    expect(await screen.findByText("Recorded step in history")).toBeInTheDocument();
    // Step added to /cases later is NOT fetched
    expect(stepsEndpointQueried).toBe(false);
    expect(screen.queryByText("Newly added step in editor")).not.toBeInTheDocument();
  });

  it("renders Re-run case button for terminal runs and calls onRerunCase on click when hasMultipleCases is true", async () => {
    const user = userEvent.setup();
    const onRerunCase = vi.fn();
    const group: CaseGroup = {
      caseId: "tc_1",
      casePublicId: "TC-101",
      caseName: "Checkout",
      steps: [makeStep(1, "Step 1", "FAIL")],
      total: 1,
      passed: 0,
      failed: 1,
      rollup: "fail",
      durationMs: 200,
      kind: "frontend",
      firstFailure: "Element not found",
    };

    renderPanel(group, "FAIL", onRerunCase, true);

    const rerunBtn = await screen.findByTestId("case-rerun-button");
    expect(rerunBtn).toBeInTheDocument();
    expect(rerunBtn).toHaveTextContent(/Re-run case/i);

    await user.click(rerunBtn);
    expect(onRerunCase).toHaveBeenCalledTimes(1);
    expect(onRerunCase).toHaveBeenCalledWith("tc_1");
  });

  it("hides Edit case and Re-run case buttons when hasMultipleCases is false", async () => {
    const onRerunCase = vi.fn();
    const group: CaseGroup = {
      caseId: "tc_1",
      casePublicId: "TC-101",
      caseName: "Checkout",
      steps: [makeStep(1, "Step 1", "FAIL")],
      total: 1,
      passed: 0,
      failed: 1,
      rollup: "fail",
      durationMs: 200,
      kind: "frontend",
      firstFailure: "Element not found",
    };

    renderPanel(group, "FAIL", onRerunCase, false);

    expect(await screen.findByTestId("case-detail-title")).toBeInTheDocument();
    expect(screen.queryByTestId("case-edit-link")).not.toBeInTheDocument();
    expect(screen.queryByTestId("case-rerun-button")).not.toBeInTheDocument();
  });

  it("handles soft-deleted cases: renders Deleted case badge, banner, and hides Re-run case", async () => {
    const group: CaseGroup = {
      caseId: "tc_del",
      casePublicId: "TC-999",
      caseName: "Deleted flow",
      steps: [makeStep(1, "Step 1", "PASS")],
      total: 1,
      passed: 1,
      failed: 0,
      rollup: "pass",
      durationMs: 200,
      kind: "frontend",
      firstFailure: null,
      isDeleted: true,
    };

    renderPanel(group, "PASS", vi.fn());

    expect(await screen.findByTestId("case-deleted-badge")).toBeInTheDocument();
    expect(await screen.findByTestId("case-deleted-banner")).toHaveTextContent(
      /Historical snapshot: This test case is deleted from the workspace/i,
    );
    expect(screen.queryByTestId("case-edit-link")).not.toBeInTheDocument();
    expect(screen.queryByTestId("case-rerun-button")).not.toBeInTheDocument();
  });

  it("retains aborted steps and displays assertive messaging when run is cancelled", async () => {
    server.use(
      http.get("*/api/v1/test-cases/:id/steps", () =>
        HttpResponse.json([
          { id: "step_1", order: 1, action: "Navigate to home" },
          { id: "step_2", order: 2, action: "Click submit" },
        ]),
      ),
    );

    const group: CaseGroup = {
      caseId: "tc_1",
      casePublicId: "TC-101",
      caseName: "Checkout",
      steps: [makeStep(1, "Navigate to home", "PASS")],
      total: 2,
      passed: 1,
      failed: 0,
      rollup: "aborted",
      durationMs: 200,
      kind: "frontend",
      firstFailure: null,
    };

    renderPanel(group, "CANCELLED");

    expect(await screen.findByText("Navigate to home")).toBeInTheDocument();
    expect(await screen.findByText("Click submit")).toBeInTheDocument();
    expect((await screen.findAllByText("ABORTED")).length).toBeGreaterThanOrEqual(1);
    expect(
      await screen.findByText(/Step was not executed because the test run was cancelled by user/i),
    ).toBeInTheDocument();
  });

  it("queued case in live run renders unexecuted planned steps as QUEUED, not RUNNING", async () => {
    server.use(
      http.get("*/api/v1/test-cases/:id/steps", () =>
        HttpResponse.json([
          { id: "step_1", order: 1, action: "Navigate to page" },
          { id: "step_2", order: 2, action: "Click button" },
        ]),
      ),
    );

    const group: CaseGroup = {
      caseId: "tc_1",
      casePublicId: "TC-101",
      caseName: "Queued Case",
      steps: [],
      total: 2,
      passed: 0,
      failed: 0,
      rollup: "queued",
      durationMs: 0,
      kind: "frontend",
      firstFailure: null,
    };

    renderPanel(group, "RUNNING");

    expect(await screen.findByText("Navigate to page")).toBeInTheDocument();
    expect(await screen.findByText("Click button")).toBeInTheDocument();
    expect(screen.queryByText("RUNNING")).not.toBeInTheDocument();

    const stepRows = screen.getAllByTestId("step-row");
    expect(stepRows).toHaveLength(2);
    expect(stepRows[0]).toHaveTextContent("QUEUED");
    expect(stepRows[1]).toHaveTextContent("QUEUED");
  });

  it("HTTP 500 error on case description fetch does NOT mark case as deleted", async () => {
    server.use(
      http.get("*/api/v1/test-cases/:id", () =>
        new HttpResponse(null, { status: 500 }),
      ),
    );

    const group: CaseGroup = {
      caseId: "tc_1",
      casePublicId: "TC-101",
      caseName: "Active Case with 500",
      steps: [makeStep(1, "Step 1", "PASS")],
      total: 1,
      passed: 1,
      failed: 0,
      rollup: "pass",
      durationMs: 200,
      kind: "frontend",
      firstFailure: null,
    };

    renderPanel(group, "PASS", vi.fn());

    expect(await screen.findByTestId("case-detail-title")).toBeInTheDocument();
    expect(screen.queryByTestId("case-deleted-badge")).not.toBeInTheDocument();
    expect(screen.queryByTestId("case-deleted-banner")).not.toBeInTheDocument();
    expect(screen.getByTestId("case-rerun-button")).toBeInTheDocument();
  });

  it("opens lightbox modal when clicking Zoom on a screenshot artifact in Artifacts tab", async () => {
    const group: CaseGroup = {
      caseId: "tc_1",
      casePublicId: "TC-101",
      caseName: "Checkout",
      steps: [makeStep(1, "Navigate to home", "PASS")],
      total: 1,
      passed: 1,
      failed: 0,
      rollup: "pass",
      durationMs: 200,
      kind: "frontend",
      firstFailure: null,
    };

    const artifacts: ArtifactPublic[] = [
      {
        id: "art_shot_1",
        run_step_id: "step_1",
        kind: "SCREENSHOT",
        mime_type: "image/png",
        size_bytes: 1024,
        created_at: "2026-09-14T00:00:00Z",
      },
    ];

    renderPanel(group, "PASS", undefined, true, artifacts);

    // Click Artifacts tab
    const artifactsTab = await screen.findByRole("tab", { name: "Artifacts" });
    await userEvent.click(artifactsTab);

    // Find and click Zoom button
    const zoomBtn = await screen.findByTestId("case-artifact-zoom-btn");
    expect(zoomBtn).toBeInTheDocument();

    await userEvent.click(zoomBtn);

    // Lightbox modal should appear
    expect(await screen.findByTestId("image-lightbox-modal")).toBeInTheDocument();
    expect(screen.getByTestId("lightbox-image")).toHaveAttribute(
      "src",
      "https://example.invalid/blob/fake",
    );
  });

  it("renders step-by-step screenshot navigator in Preview tab and allows zooming step screenshot", async () => {
    const group: CaseGroup = {
      caseId: "tc_1",
      casePublicId: "TC-101",
      caseName: "Checkout",
      steps: [
        makeStep(1, "Navigate to home", "PASS"),
        makeStep(2, "Click buy button", "FAIL"),
      ],
      total: 2,
      passed: 1,
      failed: 1,
      rollup: "fail",
      durationMs: 400,
      kind: "frontend",
      firstFailure: null,
    };

    const artifacts: ArtifactPublic[] = [
      {
        id: "art_shot_1",
        run_step_id: "step_1",
        kind: "SCREENSHOT",
        mime_type: "image/png",
        size_bytes: 1024,
        created_at: "2026-09-14T00:00:00Z",
      },
      {
        id: "art_shot_2",
        run_step_id: "step_2",
        kind: "SCREENSHOT",
        mime_type: "image/png",
        size_bytes: 2048,
        created_at: "2026-09-14T00:00:01Z",
      },
    ];

    renderPanel(group, "FAIL", undefined, true, artifacts);

    // Preview tab is active by default
    expect(await screen.findByTestId("step-screenshot-navigator")).toBeInTheDocument();
    expect(screen.getByTestId("step-nav-btn-1")).toBeInTheDocument();
    expect(screen.getByTestId("step-nav-btn-2")).toBeInTheDocument();

    // Click step 2 button
    await userEvent.click(screen.getByTestId("step-nav-btn-2"));

    // Click zoom trigger on step image
    const zoomTrigger = await screen.findByTestId("case-preview-zoom-trigger");
    await userEvent.click(zoomTrigger);

    // Lightbox modal opens
    expect(await screen.findByTestId("image-lightbox-modal")).toBeInTheDocument();
  });

  it("renders video player in Preview tab when only VIDEO artifact is present", async () => {
    server.use(
      http.get("*/api/v1/runs/:runId/artifacts/:artifactId", () =>
        HttpResponse.json({
          url: "https://example.com/recording.webm",
          expires_at: "2026-09-17T00:00:00Z",
        }),
      ),
    );

    const group: CaseGroup = {
      caseId: "tc_1",
      casePublicId: "TC-101",
      caseName: "Checkout",
      steps: [
        makeStep(1, "Navigate to home", "PASS"),
        makeStep(2, "Click buy button", "PASS"),
      ],
      total: 2,
      passed: 2,
      failed: 0,
      rollup: "pass",
      durationMs: 400,
      kind: "frontend",
      firstFailure: null,
    };

    const artifacts: ArtifactPublic[] = [
      {
        id: "art_video_1",
        run_step_id: "step_2",
        kind: "VIDEO",
        mime_type: "video/webm",
        size_bytes: 50000,
        created_at: "2026-09-14T00:00:01Z",
      },
    ];

    renderPanel(group, "PASS", undefined, true, artifacts);

    // Should display video recording label and video element
    expect(await screen.findByText("Video recording")).toBeInTheDocument();
    const videoElem = await screen.findByTestId("case-preview-video");
    expect(videoElem).toBeInTheDocument();
    expect(videoElem).toHaveAttribute("src", "https://example.com/recording.webm");
  });

  it("opens video modal when clicking expand button in Preview tab", async () => {
    server.use(
      http.get("*/api/v1/runs/:runId/artifacts/:artifactId", () =>
        HttpResponse.json({
          url: "https://example.com/recording.webm",
          expires_at: "2026-09-17T00:00:00Z",
        }),
      ),
    );

    const group: CaseGroup = {
      caseId: "tc_1",
      casePublicId: "TC-101",
      caseName: "Checkout",
      steps: [makeStep(1, "Navigate to home", "PASS")],
      total: 1,
      passed: 1,
      failed: 0,
      rollup: "pass",
      durationMs: 200,
      kind: "frontend",
      firstFailure: null,
    };

    const artifacts: ArtifactPublic[] = [
      {
        id: "art_video_1",
        run_step_id: "step_1",
        kind: "VIDEO",
        mime_type: "video/webm",
        size_bytes: 50000,
        created_at: "2026-09-14T00:00:01Z",
      },
    ];

    renderPanel(group, "PASS", undefined, true, artifacts);

    const videoTrigger = await screen.findByTestId("case-preview-video-trigger");
    await userEvent.click(videoTrigger);

    expect(await screen.findByTestId("video-player-modal")).toBeInTheDocument();
  });

  it("opens video modal when clicking expand button in Artifacts tab", async () => {
    server.use(
      http.get("*/api/v1/runs/:runId/artifacts/:artifactId", () =>
        HttpResponse.json({
          url: "https://example.com/recording.webm",
          expires_at: "2026-09-17T00:00:00Z",
        }),
      ),
    );

    const group: CaseGroup = {
      caseId: "tc_1",
      casePublicId: "TC-101",
      caseName: "Checkout",
      steps: [makeStep(1, "Navigate to home", "PASS")],
      total: 1,
      passed: 1,
      failed: 0,
      rollup: "pass",
      durationMs: 200,
      kind: "frontend",
      firstFailure: null,
    };

    const artifacts: ArtifactPublic[] = [
      {
        id: "art_video_1",
        run_step_id: "step_1",
        kind: "VIDEO",
        mime_type: "video/webm",
        size_bytes: 50000,
        created_at: "2026-09-14T00:00:01Z",
      },
    ];

    renderPanel(group, "PASS", undefined, true, artifacts);

    // Switch to artifacts tab
    const tabBtn = await screen.findByRole("tab", { name: /artifacts/i });
    await userEvent.click(tabBtn);

    const expandBtn = await screen.findByTestId("case-artifact-video-expand-btn");
    await userEvent.click(expandBtn);

    expect(await screen.findByTestId("video-player-modal")).toBeInTheDocument();
  });

  it("paginates artifacts progressively with Load More button", async () => {
    const steps = Array.from({ length: 15 }, (_, i) =>
      makeStep(i + 1, `Step ${i + 1}`, "PASS"),
    );
    const group: CaseGroup = {
      caseId: "tc_1",
      casePublicId: "TC-101",
      caseName: "Checkout",
      steps,
      total: 15,
      passed: 15,
      failed: 0,
      rollup: "pass",
      durationMs: 3000,
      kind: "frontend",
      firstFailure: null,
    };

    // Create 15 artifacts
    const artifacts: ArtifactPublic[] = Array.from({ length: 15 }, (_, i) => ({
      id: `art_${i + 1}`,
      run_step_id: `step_${i + 1}`,
      kind: "SCREENSHOT",
      mime_type: "image/png",
      size_bytes: 1024,
      created_at: "2026-09-14T00:00:01Z",
    }));

    renderPanel(group, "PASS", undefined, true, artifacts);

    // Switch to artifacts tab
    const tabBtn = await screen.findByRole("tab", { name: /artifacts/i });
    await userEvent.click(tabBtn);

    // Count indicator shows 10 of 15
    expect(screen.getByTestId("case-artifacts-count")).toHaveTextContent("Showing 10 of 15 artifacts");

    // Exactly 10 artifact items rendered
    const items = screen.getAllByTestId("case-artifact");
    expect(items).toHaveLength(10);

    // Load more button shows 5 remaining
    const loadMoreBtn = screen.getByTestId("case-artifacts-load-more");
    expect(loadMoreBtn).toHaveTextContent("Load more (5 remaining)");

    // Click load more
    await userEvent.click(loadMoreBtn);

    // Count updates to 15 of 15
    expect(screen.getByTestId("case-artifacts-count")).toHaveTextContent("Showing 15 of 15 artifacts");
    expect(screen.getAllByTestId("case-artifact")).toHaveLength(15);
    expect(screen.queryByTestId("case-artifacts-load-more")).not.toBeInTheDocument();
  });

  it("deduplicates multiple screenshots for the same step and orders buttons 1..N relative to case", async () => {
    const steps = [
      makeStep(88, "Open modal", "PASS"),
      makeStep(89, "Fill input", "FAIL"),
    ];

    const group: CaseGroup = {
      caseId: "tc_bulk_1",
      casePublicId: "TC-3003",
      caseName: "Bulk Test Case",
      steps,
      total: 2,
      passed: 1,
      failed: 1,
      rollup: "fail",
      durationMs: 400,
      kind: "frontend",
      firstFailure: "Element not found",
    };

    // Step 89 has BOTH a step execution screenshot AND a failure screenshot
    const artifacts: ArtifactPublic[] = [
      {
        id: "art_shot_88",
        run_step_id: "step_88",
        kind: "SCREENSHOT",
        mime_type: "image/png",
        size_bytes: 1024,
        created_at: "2026-09-14T00:00:01Z",
      },
      {
        id: "art_shot_89_exec",
        run_step_id: "step_89",
        kind: "SCREENSHOT",
        mime_type: "image/png",
        size_bytes: 1024,
        created_at: "2026-09-14T00:00:02Z",
      },
      {
        id: "art_shot_89_failure",
        run_step_id: "step_89",
        kind: "SCREENSHOT",
        mime_type: "image/png",
        size_bytes: 1024,
        created_at: "2026-09-14T00:00:03Z",
      },
    ];

    renderPanel(group, "FAIL", undefined, true, artifacts);

    // Step navigator buttons should be exactly 2 buttons: Step 1 and Step 2 (not Step 88 or duplicate Step 2)
    const btn1 = await screen.findByTestId("step-nav-btn-1");
    expect(btn1).toBeInTheDocument();
    expect(btn1).toHaveTextContent("Step 1");

    const btn2 = await screen.findByTestId("step-nav-btn-2");
    expect(btn2).toBeInTheDocument();
    expect(btn2).toHaveTextContent("Step 2");

    // Must NOT have buttons labeled with raw global orders 88 or 89
    expect(screen.queryByTestId("step-nav-btn-88")).not.toBeInTheDocument();
    expect(screen.queryByTestId("step-nav-btn-89")).not.toBeInTheDocument();

    // Total step buttons in navigator should be exactly 2 (deduplicated)
    const navigator = screen.getByTestId("step-screenshot-navigator");
    expect(navigator.querySelectorAll("button")).toHaveLength(2);
  });

  it("toggles cleanly between Video and Step captures without rogue snapping, and hides X button in video mode", async () => {
    server.use(
      http.get("*/api/v1/runs/:runId/artifacts/:artifactId", ({ params }) => {
        return HttpResponse.json({
          url: `https://storage.suitest.local/artifacts/${params.artifactId}`,
        });
      }),
    );

    const steps = [makeStep(1, "Step 1", "PASS")];
    const group: CaseGroup = {
      caseId: "tc_media_1",
      casePublicId: "TC-5001",
      caseName: "Media Case",
      steps,
      total: 1,
      passed: 1,
      failed: 0,
      rollup: "pass",
      durationMs: 300,
      kind: "frontend",
      firstFailure: null,
    };

    const artifacts: ArtifactPublic[] = [
      {
        id: "art_video_1",
        run_step_id: "step_1",
        kind: "VIDEO",
        mime_type: "video/webm",
        size_bytes: 4096,
        created_at: "2026-09-14T00:00:01Z",
      },
      {
        id: "art_shot_1",
        run_step_id: "step_1",
        kind: "SCREENSHOT",
        mime_type: "image/png",
        size_bytes: 1024,
        created_at: "2026-09-14T00:00:02Z",
      },
    ];

    renderPanel(group, "PASS", undefined, true, artifacts);

    // Initial state with video + screenshots starts in video mode
    const videoBtn = await screen.findByTestId("preview-mode-video");
    const shotsBtn = screen.getByTestId("preview-mode-screenshots");
    expect(videoBtn).toBeInTheDocument();
    expect(shotsBtn).toBeInTheDocument();

    // In video mode: video player trigger is present
    expect(await screen.findByTestId("case-preview-video-trigger")).toBeInTheDocument();

    // Switch to step captures via mode tab
    await userEvent.click(shotsBtn);
    expect(await screen.findByTestId("case-preview-step-image")).toBeInTheDocument();

    // Click Video button: mode switches back to video cleanly
    await userEvent.click(videoBtn);
    expect(await screen.findByTestId("case-preview-video")).toBeInTheDocument();
  });

  it("renders informative empty state in Artifacts tab with execution settings when media capture is disabled", async () => {
    const group: CaseGroup = {
      caseId: "tc_no_media",
      casePublicId: "TC-1001",
      caseName: "Login Authentication Flow",
      total: 3,
      passed: 3,
      failed: 0,
      rollup: "pass",
      durationMs: 450,
      kind: "frontend",
      firstFailure: null,
      steps: [
        makeStep(1, "Open app", "PASS"),
        makeStep(2, "Enter credentials", "PASS"),
        makeStep(3, "Submit login", "PASS"),
      ],
    };

    renderPanel(group, "PASS", undefined, true, [], {
      headless: true,
      screenshot: "off",
      video: "off",
      highlightSteps: true,
    });

    // Preview tab shows informative placeholder
    const previewPlaceholder = await screen.findByTestId("case-preview-placeholder");
    expect(previewPlaceholder).toHaveTextContent(/No preview available/);
    expect(previewPlaceholder).toHaveTextContent(/Screenshots and video recording were disabled/);

    // Switch to Artifacts tab
    const artifactsTabTrigger = screen.getByRole("tab", { name: "Artifacts" });
    await userEvent.click(artifactsTabTrigger);

    const emptyArtifacts = screen.getByTestId("case-artifacts-empty");
    expect(emptyArtifacts).toBeInTheDocument();
    expect(emptyArtifacts).toHaveTextContent("No media artifacts captured for this case");
    expect(emptyArtifacts).toHaveTextContent(/disabled in Execution Settings/);
    expect(emptyArtifacts).toHaveTextContent("Headless: On");
    expect(emptyArtifacts).toHaveTextContent("Screenshots: Off");
    expect(emptyArtifacts).toHaveTextContent("Video: Off");
    expect(emptyArtifacts).toHaveTextContent("Highlight: Enabled");
  });

  it("renders phase toggle when a step has dual screenshots (before action highlight and after action)", async () => {
    server.use(
      http.get("*/api/v1/runs/:runId/artifacts/:artifactId", ({ params }) => {
        return HttpResponse.json({
          url: `https://storage.suitest.local/artifacts/${params.artifactId}.png`,
        });
      }),
    );

    const steps = [makeStep(1, "Click login button", "PASS")];
    const group: CaseGroup = {
      caseId: "tc_dual_1",
      casePublicId: "TC-5042",
      caseName: "Login flow",
      steps,
      total: 1,
      passed: 1,
      failed: 0,
      rollup: "pass",
      durationMs: 300,
      kind: "frontend",
      firstFailure: null,
    };

    const artifacts: ArtifactPublic[] = [
      {
        id: "art_shot_before",
        run_step_id: "step_1",
        kind: "SCREENSHOT",
        mime_type: "image/png",
        size_bytes: 1024,
        created_at: "2026-09-14T00:00:01Z",
      },
      {
        id: "art_shot_after",
        run_step_id: "step_1",
        kind: "SCREENSHOT",
        mime_type: "image/png",
        size_bytes: 1024,
        created_at: "2026-09-14T00:00:02Z",
      },
    ];

    renderPanel(group, "PASS", undefined, true, artifacts);

    // Step navigator exists
    const stepBtn = await screen.findByTestId("step-nav-btn-1");
    expect(stepBtn).toBeInTheDocument();

    // Click step to activate
    fireEvent.click(stepBtn);

    // Phase navigator should appear with Before and After buttons
    const phaseNav = await screen.findByTestId("step-phase-navigator");
    expect(phaseNav).toBeInTheDocument();

    const beforeBtn = screen.getByTestId("step-phase-btn-before");
    const afterBtn = screen.getByTestId("step-phase-btn-after");
    expect(beforeBtn).toBeInTheDocument();
    expect(afterBtn).toBeInTheDocument();

    // Default image is before shot
    const img = await screen.findByTestId("case-preview-step-image");
    await waitFor(() => {
      expect(img).toHaveAttribute("src", "https://storage.suitest.local/artifacts/art_shot_before.png");
    });

    // Switching to after shot
    fireEvent.click(afterBtn);
    await waitFor(() => {
      expect(img).toHaveAttribute("src", "https://storage.suitest.local/artifacts/art_shot_after.png");
    });
  });

  it("correctly sorts and labels phase buttons when artifacts arrive with after preceding before in array", async () => {
    server.use(
      http.get("/api/v1/runs/:runId/artifacts/:artifactId", ({ params }) => {
        return HttpResponse.json({
          url: `https://storage.suitest.local/artifacts/${params.artifactId}.png`,
        });
      }),
    );

    const steps = [makeStep(1, "Click Button", "PASS")];
    const group: CaseGroup = {
      caseId: "case_dual_inv",
      casePublicId: "TC-9999",
      caseName: "Dual Screenshot Inverted Array Test",
      steps,
      total: 1,
      passed: 1,
      failed: 0,
      rollup: "pass",
      durationMs: 300,
      kind: "frontend",
      firstFailure: null,
    };

    // 'after' artifact is intentionally listed first in the array to simulate DB tie-break inversion
    const artifacts: ArtifactPublic[] = [
      {
        id: "art_shot_after_first",
        run_step_id: "step_1",
        kind: "SCREENSHOT",
        mime_type: "image/png",
        size_bytes: 2048,
        created_at: "2026-09-14T00:00:01Z",
        metadata: { phase: "after" },
      },
      {
        id: "art_shot_before_second",
        run_step_id: "step_1",
        kind: "SCREENSHOT",
        mime_type: "image/png",
        size_bytes: 1024,
        created_at: "2026-09-14T00:00:01Z",
        metadata: { phase: "before", highlight: true },
      },
    ];

    renderPanel(group, "PASS", undefined, true, artifacts);

    const stepBtn = await screen.findByTestId("step-nav-btn-1");
    fireEvent.click(stepBtn);

    const phaseNav = await screen.findByTestId("step-phase-navigator");
    expect(phaseNav).toBeInTheDocument();

    const beforeBtn = screen.getByTestId("step-phase-btn-before");
    const afterBtn = screen.getByTestId("step-phase-btn-after");
    expect(beforeBtn).toHaveTextContent("Before action (highlight)");
    expect(afterBtn).toHaveTextContent("After action");

    // The default active preview must be 'before' (highlighted) despite 'after' being index 0 in the raw array
    const img = await screen.findByTestId("case-preview-step-image");
    await waitFor(() => {
      expect(img).toHaveAttribute(
        "src",
        "https://storage.suitest.local/artifacts/art_shot_before_second.png",
      );
    });

    // Clicking After switches to the after screenshot
    fireEvent.click(afterBtn);
    await waitFor(() => {
      expect(img).toHaveAttribute(
        "src",
        "https://storage.suitest.local/artifacts/art_shot_after_first.png",
      );
    });
  });

  it("allows toggling before and after screenshots directly inside the lightbox modal when zoomed", async () => {
    server.use(
      http.get("/api/v1/runs/:runId/artifacts/:artifactId", ({ params }) => {
        return HttpResponse.json({
          url: `https://storage.suitest.local/artifacts/${params.artifactId}.png`,
        });
      }),
    );

    const steps = [makeStep(1, "Click Submit", "PASS")];
    const group: CaseGroup = {
      caseId: "case_zoom_dual",
      casePublicId: "TC-8888",
      caseName: "Zoom Modal Dual Screenshot Test",
      steps,
      total: 1,
      passed: 1,
      failed: 0,
      rollup: "pass",
      durationMs: 250,
      kind: "frontend",
      firstFailure: null,
    };

    const artifacts: ArtifactPublic[] = [
      {
        id: "modal_shot_before",
        run_step_id: "step_1",
        kind: "SCREENSHOT",
        mime_type: "image/png",
        size_bytes: 1024,
        created_at: "2026-09-14T00:00:01Z",
        metadata: { phase: "before", highlight: true },
      },
      {
        id: "modal_shot_after",
        run_step_id: "step_1",
        kind: "SCREENSHOT",
        mime_type: "image/png",
        size_bytes: 2048,
        created_at: "2026-09-14T00:00:02Z",
        metadata: { phase: "after" },
      },
    ];

    renderPanel(group, "PASS", undefined, true, artifacts);

    // Select step 1
    const stepBtn = await screen.findByTestId("step-nav-btn-1");
    fireEvent.click(stepBtn);

    // Click to open zoom lightbox modal
    const zoomTrigger = await screen.findByTestId("case-preview-zoom-trigger");
    fireEvent.click(zoomTrigger);

    // Lightbox modal should be open
    const modal = await screen.findByTestId("image-lightbox-modal");
    expect(modal).toBeInTheDocument();

    // Lightbox phase navigator should be visible in modal header
    const modalPhaseNav = await screen.findByTestId("lightbox-phase-navigator");
    expect(modalPhaseNav).toBeInTheDocument();

    const modalBeforeBtn = screen.getByTestId("lightbox-phase-btn-before");
    const modalAfterBtn = screen.getByTestId("lightbox-phase-btn-after");
    expect(modalBeforeBtn).toBeInTheDocument();
    expect(modalAfterBtn).toBeInTheDocument();

    // Default image in lightbox is before action
    const lightboxImg = screen.getByTestId("lightbox-image");
    await waitFor(() => {
      expect(lightboxImg).toHaveAttribute(
        "src",
        "https://storage.suitest.local/artifacts/modal_shot_before.png",
      );
    });

    // Click 'After action' inside modal
    fireEvent.click(modalAfterBtn);
    await waitFor(() => {
      expect(lightboxImg).toHaveAttribute(
        "src",
        "https://storage.suitest.local/artifacts/modal_shot_after.png",
      );
    });

    // Keyboard shortcut 'b' inside modal switches back to before
    fireEvent.keyDown(window, { key: "b" });
    await waitFor(() => {
      expect(lightboxImg).toHaveAttribute(
        "src",
        "https://storage.suitest.local/artifacts/modal_shot_before.png",
      );
    });
  });
});
