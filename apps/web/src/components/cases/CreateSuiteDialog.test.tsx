import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CreateSuiteDialog } from "@/components/cases/CreateSuiteDialog";
import { server } from "@/mocks/server";
import { useActiveProject } from "@/stores/use-active-project";
import { useActiveWorkspace } from "@/stores/use-active-workspace";

function renderDialog(props?: Partial<React.ComponentProps<typeof CreateSuiteDialog>>) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <CreateSuiteDialog open onClose={onClose} {...props} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("CreateSuiteDialog", () => {
  beforeEach(() => {
    useActiveWorkspace.setState({ workspaceId: "ws_demo" });
    useActiveProject.setState({ projectId: "prj_demo" });
  });
  afterEach(() => {
    useActiveWorkspace.setState({ workspaceId: null });
    useActiveProject.setState({ projectId: null });
  });

  it("creates a suite under the active project and closes", async () => {
    const user = userEvent.setup();
    let captured: { projectId?: string; name?: string } = {};
    server.use(
      http.post("*/api/v1/suites", async ({ request }) => {
        captured = (await request.json()) as { projectId?: string; name?: string };
        return HttpResponse.json(
          {
            id: "ste_new",
            project_id: "prj_demo",
            name: captured.name,
            description: null,
            order: 0,
            case_count: 0,
            created_at: "2026-06-28T00:00:00Z",
            updated_at: "2026-06-28T00:00:00Z",
          },
          { status: 201 },
        );
      }),
    );

    const { onClose } = renderDialog();
    await user.type(screen.getByTestId("create-suite-name"), "Login flow");
    await user.click(screen.getByTestId("create-suite-submit"));

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
    expect(captured.projectId).toBe("prj_demo");
    expect(captured.name).toBe("Login flow");
  });

  it("surfaces an error when the backend rejects the create", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("*/api/v1/suites", () => new HttpResponse(null, { status: 400 })),
    );

    renderDialog();
    await user.type(screen.getByTestId("create-suite-name"), "Bad");
    await user.click(screen.getByTestId("create-suite-submit"));

    expect(await screen.findByTestId("create-suite-error")).toBeInTheDocument();
  });

  it("disables submit until a name is entered", () => {
    renderDialog();
    expect(screen.getByTestId("create-suite-submit")).toBeDisabled();
  });
});
