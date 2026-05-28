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
import userEvent from "@testing-library/user-event";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Topbar } from "@/components/shell/Topbar";
import {
  useCapabilities,
  type Capabilities,
} from "@/stores/use-capabilities";

const ZERO_CAPS: Capabilities = {
  tier: "ZERO",
  llm: { provider: "none", model: null, base_url: null, is_test_provider: false },
  embeddings: { enabled: false, backend: "none", model: null, dim: null },
  features: {
    manual_tcm: true,
    deterministic_runner: true,
    deterministic_generator_openapi: true,
    deterministic_generator_recorder: true,
    deterministic_generator_crawler: true,
    ai_generation: false,
    ai_execution_agentic: false,
    ai_diagnose: false,
    ai_conversation: false,
    semantic_search: false,
    fts_search: true,
    auto_defect_filing_ai: false,
    auto_defect_filing_rule: true,
  },
  autonomy: { available: ["manual"], default: "manual" },
  mcpProviders: [],
  version: "1.0.0",
};

async function renderTopbar(initialPath: string): Promise<ReturnType<typeof render>> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  const rootRoute = createRootRoute({
    component: () => (
      <div>
        <Topbar />
        <Outlet />
      </div>
    ),
  });

  const targets = [
    { path: "/dashboard", title: "Dashboard" },
    { path: "/cases", title: "Test Cases" },
    { path: "/runs", title: "Test Runs" },
    { path: "/defects", title: "Defects" },
    { path: "/analytics", title: "Analytics" },
    { path: "/trace", title: "Traceability" },
    { path: "/integrations", title: "Integrations" },
    { path: "/docs", title: "Documents" },
    { path: "/inbox", title: "Inbox" },
  ];
  const children = targets.map((t) =>
    createRoute({
      getParentRoute: () => rootRoute,
      path: t.path,
      component: () => <div data-testid={`page-${t.path}`}>{t.title}</div>,
      staticData: { title: t.title },
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
  await waitFor(() => {
    expect(result.container.querySelector("[data-testid='topbar']")).not.toBeNull();
  });
  return result;
}

describe("<Topbar>", () => {
  beforeEach(() => {
    act(() => {
      useCapabilities.setState({ capabilities: ZERO_CAPS, loading: false, error: null });
    });
  });
  afterEach(() => {
    act(() => {
      useCapabilities.setState({ capabilities: null, loading: true, error: null });
    });
  });

  it("renders the tier badge slot from useCapabilities", async () => {
    await renderTopbar("/dashboard");
    expect(screen.getByTestId("tier-badge")).toHaveTextContent("ZERO");
  });

  it("reflects current route title in breadcrumbs", async () => {
    await renderTopbar("/runs");
    const crumbs = await screen.findByTestId("topbar-breadcrumbs");
    expect(crumbs).toHaveTextContent("Test Runs");
  });

  it("renders breadcrumbs for a different route after mount", async () => {
    await renderTopbar("/analytics");
    const crumbs = screen.getByTestId("topbar-breadcrumbs");
    expect(crumbs).toHaveTextContent("Analytics");
  });

  it("disables the + New button with a tooltip reason", async () => {
    await renderTopbar("/dashboard");
    const newBtn = screen.getByTestId("topbar-new-button");
    expect(newBtn).toBeDisabled();
  });

  it("opens the command palette on ⌘K keydown", async () => {
    await renderTopbar("/dashboard");
    // shadcn CommandDialog mounts dialog content only when open.
    expect(screen.queryByPlaceholderText(/Type a command/i)).toBeNull();

    await act(async () => {
      window.dispatchEvent(
        new KeyboardEvent("keydown", { key: "k", metaKey: true }),
      );
    });

    expect(await screen.findByPlaceholderText(/Type a command/i)).toBeInTheDocument();
  });

  it("opens the command palette on Ctrl+K keydown", async () => {
    await renderTopbar("/dashboard");
    await act(async () => {
      window.dispatchEvent(
        new KeyboardEvent("keydown", { key: "k", ctrlKey: true }),
      );
    });
    expect(await screen.findByPlaceholderText(/Type a command/i)).toBeInTheDocument();
  });

  it("opens the command palette when the search trigger is clicked", async () => {
    await renderTopbar("/dashboard");
    const trigger = screen.getByTestId("topbar-search-trigger");
    await userEvent.click(trigger);
    expect(await screen.findByPlaceholderText(/Type a command/i)).toBeInTheDocument();
  });

  it("lists all 9 navigation commands inside the palette", async () => {
    await renderTopbar("/dashboard");
    await userEvent.click(screen.getByTestId("topbar-search-trigger"));
    await screen.findByPlaceholderText(/Type a command/i);
    const list = screen.getByTestId("topbar-command-list");
    const labels = [
      "Go to Dashboard",
      "Go to Test Cases",
      "Go to Test Runs",
      "Go to Defects",
      "Go to Analytics",
      "Go to Traceability",
      "Go to Integrations",
      "Go to Docs",
      "Go to Inbox",
    ];
    for (const label of labels) {
      expect(list).toHaveTextContent(label);
    }
  });
});
