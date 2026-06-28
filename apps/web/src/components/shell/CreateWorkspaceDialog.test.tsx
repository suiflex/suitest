import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CreateWorkspaceDialog } from "@/components/shell/CreateWorkspaceDialog";
import { server } from "@/mocks/server";
import { useActiveProject } from "@/stores/use-active-project";
import { useActiveWorkspace } from "@/stores/use-active-workspace";

function renderDialog(props?: Partial<React.ComponentProps<typeof CreateWorkspaceDialog>>) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={queryClient}>
      <CreateWorkspaceDialog open onClose={onClose} {...props} />
    </QueryClientProvider>,
  );
  return { onClose };
}

describe("CreateWorkspaceDialog", () => {
  beforeEach(() => {
    useActiveWorkspace.setState({ workspaceId: "ws_old" });
    useActiveProject.setState({ projectId: "prj_old" });
  });
  afterEach(() => {
    useActiveWorkspace.setState({ workspaceId: null });
    useActiveProject.setState({ projectId: null });
  });

  it("creates a workspace, switches to it, clears the active project, and closes", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("*/api/v1/workspaces", async ({ request }) => {
        const body = (await request.json()) as { name: string };
        return HttpResponse.json(
          {
            id: "ws_new",
            slug: "swag-labs-qa",
            name: body.name,
            region: "ap-southeast-1",
            created_at: "2026-06-28T00:00:00Z",
            updated_at: "2026-06-28T00:00:00Z",
          },
          { status: 201 },
        );
      }),
    );

    const { onClose } = renderDialog();
    await user.type(screen.getByTestId("create-workspace-name"), "Swag Labs QA");
    await user.click(screen.getByTestId("create-workspace-submit"));

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
    expect(useActiveWorkspace.getState().workspaceId).toBe("ws_new");
    expect(useActiveProject.getState().projectId).toBeNull();
  });

  it("surfaces an error when the slug is taken (409)", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("*/api/v1/workspaces", () =>
        HttpResponse.json(
          { error: { code: "DUPLICATE_WORKSPACE_SLUG", message: "taken", details: {} } },
          { status: 409 },
        ),
      ),
    );

    renderDialog();
    await user.type(screen.getByTestId("create-workspace-name"), "Dupe");
    await user.click(screen.getByTestId("create-workspace-submit"));

    expect(await screen.findByTestId("create-workspace-error")).toBeInTheDocument();
    expect(useActiveWorkspace.getState().workspaceId).toBe("ws_old");
  });

  it("disables submit until a name is entered", () => {
    renderDialog();
    expect(screen.getByTestId("create-workspace-submit")).toBeDisabled();
  });
});
