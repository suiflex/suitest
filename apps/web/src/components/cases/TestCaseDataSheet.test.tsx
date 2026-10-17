import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { TestCaseDataSheet } from "./TestCaseDataSheet";

vi.mock("@/hooks/use-test-cases", () => ({
  useUpdateTestCase: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));

const mockCase = {
  id: "c1",
  public_id: "TC-101",
  name: "Login test",
  dataset_schema: ["base_url", "user_role"],
  dataset_rows: [
    {
      id: "r1",
      name: "Admin Role",
      enabled: true,
      values: { base_url: "https://admin.test", user_role: "admin" },
    },
  ],
} as unknown as Parameters<typeof TestCaseDataSheet>[0]["testCase"];

function renderWithClient(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

describe("<TestCaseDataSheet>", () => {
  it("renders data matrix columns and rows", () => {
    renderWithClient(
      <TestCaseDataSheet
        testCase={mockCase}
        steps={[{ action: "Type {{password}} into #pass" }]}
      />
    );

    expect(screen.getByText("In-Case Test Data Matrix (DDT)")).toBeInTheDocument();
    expect(screen.getByText("{{base_url}}")).toBeInTheDocument();
    expect(screen.getByText("{{user_role}}")).toBeInTheDocument();
    // Auto-detected from step
    expect(screen.getByText("{{password}}")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Admin Role")).toBeInTheDocument();
    expect(screen.getByDisplayValue("https://admin.test")).toBeInTheDocument();
  });

  it("adds a new dataset matrix row on button click", async () => {
    const user = userEvent.setup();
    renderWithClient(
      <TestCaseDataSheet
        testCase={mockCase}
        steps={[]}
      />
    );

    await user.click(screen.getByRole("button", { name: /add row/i }));
    expect(screen.getByDisplayValue("Dataset Matrix #2")).toBeInTheDocument();
  });
});
