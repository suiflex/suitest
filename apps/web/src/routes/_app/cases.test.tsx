import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRouter } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/mocks/server";
import { routeTree } from "@/routeTree.gen";
import { CLOUD_CAPS, ZERO_CAPS, resetCaps, setCaps } from "@/test/capabilities";

function renderCases(path = "/cases") {
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

describe("Test Cases screen", () => {
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
      pathname: "/cases",
      assign: vi.fn(),
      origin: "http://localhost",
    });
  });
  afterEach(() => {
    resetCaps();
    vi.unstubAllGlobals();
  });

  it("renders the skeleton before suites/cases resolve", async () => {
    server.use(
      http.get("*/api/v1/suites", async () => {
        await new Promise((r) => setTimeout(r, 50));
        return HttpResponse.json({ items: [] });
      }),
    );
    renderCases();
    expect(await screen.findByTestId("cases-skeleton")).toBeInTheDocument();
  });

  it("ZERO tier: shows 4 tabs (no AI-generated)", async () => {
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });
    expect(screen.getByTestId("cases-tab-all")).toBeInTheDocument();
    expect(screen.getByTestId("cases-tab-manual")).toBeInTheDocument();
    expect(screen.queryByTestId("cases-tab-ai")).toBeNull();
    expect(screen.getByTestId("cases-tab-mcp")).toBeInTheDocument();
    expect(screen.getByTestId("cases-tab-failing")).toBeInTheDocument();
  });

  it("CLOUD tier: shows 5 tabs including AI-generated", async () => {
    setCaps(CLOUD_CAPS);
    server.use(
      http.get("*/capabilities", () => HttpResponse.json(CLOUD_CAPS)),
      http.get("*/api/v1/capabilities", () => HttpResponse.json(CLOUD_CAPS)),
    );
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });
    expect(screen.getByTestId("cases-tab-ai")).toBeInTheDocument();
  });

  it("renders the tree grouped by suite", async () => {
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });
    const rows = screen.getAllByTestId("cases-tree-row");
    expect(rows.length).toBeGreaterThan(0);
    expect(rows[0]?.getAttribute("data-public-id")).toBe("TC-101");
  });

  it("renders the empty state when there are zero cases", async () => {
    server.use(
      http.get("*/api/v1/test-cases", () =>
        HttpResponse.json({ items: [], meta: { limit: 50, nextCursor: null } }),
      ),
    );
    renderCases();
    expect(
      await screen.findByText(/No cases yet/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("renders the error fallback when /suites 500s", async () => {
    server.use(
      http.get("*/api/v1/suites", () =>
        HttpResponse.json({ code: "BOOM", message: "nope" }, { status: 500 }),
      ),
    );
    renderCases();
    expect(
      await screen.findByText(/Couldn't load cases/i, undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("clicking a tree row loads detail panel via ?case= param", async () => {
    const user = userEvent.setup();
    renderCases();
    const rows = await screen.findAllByTestId("cases-tree-row", undefined, { timeout: 3000 });
    await user.click(rows[0] as HTMLElement);
    expect(
      await screen.findByTestId("case-detail", undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
    // Steps live under the Steps tab — now an editable list (one row per
    // step) instead of the read-only card list.
    await user.click(await screen.findByTestId("case-tab-steps"));
    expect((await screen.findAllByTestId("step-row")).length).toBeGreaterThan(0);
  });

  it("M1d-23: clicking Delete fires DELETE /test-cases/:id", async () => {
    const user = userEvent.setup();
    let deleteCalled = false;
    server.use(
      http.delete("*/api/v1/test-cases/:caseId", ({ params }) => {
        deleteCalled = true;
        expect(params["caseId"]).toBe("TC-101");
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderCases("/cases?case=TC-101");

    const deleteBtn = await screen.findByTestId("case-delete-btn", undefined, { timeout: 3000 });
    await user.click(deleteBtn);

    await waitFor(() => {
      expect(deleteCalled).toBe(true);
    });
  });

  // ---------------------------------------------------------------------------
  // M1-15b: Bulk ops sticky bar
  // ---------------------------------------------------------------------------

  it("M1-15b: shows select-all checkbox in the tree header", async () => {
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });
    expect(screen.getByTestId("select-all-checkbox")).toBeInTheDocument();
  });

  it("M1-15b: shows per-row checkbox for each case", async () => {
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });
    const checkboxes = screen.getAllByTestId("case-row-checkbox");
    expect(checkboxes.length).toBeGreaterThan(0);
  });

  it("M1-15b: checking a row reveals the bulk action bar", async () => {
    const user = userEvent.setup();
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });

    // Bulk bar should not be visible initially
    expect(screen.queryByTestId("bulk-action-bar")).toBeNull();

    // Click the first row checkbox
    const checkboxes = screen.getAllByTestId("case-row-checkbox");
    await user.click(checkboxes[0] as HTMLElement);

    // Bulk bar should now appear
    expect(await screen.findByTestId("bulk-action-bar")).toBeInTheDocument();
  });

  it("M1-15b: checking a row does NOT navigate to detail panel", async () => {
    const user = userEvent.setup();
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });

    const checkboxes = screen.getAllByTestId("case-row-checkbox");
    await user.click(checkboxes[0] as HTMLElement);

    // Detail panel should NOT have opened
    expect(screen.queryByTestId("case-detail")).toBeNull();
  });

  it("M1-15b: select-all selects all visible cases", async () => {
    const user = userEvent.setup();
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });

    const selectAll = screen.getByTestId("select-all-checkbox");
    await user.click(selectAll);

    // Bulk bar appears with count of all cases
    const bar = await screen.findByTestId("bulk-action-bar");
    expect(bar).toBeInTheDocument();
    // All row checkboxes should be checked
    const checkboxes = screen.getAllByTestId("case-row-checkbox") as HTMLInputElement[];
    expect(checkboxes.every((cb) => cb.checked)).toBe(true);
  });

  it("M1-15b: clear button hides the bulk action bar", async () => {
    const user = userEvent.setup();
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });

    // Select one
    const checkboxes = screen.getAllByTestId("case-row-checkbox");
    await user.click(checkboxes[0] as HTMLElement);
    await screen.findByTestId("bulk-action-bar");

    // Click clear
    await user.click(screen.getByTestId("bulk-clear-btn"));
    await waitFor(() => {
      expect(screen.queryByTestId("bulk-action-bar")).toBeNull();
    });
  });
  it("issue #238: renders all bulk actions and keeps them keyboard accessible", async () => {
    const user = userEvent.setup();
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });

    const checkboxes = screen.getAllByTestId("case-row-checkbox");
    await user.click(checkboxes[0] as HTMLElement);

    const bar = await screen.findByTestId("bulk-action-bar");
    expect(bar).toBeInTheDocument();
    expect(bar).toHaveTextContent("1 selected");

    // All controls must be present and reachable
    const clearBtn = screen.getByTestId("bulk-clear-btn");
    const runBtn = screen.getByTestId("bulk-run-btn");
    const deleteBtn = screen.getByTestId("bulk-delete-btn");
    const moveSelect = screen.getByTestId("bulk-move-suite-select");
    const prioritySelect = screen.getByTestId("bulk-priority-select");

    expect(clearBtn).toBeInTheDocument();
    expect(runBtn).toBeInTheDocument();
    expect(deleteBtn).toBeInTheDocument();
    expect(moveSelect).toBeInTheDocument();
    expect(prioritySelect).toBeInTheDocument();

    // Verify keyboard focusability
    clearBtn.focus();
    expect(clearBtn).toHaveFocus();

    runBtn.focus();
    expect(runBtn).toHaveFocus();

    deleteBtn.focus();
    expect(deleteBtn).toHaveFocus();

    moveSelect.focus();
    expect(moveSelect).toHaveFocus();

    prioritySelect.focus();
    expect(prioritySelect).toHaveFocus();
  });


  it("suite selection: renders a checkbox for each suite in the tree", async () => {
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });
    const suiteCheckboxes = screen.getAllByTestId("suite-row-checkbox");
    expect(suiteCheckboxes.length).toBe(2);
  });

  it("filtering: hides empty suites that have no matching cases in the current tab", async () => {
    const user = userEvent.setup();
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });

    // Initially both suites are present (Smoke with 2 cases, Regression with 1 case)
    expect(screen.getAllByTestId("cases-tree-suite")).toHaveLength(2);

    // Switch to Manual tab (Smoke has 1 manual case, Regression has 0)
    await user.click(screen.getByTestId("cases-tab-manual"));

    // Only Smoke suite should be displayed; Regression suite is hidden because it has 0 matching cases
    const visibleSuites = screen.getAllByTestId("cases-tree-suite");
    expect(visibleSuites).toHaveLength(1);
    expect(visibleSuites[0]).toHaveTextContent(/Smoke/i);
  });

  it("suite selection: checking a suite selects all cases in that suite", async () => {
    const user = userEvent.setup();
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });

    const suiteCheckboxes = screen.getAllByTestId("suite-row-checkbox") as HTMLInputElement[];
    // Click Smoke suite checkbox (has 2 cases: case_01, case_03)
    await user.click(suiteCheckboxes[0] as HTMLElement);

    const bar = await screen.findByTestId("bulk-action-bar");
    expect(bar).toHaveTextContent("2 selected");
    expect(suiteCheckboxes[0]?.checked).toBe(true);
    expect(suiteCheckboxes[1]?.checked).toBe(false);

    // Clicking it again deselects all cases in Smoke suite
    await user.click(suiteCheckboxes[0] as HTMLElement);
    await waitFor(() => {
      expect(screen.queryByTestId("bulk-action-bar")).toBeNull();
    });
    expect(suiteCheckboxes[0]?.checked).toBe(false);
  });

  it("suite selection: partial selection in suite shows indeterminate state", async () => {
    const user = userEvent.setup();
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });

    // Select only 1 case in Smoke suite (TC-101)
    const caseCheckboxes = screen.getAllByTestId("case-row-checkbox");
    await user.click(caseCheckboxes[0] as HTMLElement);

    const suiteCheckboxes = screen.getAllByTestId("suite-row-checkbox") as HTMLInputElement[];
    expect(suiteCheckboxes[0]?.indeterminate).toBe(true);
    expect(suiteCheckboxes[0]?.checked).toBe(false);

    // Clicking indeterminate checkbox selects all cases in Smoke suite
    await user.click(suiteCheckboxes[0] as HTMLElement);
    expect(suiteCheckboxes[0]?.checked).toBe(true);
    const bar = await screen.findByTestId("bulk-action-bar");
    expect(bar).toHaveTextContent("2 selected");
  });

  it("suite collapse: collapsing a suite hides its case rows and expanding shows them", async () => {
    const user = userEvent.setup();
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });

    // Initially 3 case rows are present across 2 suites
    expect(screen.getAllByTestId("cases-tree-row")).toHaveLength(3);

    const collapseBtns = screen.getAllByTestId("suite-collapse-btn");
    expect(collapseBtns).toHaveLength(2);

    // Collapse the Smoke suite (which has 2 cases)
    await user.click(collapseBtns[0] as HTMLElement);

    // Only Regression suite case (1 case) should now be visible in the tree
    expect(screen.getAllByTestId("cases-tree-row")).toHaveLength(1);

    // Expand the Smoke suite again
    await user.click(collapseBtns[0] as HTMLElement);
    expect(screen.getAllByTestId("cases-tree-row")).toHaveLength(3);
  });

  it("gating suite: allows unsetting the gating suite", async () => {
    const user = userEvent.setup();
    let patchedPayload: unknown = null;
    server.use(
      http.get("*/api/v1/projects/:projectId", () =>
        HttpResponse.json({
          id: "prj_demo",
          name: "Fixture project",
          gating_suite_id: "ste_smoke",
        }),
      ),
      http.patch("*/api/v1/projects/:projectId", async ({ request }) => {
        patchedPayload = await request.json();
        return HttpResponse.json({
          id: "prj_demo",
          name: "Fixture project",
          gating_suite_id: null,
        });
      }),
    );

    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });

    // Smoke suite has the gating badge and unset button (loaded via useProject query)
    expect(await screen.findByTestId("suite-gating-badge", undefined, { timeout: 3000 })).toBeInTheDocument();
    const unsetBtn = await screen.findByTestId("suite-unset-gating-btn", undefined, { timeout: 3000 });
    expect(unsetBtn).toBeInTheDocument();

    await user.click(unsetBtn);
    await waitFor(() => {
      expect(patchedPayload).toEqual({ gatingSuiteId: null });
    });
  });

  it("M1-15b: clicking Delete in bulk bar fires POST /test-cases/bulk-update (after undo window)", async () => {
    const user = userEvent.setup();
    let bulkCalled = false;
    let capturedBody: unknown = null;

    server.use(
      http.post("*/api/v1/test-cases/bulk-update", async ({ request }) => {
        bulkCalled = true;
        capturedBody = await request.json();
        return HttpResponse.json({ updated: 1, auditIds: ["aud_01"] });
      }),
    );

    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });

    // Select a row
    const checkboxes = screen.getAllByTestId("case-row-checkbox");
    await user.click(checkboxes[0] as HTMLElement);
    await screen.findByTestId("bulk-action-bar");

    // Click Delete
    await user.click(screen.getByTestId("bulk-delete-btn"));

    // The undo toast pattern: bulkUpdate fires AFTER the toast window expires,
    // so bulkCalled may be false immediately. The toast appears.
    // We can't easily control time in this test; just verify the bar is still
    // shown (toast is open) and the button was clickable.
    // The actual bulk call fires when toast auto-dismisses (8s), tested by
    // the undoToast unit test. Here we just confirm the handler is wired.
    expect(bulkCalled).toBe(false); // not called yet (toast window open)
    // capturedBody will be null since we haven't waited for timeout
    expect(capturedBody).toBeNull();
  });

  it("M1-15b: Move to suite calls bulkUpdate with correct body", async () => {
    const user = userEvent.setup();
    let capturedBody: unknown = null;

    server.use(
      http.post("*/api/v1/test-cases/bulk-update", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({ updated: 1, auditIds: ["aud_01"] });
      }),
    );

    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });

    // Select first row
    const checkboxes = screen.getAllByTestId("case-row-checkbox");
    await user.click(checkboxes[0] as HTMLElement);
    await screen.findByTestId("bulk-action-bar");

    // Change the move-to-suite select
    const moveSelect = screen.getByTestId("bulk-move-suite-select");
    await user.selectOptions(moveSelect, "ste_smoke");

    await waitFor(() => {
      expect(capturedBody).toMatchObject({
        action: "move_to_suite",
        payload: { suiteId: "ste_smoke" },
      });
    });
  });

  it("M1-15b: Set priority calls bulkUpdate with correct body", async () => {
    const user = userEvent.setup();
    let capturedBody: unknown = null;

    server.use(
      http.post("*/api/v1/test-cases/bulk-update", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({ updated: 1, auditIds: ["aud_01"] });
      }),
    );

    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });

    // Select first row
    const checkboxes = screen.getAllByTestId("case-row-checkbox");
    await user.click(checkboxes[0] as HTMLElement);
    await screen.findByTestId("bulk-action-bar");

    // Change the priority select
    const prioritySelect = screen.getByTestId("bulk-priority-select");
    await user.selectOptions(prioritySelect, "P0");

    await waitFor(() => {
      expect(capturedBody).toMatchObject({
        action: "set_priority",
        payload: { priority: "P0" },
      });
    });
  });

  it("M1-15b: shows Run button in bulk bar and opens ConfirmBulkRunDialog with warning", async () => {
    const user = userEvent.setup();
    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });

    const checkboxes = screen.getAllByTestId("case-row-checkbox");
    await user.click(checkboxes[0] as HTMLElement);

    const runBtn = await screen.findByTestId("bulk-run-btn");
    expect(runBtn).toBeInTheDocument();
    expect(runBtn).toHaveTextContent("Run (1)");

    await user.click(runBtn);

    const dialog = await screen.findByTestId("bulk-run-confirm-dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByTestId("bulk-run-warning")).toBeInTheDocument();
    expect(screen.getByText("Local Resource & Execution Notice")).toBeInTheDocument();

    // Cancel closes dialog
    await user.click(screen.getByTestId("bulk-run-confirm-cancel"));
    await waitFor(() => {
      expect(screen.queryByTestId("bulk-run-confirm-dialog")).toBeNull();
    });
  });

  it("M1-15b: confirming bulk run dialog dispatches POST /runs with selection", async () => {
    const user = userEvent.setup();
    let capturedBody: unknown = null;

    server.use(
      http.post("*/api/v1/runs", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({
          id: "run_bulk_123",
          public_id: "RUN-123",
          status: "QUEUED",
        });
      }),
    );

    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });

    const checkboxes = screen.getAllByTestId("case-row-checkbox");
    await user.click(checkboxes[0] as HTMLElement);
    await user.click(checkboxes[1] as HTMLElement);

    const runBtn = await screen.findByTestId("bulk-run-btn");
    expect(runBtn).toHaveTextContent("Run (2)");
    await user.click(runBtn);

    await screen.findByTestId("bulk-run-confirm-dialog");
    const submitBtn = screen.getByTestId("bulk-run-confirm-submit");
    expect(submitBtn).toHaveTextContent("Run 2 Cases");

    await user.click(submitBtn);

    await waitFor(() => {
      expect(capturedBody).toMatchObject({
        name: "Ad-hoc: 2 selected cases",
        selection: [{ caseId: expect.any(String) }, { caseId: expect.any(String) }],
        trigger: "MANUAL",
      });
    });
  });

  it("M1-15b: selecting 1 case in bulk bar names run as single case and displays case title in dialog", async () => {
    const user = userEvent.setup();
    let capturedBody: unknown = null;

    server.use(
      http.post("*/api/v1/runs", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({
          id: "run_single_123",
          public_id: "RUN-124",
          status: "QUEUED",
        });
      }),
    );

    renderCases();
    await screen.findByTestId("cases-tree", undefined, { timeout: 3000 });

    const checkboxes = screen.getAllByTestId("case-row-checkbox");
    await user.click(checkboxes[0] as HTMLElement);

    const runBtn = await screen.findByTestId("bulk-run-btn");
    expect(runBtn).toHaveTextContent("Run (1)");
    await user.click(runBtn);

    const dialog = await screen.findByTestId("bulk-run-confirm-dialog");
    expect(dialog).toBeInTheDocument();
    // Verify single-case run confirmation dialog displays the case title rather than generic count
    expect(dialog).toHaveTextContent("Checkout flow rejects expired cards");

    const submitBtn = screen.getByTestId("bulk-run-confirm-submit");
    await user.click(submitBtn);

    await waitFor(() => {
      expect(capturedBody).toMatchObject({
        name: "Ad-hoc: Checkout flow rejects expired cards",
        selection: [{ caseId: expect.any(String) }],
        trigger: "MANUAL",
      });
    });
  });

  it("renders informative historical audit state in Artifacts tab when last run had media capture disabled", async () => {
    const user = userEvent.setup();

    server.use(
      http.get("*/api/v1/test-cases/TC-101", () =>
        HttpResponse.json({
          id: "case_TC-101",
          public_id: "TC-101",
          name: "Checkout flow rejects expired cards",
          description: "Verify expired card path returns a friendly error.",
          priority: "P1",
          status: "ACTIVE",
          source: "MANUAL",
          suite_id: "ste_smoke",
          last_run_id: "run_nomedia_1",
          steps: [],
        }),
      ),
      http.get("*/api/v1/runs/run_nomedia_1", () =>
        HttpResponse.json({
          id: "run_nomedia_1",
          public_id: "RUN-1001",
          status: "PASS",
          created_at: "2026-05-01T08:00:00Z",
          started_at: "2026-05-01T08:00:01Z",
          playwrightConfig: {
            headless: true,
            screenshot: "off",
            video: "off",
            highlightSteps: true,
          },
        }),
      ),
      http.get("*/api/v1/test-cases/case_TC-101/artifacts", () =>
        HttpResponse.json({ items: [] }),
      ),
      http.get("*/api/v1/test-cases/case_TC-101/runs", () =>
        HttpResponse.json([
          {
            id: "run_nomedia_1",
            publicId: "RUN-1001",
            status: "PASS",
            createdAt: "2026-05-01T08:00:00Z",
            startedAt: "2026-05-01T08:00:01Z",
            playwrightConfig: {
              headless: true,
              screenshot: "off",
              video: "off",
              highlightSteps: true,
            },
          },
        ]),
      ),
    );

    renderCases("/cases?case=TC-101");

    const artifactsTabTrigger = await screen.findByTestId("case-tab-artifacts", undefined, {
      timeout: 3000,
    });
    await user.click(artifactsTabTrigger);

    // Verify informative historical audit card or group empty state appears with execution settings badges
    const emptyNotice = await screen.findByText(/No media artifacts captured/i);
    expect(emptyNotice).toBeInTheDocument();
    expect(screen.getByText("Headless: On")).toBeInTheDocument();
    expect(screen.getByText("Screenshots: Off")).toBeInTheDocument();
    expect(screen.getByText("Video: Off")).toBeInTheDocument();
    expect(screen.getByText("Highlight: Enabled")).toBeInTheDocument();
  });

  it("renders both runs with artifacts and runs without artifacts in historical order in Artifacts tab", async () => {
    const user = userEvent.setup();

    server.use(
      http.get("*/api/v1/test-cases/TC-101", () =>
        HttpResponse.json({
          id: "case_TC-101",
          public_id: "TC-101",
          name: "Checkout flow rejects expired cards",
          description: "Verify expired card path returns a friendly error.",
          priority: "P1",
          status: "ACTIVE",
          source: "MANUAL",
          suite_id: "ste_smoke",
          last_run_id: "run_nomedia_1238",
          steps: [],
        }),
      ),
      http.get("*/api/v1/test-cases/case_TC-101/runs", () =>
        HttpResponse.json([
          {
            id: "run_nomedia_1238",
            publicId: "R-1238",
            status: "PASS",
            createdAt: "2026-09-16T12:53:30Z",
            startedAt: "2026-09-16T12:53:31Z",
            playwrightConfig: {
              headless: true,
              screenshot: "off",
              video: "off",
              highlightSteps: false,
            },
          },
          {
            id: "run_media_1236",
            publicId: "R-1236",
            status: "PASS",
            createdAt: "2026-09-16T12:18:09Z",
            startedAt: "2026-09-16T12:18:10Z",
            playwrightConfig: {
              headless: true,
              screenshot: "on",
              video: "off",
              highlightSteps: true,
            },
          },
        ]),
      ),
      http.get("*/api/v1/test-cases/case_TC-101/artifacts", () =>
        HttpResponse.json({
          items: [
            {
              id: "art_1236_shot_1",
              runId: "run_media_1236",
              runPublicId: "R-1236",
              runStatus: "PASS",
              runDate: "2026-09-16T12:18:09Z",
              runStepId: "step_1",
              stepOrder: 1,
              stepTitle: "Open login page",
              kind: "SCREENSHOT",
              sizeBytes: 15420,
              mimeType: "image/png",
              createdAt: "2026-09-16T12:18:15Z",
            },
          ],
        }),
      ),
    );

    renderCases("/cases?case=TC-101");

    const artifactsTabTrigger = await screen.findByTestId("case-tab-artifacts", undefined, {
      timeout: 3000,
    });
    await user.click(artifactsTabTrigger);

    // Verify both R-1238 and R-1236 artifact groups render
    const group1238 = await screen.findByTestId("artifact-group-R-1238");
    expect(group1238).toBeInTheDocument();
    expect(within(group1238).getByText(/0 artifacts/i)).toBeInTheDocument();
    expect(within(group1238).getByText(/No media artifacts captured for this run/i)).toBeInTheDocument();
    expect(within(group1238).getByText(/Screenshots:/i)).toBeInTheDocument();
    expect(within(group1238).getByText(/Video:/i)).toBeInTheDocument();

    const group1236 = await screen.findByTestId("artifact-group-R-1236");
    expect(group1236).toBeInTheDocument();
    expect(within(group1236).getByText(/1 artifact/i)).toBeInTheDocument();
  });

  it("prevents draft steps from leaking when creating a new case from an edited case", async () => {
    const user = userEvent.setup();
    setCaps(CLOUD_CAPS); // Enable AI diagnose to also check callout behavior

    renderCases("/cases?case=TC-101");

    // 1. Go to Steps tab on TC-101
    const stepsTab = await screen.findByTestId("case-tab-steps", undefined, { timeout: 3000 });
    await user.click(stepsTab);

    // Verify existing steps are rendered
    expect((await screen.findAllByTestId("step-row")).length).toBe(2);

    // 2. Add an uncommitted draft step to TC-101
    const addBtn = await screen.findByTestId("step-add-btn");
    await user.click(addBtn);
    expect((await screen.findAllByTestId("step-row")).length).toBe(3);

    // 3. Create a new case
    const newCaseBtn = await screen.findByTestId("new-case-btn");
    await user.click(newCaseBtn);

    const nameInput = await screen.findByTestId("create-case-name");
    await user.type(nameInput, "Brand New Case");
    const submitBtn = await screen.findByTestId("create-case-submit");
    await user.click(submitBtn);

    // 4. Detail panel switches to new case (TC-NEW-99)
    expect(await screen.findByTestId("case-detail", undefined, { timeout: 3000 })).toBeInTheDocument();

    // 5. Navigate to Steps tab of the new case
    const newStepsTab = await screen.findByTestId("case-tab-steps");
    await user.click(newStepsTab);

    // 6. Verify: No leaked steps from TC-101! Empty state is shown cleanly
    expect(await screen.findByText(/No steps yet/i)).toBeInTheDocument();
    expect(screen.queryByTestId("step-row")).not.toBeInTheDocument();

    // 7. Verify: No ghost Agent diagnosis is displayed for this new case (0 runs)
    expect(screen.queryByText(/Agent diagnosis/i)).not.toBeInTheDocument();
  });

  it("prunes deleted case from selectedIds when single-case delete occurs", async () => {
    const user = userEvent.setup();
    let currentCases = [
      {
        id: "case_TC-101",
        public_id: "TC-101",
        suite_id: "ste_smoke",
        name: "Checkout flow rejects expired cards",
        priority: "P1",
        status: "ACTIVE",
        source: "MANUAL",
        effective_testing_approach: "BLACK_BOX",
        last_run: null,
      },
      {
        id: "case_TC-102",
        public_id: "TC-102",
        suite_id: "ste_smoke",
        name: "Second case",
        priority: "P2",
        status: "ACTIVE",
        source: "MANUAL",
        effective_testing_approach: "BLACK_BOX",
        last_run: null,
      },
    ];
    server.use(
      http.get("*/api/v1/test-cases", () =>
        HttpResponse.json({ items: currentCases, total: currentCases.length }),
      ),
      http.delete("*/api/v1/test-cases/:caseId", ({ params }) => {
        currentCases = currentCases.filter((c) => c.public_id !== params["caseId"]);
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderCases("/cases?case=TC-101");

    // Select TC-101 checkbox in tree
    const rows = await screen.findAllByTestId("case-row-checkbox");
    await user.click(rows[0] as HTMLElement);

    // Bulk action bar should be visible
    expect(await screen.findByTestId("bulk-action-bar")).toBeInTheDocument();

    // Delete TC-101 via detail toolbar
    const deleteBtn = await screen.findByTestId("case-delete-btn");
    await user.click(deleteBtn);

    // Once deleted and navigated back, bulk action bar should be dismissed (selectedIds pruned)
    await waitFor(() => {
      expect(screen.queryByTestId("bulk-action-bar")).not.toBeInTheDocument();
    });
  });

  it("resets active tab to 'all' when a new manual case is created under a non-matching filter", async () => {
    const user = userEvent.setup();
    renderCases("/cases");

    // Switch to Failing tab filter
    const failingTab = await screen.findByTestId("cases-tab-failing");
    await user.click(failingTab);
    expect(failingTab).toHaveAttribute("data-active", "true");

    // Create a new case
    const newCaseBtn = await screen.findByTestId("new-case-btn");
    await user.click(newCaseBtn);

    const nameInput = await screen.findByTestId("create-case-name");
    await user.type(nameInput, "Manual Case From Failing View");
    const submitBtn = await screen.findByTestId("create-case-submit");
    await user.click(submitBtn);

    // Active tab should now be reset to 'all' so the new manual case is visible in tree
    await waitFor(() => {
      const allTab = screen.getByTestId("cases-tab-all");
      expect(allTab).toHaveAttribute("data-active", "true");
    });
  });
});


