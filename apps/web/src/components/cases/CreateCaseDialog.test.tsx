import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CreateCaseDialog } from "@/components/cases/CreateCaseDialog";
import type { components } from "@/lib/api-types";
import { server } from "@/mocks/server";
import { useActiveWorkspace } from "@/stores/use-active-workspace";

type Suite = components["schemas"]["SuitePublic"];

const SUITES: Suite[] = [
  {
    id: "ste_login",
    project_id: "prj_demo",
    name: "Login flow",
    description: null,
    order: 0,
    case_count: 0,
    created_at: "2026-06-01T08:00:00Z",
    updated_at: "2026-06-01T08:00:00Z",
  },
];

function renderDialog(props?: Partial<React.ComponentProps<typeof CreateCaseDialog>>) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onClose = vi.fn();
  const onCreated = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <CreateCaseDialog open onClose={onClose} onCreated={onCreated} suites={SUITES} {...props} />
    </QueryClientProvider>,
  );
  return { onClose, onCreated };
}

describe("CreateCaseDialog", () => {
  beforeEach(() => {
    useActiveWorkspace.setState({ workspaceId: "ws_demo" });
  });
  afterEach(() => {
    useActiveWorkspace.setState({ workspaceId: null });
  });

  it("creates a manual case under the active suite, closes, and reports the public id", async () => {
    const user = userEvent.setup();
    let captured: { suiteId?: string; name?: string } = {};
    server.use(
      http.post("*/api/v1/test-cases", async ({ request }) => {
        captured = (await request.json()) as { suiteId?: string; name?: string };
        return HttpResponse.json(
          {
            id: "case_new",
            public_id: "TC-101",
            suite_id: "ste_login",
            name: captured.name,
            description: null,
            preconditions: null,
            priority: "P2",
            status: "ACTIVE",
            source: "MANUAL",
            owner_id: null,
            tags: [],
            steps: [],
            created_at: "2026-06-28T00:00:00Z",
            updated_at: "2026-06-28T00:00:00Z",
          },
          { status: 201 },
        );
      }),
    );

    const { onClose, onCreated } = renderDialog();
    await user.type(screen.getByTestId("create-case-name"), "Valid login");
    await user.click(screen.getByTestId("create-case-submit"));

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
    expect(captured.suiteId).toBe("ste_login");
    expect(captured.name).toBe("Valid login");
    expect(onCreated).toHaveBeenCalledWith("TC-101");
  });

  it("surfaces an error when the backend rejects the create", async () => {
    const user = userEvent.setup();
    server.use(http.post("*/api/v1/test-cases", () => new HttpResponse(null, { status: 400 })));

    renderDialog();
    await user.type(screen.getByTestId("create-case-name"), "Bad");
    await user.click(screen.getByTestId("create-case-submit"));

    expect(await screen.findByTestId("create-case-error")).toBeInTheDocument();
  });

  it("disables submit until a name is entered", () => {
    renderDialog();
    expect(screen.getByTestId("create-case-submit")).toBeDisabled();
  });

  it("enables submit for a single suite that arrives after the dialog mounted", async () => {
    // Regression: the dialog is rendered persistently, so it mounts while the
    // suites list is still empty; the effective suite must derive from current
    // props (not a frozen useState initial value) or submit stays disabled.
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <CreateCaseDialog open onClose={vi.fn()} suites={[]} />
      </QueryClientProvider>,
    );
    rerender(
      <QueryClientProvider client={queryClient}>
        <CreateCaseDialog open onClose={vi.fn()} suites={SUITES} />
      </QueryClientProvider>,
    );
    await user.type(screen.getByTestId("create-case-name"), "Valid login");
    expect(screen.getByTestId("create-case-submit")).toBeEnabled();
  });
});
