import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { QuickEditInputsDialog } from "./QuickEditInputsDialog";
import { api } from "@/lib/api-client";
import type { DraftStep } from "./StepEditor";

vi.mock("@/lib/api-client", () => ({
  api: {
    patch: vi.fn(),
    post: vi.fn(),
    get: vi.fn(),
  },
}));

vi.mock("@/hooks/use-test-cases", () => ({
  useTestCase: vi.fn(() => ({
    data: null,
    isLoading: false,
  })),
}));

vi.mock("@/hooks/use-variables", () => ({
  useResolvedVariables: vi.fn(() => ({
    data: [
      {
        key: "test_user_email",
        value: "tester@corp.local",
        isSecret: false,
        sourceScope: "workspace",
        description: "Standard QA user email",
      },
      {
        key: "api_key",
        value: "secret-key-123",
        isSecret: true,
        sourceScope: "suite",
        description: "Suite API token",
      },
    ],
    isLoading: false,
  })),
}));

describe("<QuickEditInputsDialog>", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
  });

  const renderComponent = (props: Partial<React.ComponentProps<typeof QuickEditInputsDialog>>) => {
    return render(
      <QueryClientProvider client={queryClient}>
        <QuickEditInputsDialog
          open={true}
          onOpenChange={vi.fn()}
          caseId="TC-101"
          caseName="User Registration Flow"
          {...props}
        />
      </QueryClientProvider>,
    );
  };

  const sampleSteps: DraftStep[] = [
    {
      id: "step-1",
      order: 1,
      action: "Navigate to registration",
      expected: "Page loaded",
      code: JSON.stringify({
        tool: "browser_navigate",
        arguments: { url: "https://app.test/register" },
      }),
      mcp_provider: "playwright-mcp",
      target_kind: "FE_WEB",
    },
    {
      id: "step-2",
      order: 2,
      action: "Type username into #username",
      expected: "Username typed",
      code: JSON.stringify({
        tool: "browser_type",
        arguments: { target: "#username", text: "budi" },
      }),
      mcp_provider: "playwright-mcp",
      target_kind: "FE_WEB",
    },
    {
      id: "step-3",
      order: 3,
      action: "Type password into input#password",
      expected: "Password typed",
      code: JSON.stringify({
        tool: "browser_type",
        arguments: { target: "input#password", text: "mypassword123" },
      }),
      mcp_provider: "playwright-mcp",
      target_kind: "FE_WEB",
    },
    {
      id: "step-4",
      order: 4,
      action: "Click submit button",
      expected: "Form submitted",
      code: JSON.stringify({
        tool: "browser_click",
        arguments: { target: "button#submit" },
      }),
      mcp_provider: "playwright-mcp",
      target_kind: "FE_WEB",
    },
  ];

  it("renders detected input steps and excludes non-input steps like click", () => {
    renderComponent({ steps: sampleSteps });

    expect(screen.getByTestId("quick-edit-inputs-dialog")).toBeInTheDocument();
    expect(screen.getByText(/Showing/i)).toHaveTextContent("Showing 3 of 3 input steps");

    // Inputs for steps 1, 2, and 3
    expect(screen.getByTestId("input-step-row-step-1")).toBeInTheDocument();
    expect(screen.getByTestId("input-step-row-step-2")).toBeInTheDocument();
    expect(screen.getByTestId("input-step-row-step-3")).toBeInTheDocument();

    // Step 4 (click) should not be detected
    expect(screen.queryByTestId("input-step-row-step-4")).not.toBeInTheDocument();
  });

  it("renders empty state when no input steps are detected", () => {
    const nonInputSteps: DraftStep[] = [
      {
        id: "step-click",
        order: 1,
        action: "Click on button",
        expected: "Clicked",
        code: JSON.stringify({ tool: "browser_click", arguments: { target: "button" } }),
        mcp_provider: "playwright-mcp",
        target_kind: "FE_WEB",
      },
    ];

    renderComponent({ steps: nonInputSteps });
    expect(screen.getByTestId("no-inputs-detected")).toBeInTheDocument();
  });

  it("filters input steps using search filter", async () => {
    const user = userEvent.setup();
    renderComponent({ steps: sampleSteps });

    const filterInput = screen.getByTestId("filter-inputs-field");
    expect(filterInput).toBeInTheDocument();

    await user.type(filterInput, "password");
    expect(screen.getByTestId("input-step-row-step-3")).toBeInTheDocument();
    expect(screen.queryByTestId("input-step-row-step-1")).not.toBeInTheDocument();
    expect(screen.queryByTestId("input-step-row-step-2")).not.toBeInTheDocument();

    await user.clear(filterInput);
    expect(screen.getByTestId("input-step-row-step-1")).toBeInTheDocument();
    expect(screen.getByTestId("input-step-row-step-2")).toBeInTheDocument();
    expect(screen.getByTestId("input-step-row-step-3")).toBeInTheDocument();
  });

  it("displays variable highlight and interactive VariableBadge when variable is present", async () => {
    const stepsWithVariable: DraftStep[] = [
      {
        id: "step-var",
        order: 1,
        action: "Type email into #email",
        expected: "Typed",
        code: JSON.stringify({
          tool: "browser_type",
          arguments: { target: "#email", text: "{{test_user_email}}" },
        }),
        mcp_provider: "playwright-mcp",
        target_kind: "FE_WEB",
      },
    ];

    renderComponent({ steps: stepsWithVariable });

    const input = screen.getByTestId("input-field-step-var");
    expect(input).toHaveValue("{{test_user_email}}");
    expect(input.className).toContain("border-purple-500");

    // VariableBadge should be rendered
    const badgeContainer = screen.getByTestId("bound-variable-badges-step-var");
    expect(badgeContainer).toBeInTheDocument();
    expect(badgeContainer).toHaveTextContent("{{test_user_email}}");
  });

  it("opens variable picker popover and allows inserting predefined variable", async () => {
    const user = userEvent.setup();
    renderComponent({ steps: sampleSteps });

    const bindBtn = screen.getByTestId("bind-var-btn-step-2");
    await user.click(bindBtn);

    const varItem = await screen.findByTestId("var-item-test_user_email");
    expect(varItem).toBeInTheDocument();
    expect(varItem).toHaveTextContent("tester@corp.local");

    await user.click(varItem);

    const usernameInput = screen.getByTestId("input-field-step-2");
    expect(usernameInput).toHaveValue("{{test_user_email}}");

    // Badge appears with resolved value preview
    expect(screen.getByTestId("bound-variable-badges-step-2")).toHaveTextContent("{{test_user_email}}");
  });

  it("updates modified counter and commits changes to backend", async () => {
    const user = userEvent.setup();
    const onStepsUpdated = vi.fn();
    const onOpenChange = vi.fn();

    vi.mocked(api.patch).mockResolvedValueOnce({ data: {} } as never);

    renderComponent({
      steps: sampleSteps,
      onStepsUpdated,
      onOpenChange,
    });

    const usernameInput = screen.getByTestId("input-field-step-2");
    await user.clear(usernameInput);
    await user.type(usernameInput, "siti");

    const applyBtn = screen.getByTestId("quick-edit-apply-btn");
    expect(applyBtn).toHaveTextContent("Apply Changes (1 modified)");

    await user.click(applyBtn);

    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith(
        "/test-cases/TC-101/steps",
        expect.objectContaining({
          steps: expect.arrayContaining([
            expect.objectContaining({
              order: 2,
              action: "Type username into #username",
              code: expect.stringContaining('"text": "siti"'),
            }),
          ]),
        }),
      );
      expect(onStepsUpdated).toHaveBeenCalled();
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });

  it("supports saving as new DDT row when checkbox is selected", async () => {
    const user = userEvent.setup();
    vi.mocked(api.patch).mockResolvedValue({ data: {} } as never);

    renderComponent({ steps: sampleSteps });

    const ddtCheckbox = screen.getByTestId("save-as-ddt-checkbox");
    await user.click(ddtCheckbox);

    const scenarioInput = screen.getByTestId("ddt-row-name-input");
    await user.type(scenarioInput, "Custom Scenario Alpha");

    const applyBtn = screen.getByTestId("quick-edit-apply-btn");
    await user.click(applyBtn);

    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith(
        "/test-cases/TC-101",
        expect.objectContaining({
          datasetRows: expect.arrayContaining([
            expect.objectContaining({
              name: "Custom Scenario Alpha",
              enabled: true,
            }),
          ]),
        }),
      );
    });
  });

  it("renders scenario switcher when multiple dataset rows exist and updates variable preview when switching rows", async () => {
    const user = userEvent.setup();
    const datasetRows = [
      {
        id: "row-1",
        name: "Default (Single Run)",
        enabled: true,
        values: { username: "user", password: "123" },
      },
      {
        id: "row-2",
        name: "Dataset Matrix #2",
        enabled: true,
        values: { username: "superadministrator", password: "123" },
      },
    ];

    renderComponent({
      steps: [
        {
          id: "step-2",
          order: 2,
          action: "Type username",
          expected: "Typed",
          code: JSON.stringify({
            tool: "browser_type",
            arguments: { target: "#username", text: "{{username}}" },
          }),
          mcp_provider: "playwright-mcp",
          target_kind: "FE_WEB",
        },
      ],
      datasetRows,
      datasetSchema: ["username", "password"],
    });

    // Scenario banner is present
    expect(screen.getByTestId("ddt-scenario-banner")).toBeInTheDocument();
    expect(screen.getByTestId("ddt-scenario-banner")).toHaveTextContent("Active Scenario: Default (Single Run)");

    // Switch row using select
    const scenarioSelect = screen.getByTestId("ddt-scenario-select");
    await user.selectOptions(scenarioSelect, "1");

    expect(screen.getByTestId("ddt-scenario-banner")).toHaveTextContent("Active Scenario: Dataset Matrix #2");
  });

  it("persists selected dataset row as default (is_default: true) when switching row and applying changes", async () => {
    const user = userEvent.setup();
    vi.mocked(api.patch).mockResolvedValue({ data: {} } as never);

    const datasetRows = [
      {
        id: "row-1",
        name: "Default (Single Run)",
        enabled: true,
        is_default: true,
        values: { username: "user", password: "123" },
      },
      {
        id: "row-2",
        name: "Dataset Matrix #2",
        enabled: true,
        is_default: false,
        values: { username: "superadministrator", password: "123" },
      },
    ];

    renderComponent({
      steps: [
        {
          id: "step-2",
          order: 2,
          action: "Type username",
          expected: "Typed",
          code: JSON.stringify({
            tool: "browser_type",
            arguments: { target: "#username", text: "{{username}}" },
          }),
          mcp_provider: "playwright-mcp",
          target_kind: "FE_WEB",
        },
      ],
      datasetRows,
      datasetSchema: ["username", "password"],
    });

    const scenarioSelect = screen.getByTestId("ddt-scenario-select");
    await user.selectOptions(scenarioSelect, "1");

    const applyBtn = screen.getByTestId("quick-edit-apply-btn");
    await user.click(applyBtn);

    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith(
        "/test-cases/TC-101",
        expect.objectContaining({
          datasetRows: [
            expect.objectContaining({
              id: "row-1",
              is_default: false,
            }),
            expect.objectContaining({
              id: "row-2",
              is_default: true,
            }),
          ],
        }),
      );
    });
  });
});
