import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { BatchEditDataDialog } from "./BatchEditDataDialog";

const mockMutate = vi.fn();
vi.mock("@/hooks/use-test-cases", () => ({
  useBulkUpdate: () => ({
    mutate: mockMutate,
    isPending: false,
  }),
}));

const mockCases = [
  {
    id: "case-1",
    public_id: "TC-001",
    name: "Valid User Login",
    title: "Valid User Login",
    suite_id: "s-1",
    created_at: "2026-10-16T00:00:00Z",
    updated_at: "2026-10-16T00:00:00Z",
    effective_testing_approach: "BLACK_BOX" as const,
    priority: "P1" as const,
    source: "MANUAL" as const,
    status: "ACTIVE" as const,
  },
  {
    id: "case-2",
    public_id: "TC-002",
    name: "Admin Dashboard Check",
    title: "Admin Dashboard Check",
    suite_id: "s-1",
    created_at: "2026-10-16T00:00:00Z",
    updated_at: "2026-10-16T00:00:00Z",
    effective_testing_approach: "BLACK_BOX" as const,
    priority: "P2" as const,
    source: "MANUAL" as const,
    status: "ACTIVE" as const,
  },
];

describe("<BatchEditDataDialog>", () => {
  it("renders with Find & Replace mode by default and submits payload", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    const onSuccess = vi.fn();

    render(
      <BatchEditDataDialog
        open={true}
        onOpenChange={onOpenChange}
        selectedIds={["case-1", "case-2"]}
        cases={mockCases}
        onSuccess={onSuccess}
      />,
    );

    expect(screen.getByTestId("batch-edit-data-dialog")).toBeInTheDocument();
    expect(screen.getByText(/Batch Edit Test Data/i)).toBeInTheDocument();
    expect(screen.getByText("Valid User Login")).toBeInTheDocument();
    expect(screen.getByText("Admin Dashboard Check")).toBeInTheDocument();

    const findInput = screen.getByTestId("find-text-input");
    const replaceInput = screen.getByTestId("replace-with-input");
    const applyBtn = screen.getByTestId("apply-batch-btn");

    expect(applyBtn).toBeDisabled();

    await user.type(findInput, "https://old-domain.dev");
    fireEvent.change(replaceInput, { target: { value: "{{BASE_URL}}" } });

    expect(applyBtn).not.toBeDisabled();

    mockMutate.mockImplementation((_body, { onSuccess: mutSuccess }) => {
      mutSuccess({ updated: 2 });
    });

    await user.click(applyBtn);

    expect(mockMutate).toHaveBeenCalledWith(
      {
        action: "batch_replace_data",
        ids: ["case-1", "case-2"],
        payload: {
          findText: "https://old-domain.dev",
          replaceWith: "{{BASE_URL}}",
          targetField: "all",
        },
      },
      expect.any(Object),
    );
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onSuccess).toHaveBeenCalled();
  });

  it("switches to Bind Shared Variable mode and submits variable payload", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    const onSuccess = vi.fn();

    render(
      <BatchEditDataDialog
        open={true}
        onOpenChange={onOpenChange}
        selectedIds={["case-1"]}
        cases={mockCases}
        onSuccess={onSuccess}
      />,
    );

    // Switch to bind mode
    await user.click(screen.getByTestId("tab-bind"));

    const varInput = screen.getByTestId("variable-key-input");
    const applyBtn = screen.getByTestId("apply-batch-btn");

    expect(applyBtn).toBeDisabled();

    await user.type(varInput, "ADMIN_PASSWORD");

    expect(applyBtn).not.toBeDisabled();

    mockMutate.mockImplementation((_body, { onSuccess: mutSuccess }) => {
      mutSuccess({ updated: 1 });
    });

    await user.click(applyBtn);

    expect(mockMutate).toHaveBeenCalledWith(
      {
        action: "batch_bind_variable",
        ids: ["case-1"],
        payload: {
          variableKey: "ADMIN_PASSWORD",
          targetField: "password",
        },
      },
      expect.any(Object),
    );
  });
});
