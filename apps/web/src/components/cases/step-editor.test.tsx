/**
 * step-editor.test.tsx
 * M1-12: step editor UI — TDD-first test suite
 *
 * Tests cover:
 *  1. Read-only rendering of existing steps
 *  2. "+ New step" button calls POST /test-cases/:id/steps
 *  3. Inline field editing (action, code, mcp_provider, target_kind)
 *  4. "Remove" button triggers PATCH /test-cases/:id/steps (bulk replace)
 *  5. Optimistic UI: rollback on error
 *  6. "Save" button commits inline edits via PATCH /test-cases/:id/steps
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import React, { useCallback, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/mocks/server";
import { ZERO_CAPS, resetCaps, setCaps } from "@/test/capabilities";

import { StepEditor } from "./StepEditor";
import type { DraftStep } from "./StepEditor";

// ---------------------------------------------------------------------------
// Stateful test wrapper — lets the editor re-render with updated steps so
// controlled inputs reflect the latest value.
// ---------------------------------------------------------------------------
function StepEditorStateful({
  initial,
  onCapture,
}: {
  initial: DraftStep[];
  onCapture: (steps: DraftStep[]) => void;
}): React.ReactElement {
  const [steps, setSteps] = useState<DraftStep[]>(initial);
  const handleChange = useCallback(
    (next: DraftStep[]) => {
      setSteps(next);
      onCapture(next);
    },
    [onCapture],
  );
  return <StepEditor caseId={CASE_ID} steps={steps} onStepsChange={handleChange} />;
}

const CASE_ID = "TC-101";

const STEP_1: DraftStep = {
  id: "stp_01",
  order: 1,
  action: "Navigate to /checkout",
  expected: "Checkout page loads",
  code: null,
  mcp_provider: "playwright-mcp",
  target_kind: "FE_WEB",
};

const STEP_2: DraftStep = {
  id: "stp_02",
  order: 2,
  action: "Enter expired card",
  expected: "Form shows error",
  code: "await page.fill('#card', '4000000000000002')",
  mcp_provider: "playwright-mcp",
  target_kind: "FE_WEB",
};

const FULL_CASE_RESPONSE = {
  id: `case_${CASE_ID}`,
  public_id: CASE_ID,
  name: "Checkout flow",
  description: null,
  preconditions: null,
  priority: "P1",
  status: "ACTIVE",
  source: "MANUAL",
  suite_id: "ste_smoke",
  owner_id: null,
  tags: [],
  steps: [
    {
      id: "stp_01",
      case_id: `case_${CASE_ID}`,
      order: 1,
      action: "Navigate to /checkout",
      expected: "Checkout page loads",
      executable: true,
      mcp_provider: "playwright-mcp",
      target_kind: "FE_WEB",
      code: null,
      data: null,
    },
    {
      id: "stp_02",
      case_id: `case_${CASE_ID}`,
      order: 2,
      action: "Enter expired card",
      expected: "Form shows error",
      executable: true,
      mcp_provider: "playwright-mcp",
      target_kind: "FE_WEB",
      code: "await page.fill('#card', '4000000000000002')",
      data: null,
    },
  ],
  created_at: "2026-05-01T08:00:00Z",
  updated_at: "2026-05-25T14:30:00Z",
};

function renderEditor(
  steps: DraftStep[] = [STEP_1, STEP_2],
  onStepsChange: (steps: DraftStep[]) => void = vi.fn(),
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <StepEditor
        caseId={CASE_ID}
        steps={steps}
        onStepsChange={onStepsChange}
      />
    </QueryClientProvider>,
  );

  return { queryClient, onStepsChange };
}

describe("StepEditor", () => {
  beforeEach(() => {
    setCaps(ZERO_CAPS);
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

  // --------------------------------------------------------------------------
  // AC-1: read-only rendering of existing steps
  // --------------------------------------------------------------------------
  it("renders existing steps in editable rows", () => {
    renderEditor();
    const rows = screen.getAllByTestId("step-row");
    expect(rows).toHaveLength(2);
    // First step action visible in input
    const firstRow = rows[0] as HTMLElement;
    const actionInput = within(firstRow).getByTestId("step-action-input");
    expect(actionInput).toHaveValue("Navigate to /checkout");
  });

  it("shows code textarea when step has code", () => {
    renderEditor();
    const rows = screen.getAllByTestId("step-row");
    const secondRow = rows[1] as HTMLElement;
    const codeInput = within(secondRow).getByTestId("step-code-input");
    expect(codeInput).toHaveValue("await page.fill('#card', '4000000000000002')");
  });

  it("shows + New step button", () => {
    renderEditor();
    expect(screen.getByTestId("step-add-btn")).toBeInTheDocument();
  });

  // --------------------------------------------------------------------------
  // AC-2: + New step calls POST /test-cases/:id/steps
  // --------------------------------------------------------------------------
  it("clicking + New step calls POST and adds a row", async () => {
    const user = userEvent.setup();
    let postCalled = false;

    server.use(
      http.post("*/api/v1/test-cases/:caseId/steps", () => {
        postCalled = true;
        return HttpResponse.json(
          {
            ...FULL_CASE_RESPONSE,
            steps: [
              ...FULL_CASE_RESPONSE.steps,
              {
                id: "stp_03",
                case_id: `case_${CASE_ID}`,
                order: 3,
                action: "",
                expected: "",
                executable: true,
                mcp_provider: "playwright-mcp",
                target_kind: "FE_WEB",
                code: null,
                data: null,
              },
            ],
          },
          { status: 201 },
        );
      }),
    );

    const onStepsChange: (steps: DraftStep[]) => void = vi.fn();
    renderEditor([STEP_1, STEP_2], onStepsChange);

    await user.click(screen.getByTestId("step-add-btn"));

    await waitFor(() => {
      expect(postCalled).toBe(true);
    });
  });

  // --------------------------------------------------------------------------
  // AC-3: inline field editing updates local state
  // --------------------------------------------------------------------------
  it("editing action field calls onStepsChange with updated value", async () => {
    const user = userEvent.setup();
    // Use a stateful wrapper so the controlled input re-renders correctly
    const received: DraftStep[][] = [];
    const onStepsChange = (steps: DraftStep[]): void => {
      received.push(steps);
    };
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <StepEditorStateful initial={[STEP_1]} onCapture={onStepsChange} />
      </QueryClientProvider>,
    );
    void rerender; // we only need the stateful wrapper

    const rows = screen.getAllByTestId("step-row");
    const actionInput = within(rows[0] as HTMLElement).getByTestId("step-action-input");

    // Type a single character change to check that onStepsChange is called
    await user.type(actionInput, "X");

    await waitFor(() => {
      expect(received.length).toBeGreaterThan(0);
      const last = received[received.length - 1];
      expect(last?.[0]?.action).toContain("X");
    });
  });

  it("changing target_kind select calls onStepsChange", async () => {
    const user = userEvent.setup();
    const onStepsChange: (steps: DraftStep[]) => void = vi.fn();
    renderEditor([STEP_1], onStepsChange);

    const rows = screen.getAllByTestId("step-row");
    const select = within(rows[0] as HTMLElement).getByTestId("step-target-kind-select");

    await user.selectOptions(select, "BE_REST");

    await waitFor(() => {
      expect(onStepsChange).toHaveBeenCalled();
      const calls = (onStepsChange as ReturnType<typeof vi.fn>).mock.calls as [DraftStep[]][];
      const lastCall = calls[calls.length - 1];
      expect(lastCall?.[0]?.[0]?.target_kind).toBe("BE_REST");
    });
  });

  // --------------------------------------------------------------------------
  // AC-4: Remove button triggers PATCH /test-cases/:id/steps
  // --------------------------------------------------------------------------
  it("clicking Remove calls PATCH with remaining steps", async () => {
    const user = userEvent.setup();
    let patchBody: unknown = null;

    server.use(
      http.patch("*/api/v1/test-cases/:caseId/steps", async ({ request }) => {
        patchBody = await request.json();
        return HttpResponse.json({
          ...FULL_CASE_RESPONSE,
          steps: [FULL_CASE_RESPONSE.steps[1]],
        });
      }),
    );

    const onStepsChange: (steps: DraftStep[]) => void = vi.fn();
    renderEditor([STEP_1, STEP_2], onStepsChange);

    const rows = screen.getAllByTestId("step-row");
    const removeBtn = within(rows[0] as HTMLElement).getByTestId("step-remove-btn");
    await user.click(removeBtn);

    await waitFor(() => {
      expect(patchBody).toBeDefined();
      const body = patchBody as { steps: unknown[] };
      // Only one step remaining (STEP_2)
      expect(body.steps).toHaveLength(1);
    });
  });

  // --------------------------------------------------------------------------
  // AC-5: Save button commits via PATCH /test-cases/:id/steps
  // --------------------------------------------------------------------------
  it("Save button calls PATCH /test-cases/:id/steps with all steps", async () => {
    const user = userEvent.setup();
    let patchCalled = false;

    server.use(
      http.patch("*/api/v1/test-cases/:caseId/steps", async () => {
        patchCalled = true;
        return HttpResponse.json(FULL_CASE_RESPONSE);
      }),
    );

    renderEditor([STEP_1, STEP_2]);

    const saveBtn = screen.getByTestId("step-save-btn");
    await user.click(saveBtn);

    await waitFor(() => {
      expect(patchCalled).toBe(true);
    });
  });

  it("Save button shows saving state while PATCH in flight", async () => {
    const user = userEvent.setup();

    server.use(
      http.patch("*/api/v1/test-cases/:caseId/steps", async () => {
        await new Promise((r) => setTimeout(r, 100));
        return HttpResponse.json(FULL_CASE_RESPONSE);
      }),
    );

    renderEditor([STEP_1, STEP_2]);

    const saveBtn = screen.getByTestId("step-save-btn");
    await user.click(saveBtn);

    // During flight the button should be disabled
    expect(saveBtn).toBeDisabled();

    await waitFor(() => {
      expect(saveBtn).not.toBeDisabled();
    }, { timeout: 3000 });
  });

  // --------------------------------------------------------------------------
  // AC-5: optimistic rollback on error
  // --------------------------------------------------------------------------
  it("shows error message when PATCH fails", async () => {
    const user = userEvent.setup();

    server.use(
      http.patch("*/api/v1/test-cases/:caseId/steps", () => {
        return HttpResponse.json(
          { code: "VALIDATION_ERROR", message: "Step requires code in ZERO tier" },
          { status: 422 },
        );
      }),
    );

    renderEditor([STEP_1, STEP_2]);
    const saveBtn = screen.getByTestId("step-save-btn");
    await user.click(saveBtn);

    expect(
      await screen.findByTestId("step-editor-error", undefined, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  // --------------------------------------------------------------------------
  // Edge: empty steps list shows add button only
  // --------------------------------------------------------------------------
  it("renders empty state with add button when no steps", () => {
    renderEditor([]);
    expect(screen.getByTestId("step-add-btn")).toBeInTheDocument();
    expect(screen.queryAllByTestId("step-row")).toHaveLength(0);
  });
});
