import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Sidebar, type SidebarProps } from "@/components/shell/Sidebar";

/**
 * Mount the Sidebar inside a minimal in-memory TanStack Router so `<Link>`
 * children resolve. Real route tree is not used — we only need a few
 * matching paths so `activeProps` can fire when the test asks for one.
 */
async function renderSidebar(
  initialPath: string,
  props: SidebarProps = {},
): Promise<ReturnType<typeof render>> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  const rootRoute = createRootRoute({
    component: () => (
      <div className="flex">
        <Sidebar {...props} />
        <Outlet />
      </div>
    ),
  });

  const pages = [
    "/dashboard",
    "/inbox",
    "/cases",
    "/runs",
    "/defects",
    "/analytics",
    "/trace",
    "/integrations",
    "/docs",
    "/settings",
  ];
  const children = pages.map((p) =>
    createRoute({
      getParentRoute: () => rootRoute,
      path: p,
      component: () => <div data-testid={`page-${p}`}>{p}</div>,
    }),
  );
  const routeTree = rootRoute.addChildren(children);

  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [initialPath] }),
  });

  const result = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );

  // Wait for the Sidebar (and the rest of the tree) to actually render.
  await waitFor(() => {
    expect(result.container.querySelector("[data-testid='sidebar']")).not.toBeNull();
  });

  return result;
}

describe("<Sidebar>", () => {
  it("renders all primary nav items", async () => {
    await renderSidebar("/dashboard");
    const expected = [
      "Dashboard",
      "Inbox",
      "Test Cases",
      "Test Runs",
      "Defects",
      "Analytics",
      "Traceability",
      "Integrations",
      "Docs",
      "Settings",
    ];
    for (const label of expected) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("renders the workspace picker trigger and brand wordmark", async () => {
    await renderSidebar("/dashboard", { workspaceName: "Acme QA" });
    expect(screen.getByTestId("workspace-picker")).toHaveTextContent("Acme QA");
    // Brand wordmark renders as a single "suitest" word split across spans.
    expect(screen.getByText("test", { selector: "span" })).toBeInTheDocument();
  });

  it("highlights the active route via Link activeProps", async () => {
    await renderSidebar("/runs");
    // TanStack Router applies `data-status="active"` automatically on the
    // anchor when the route matches.
    const runs = screen.getByTestId("nav-test-runs");
    await waitFor(() => {
      expect(runs.getAttribute("data-status")).toBe("active");
    });
    const dashboard = screen.getByTestId("nav-dashboard");
    expect(dashboard.getAttribute("data-status")).not.toBe("active");
  });

  it("shows an inbox badge when count > 0", async () => {
    await renderSidebar("/dashboard", { inboxCount: 3 });
    const badge = screen.getByTestId("nav-inbox-badge");
    expect(badge).toHaveTextContent("3");
  });

  it("omits the inbox badge when count is 0", async () => {
    await renderSidebar("/dashboard", { inboxCount: 0 });
    expect(screen.queryByTestId("nav-inbox-badge")).toBeNull();
  });

  it("shows a live dot next to Test Runs when activeRunsCount > 0", async () => {
    await renderSidebar("/dashboard", { activeRunsCount: 2 });
    expect(screen.getByTestId("nav-test-runs-live-dot")).toBeInTheDocument();
  });

  it("hides the live dot when activeRunsCount is 0", async () => {
    await renderSidebar("/dashboard", { activeRunsCount: 0 });
    expect(screen.queryByTestId("nav-test-runs-live-dot")).toBeNull();
  });

  it("renders the notification bell with a red dot when unreadCount > 0", async () => {
    await renderSidebar("/dashboard", { unreadCount: 5 });
    expect(screen.getByTestId("sidebar-bell")).toBeInTheDocument();
    expect(screen.getByTestId("sidebar-bell-unread")).toBeInTheDocument();
  });

  it("omits the bell red dot when unreadCount is 0", async () => {
    await renderSidebar("/dashboard", { unreadCount: 0 });
    expect(screen.queryByTestId("sidebar-bell-unread")).toBeNull();
  });

  it("renders Settings as disabled (M1b placeholder)", async () => {
    await renderSidebar("/dashboard");
    const settings = screen.getByTestId("nav-settings");
    expect(settings.getAttribute("aria-disabled")).toBe("true");
  });
});
