import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { VariablesTable } from "./VariablesTable";

// Mock hooks
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    canWriteTests: true,
    isAdmin: false,
    isOwner: false,
  }),
}));

vi.mock("@/hooks/use-variables", () => ({
  useWorkspaceVariables: () => ({
    data: [
      {
        id: "v1",
        workspaceId: "ws1",
        key: "base_url",
        value: "https://example.com",
        description: "API URL",
        isSecret: false,
        hasValue: true,
        createdAt: "2026-10-16T00:00:00Z",
        updatedAt: "2026-10-16T00:00:00Z",
      },
      {
        id: "v2",
        workspaceId: "ws1",
        key: "db_password",
        value: null,
        description: "DB secret",
        isSecret: true,
        hasValue: true,
        createdAt: "2026-10-16T00:00:00Z",
        updatedAt: "2026-10-16T00:00:00Z",
      },
    ],
    isLoading: false,
  }),
  useCreateWorkspaceVariable: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateWorkspaceVariable: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteWorkspaceVariable: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSuiteVariables: () => ({ data: [], isLoading: false }),
  useCreateSuiteVariable: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useUpdateSuiteVariable: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useDeleteSuiteVariable: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("<VariablesTable>", () => {
  it("renders variables and secret tags", () => {
    renderWithClient(<VariablesTable scope="workspace" workspaceId="ws1" />);

    expect(screen.getByText("Workspace Shared Variables & Secrets")).toBeInTheDocument();
    expect(screen.getByText("{{base_url}}")).toBeInTheDocument();
    expect(screen.getByText("https://example.com")).toBeInTheDocument();
    expect(screen.getByText("{{db_password}}")).toBeInTheDocument();
    expect(screen.getByText("AES-GCM Encrypted")).toBeInTheDocument();
    expect(screen.getByText("Add Variable")).toBeInTheDocument();
  });

  it("opens add variable modal on click", async () => {
    const user = userEvent.setup();
    renderWithClient(<VariablesTable scope="workspace" workspaceId="ws1" />);

    await user.click(screen.getByRole("button", { name: /add variable/i }));
    expect(screen.getByText("Reference this variable in step actions and targets as {{key}}.")).toBeInTheDocument();
  });
});
