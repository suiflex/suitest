import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CreateProjectDialog } from "@/components/cases/CreateProjectDialog";
import { server } from "@/mocks/server";
import { useActiveProject } from "@/stores/use-active-project";
import { useActiveWorkspace } from "@/stores/use-active-workspace";

function renderDialog(props?: Partial<React.ComponentProps<typeof CreateProjectDialog>>) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <CreateProjectDialog open onClose={onClose} {...props} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("CreateProjectDialog", () => {
  beforeEach(() => {
    useActiveWorkspace.setState({ workspaceId: "ws_demo" });
    useActiveProject.setState({ projectId: null });
  });
  afterEach(() => {
    useActiveWorkspace.setState({ workspaceId: null });
    useActiveProject.setState({ projectId: null });
  });

  it("creates a project, makes it the active project, and closes", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("*/api/v1/projects", async ({ request }) => {
        const body = (await request.json()) as { name: string };
        return HttpResponse.json(
          {
            id: "prj_new",
            workspace_id: "ws_demo",
            slug: "checkout",
            name: body.name,
            description: null,
            gating_suite_id: null,
            default_mcp_routing: {},
            created_at: "2026-06-28T00:00:00Z",
            updated_at: "2026-06-28T00:00:00Z",
          },
          { status: 201 },
        );
      }),
    );

    const { onClose } = renderDialog();
    await user.type(screen.getByTestId("create-project-name"), "Checkout");
    await user.click(screen.getByTestId("create-project-submit"));

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
    expect(useActiveProject.getState().projectId).toBe("prj_new");
  });

  it("surfaces an error when the name collides (409)", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("*/api/v1/projects", () =>
        HttpResponse.json(
          { error: { code: "DUPLICATE_PROJECT_SLUG", message: "taken", details: {} } },
          { status: 409 },
        ),
      ),
    );

    renderDialog();
    await user.type(screen.getByTestId("create-project-name"), "Dupe");
    await user.click(screen.getByTestId("create-project-submit"));

    expect(await screen.findByTestId("create-project-error")).toBeInTheDocument();
    expect(useActiveProject.getState().projectId).toBeNull();
  });

  it("disables submit until a name is entered", () => {
    renderDialog();
    expect(screen.getByTestId("create-project-submit")).toBeDisabled();
  });
});
