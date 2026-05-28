import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  RouterProvider,
  createMemoryHistory,
  createRouter,
} from "@tanstack/react-router";
import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "@/mocks/server";
import { routeTree } from "@/routeTree.gen";
import { useCapabilities, type Capabilities } from "@/stores/use-capabilities";

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

const CLOUD_CAPS: Capabilities = {
  tier: "CLOUD",
  llm: {
    provider: "anthropic",
    model: "claude-sonnet-4-5",
    base_url: null,
    is_test_provider: false,
  },
  embeddings: { enabled: true, backend: "openai", model: "text-embedding-3-small", dim: 1536 },
  features: {
    manual_tcm: true,
    deterministic_runner: true,
    deterministic_generator_openapi: true,
    deterministic_generator_recorder: true,
    deterministic_generator_crawler: true,
    ai_generation: true,
    ai_execution_agentic: true,
    ai_diagnose: true,
    ai_conversation: true,
    semantic_search: true,
    fts_search: true,
    auto_defect_filing_ai: true,
    auto_defect_filing_rule: true,
  },
  autonomy: { available: ["manual", "assist", "semi_auto", "auto"], default: "assist" },
  mcpProviders: [],
  version: "1.0.0",
};

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [path] }),
    context: { queryClient },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router, queryClient };
}

function setCaps(caps: Capabilities): void {
  act(() => {
    useCapabilities.setState({ capabilities: caps, loading: false, error: null });
  });
}

/** MSW overrides for `/capabilities` — the root layout boots a fetch on mount
 *  that would otherwise overwrite the store with the default ZERO fixture. */
function mockCaps(caps: Capabilities): void {
  server.use(
    http.get("*/capabilities", () => HttpResponse.json(caps)),
  );
}

describe("<_app> layout grid", () => {
  beforeEach(() => {
    vi.stubGlobal("location", {
      pathname: "/dashboard",
      assign: vi.fn(),
      origin: "http://localhost",
    });
    server.use(
      http.get("*/api/v1/auth/me", () =>
        HttpResponse.json({
          id: "u_demo",
          email: "demo@suitest.dev",
          name: "Demo",
          avatar_url: null,
          memberships: [],
        }),
      ),
    );
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    act(() => {
      useCapabilities.setState({ capabilities: null, loading: true, error: null });
    });
  });

  it("renders Sidebar + Topbar inside the authenticated shell", async () => {
    mockCaps(CLOUD_CAPS);
    setCaps(CLOUD_CAPS);
    renderAt("/dashboard");
    expect(await screen.findByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("topbar")).toBeInTheDocument();
  });

  it("collapses the AI rail in ZERO tier (no AiPanel rendered)", async () => {
    mockCaps(ZERO_CAPS);
    setCaps(ZERO_CAPS);
    const { router } = renderAt("/dashboard");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/dashboard");
    });
    const shell = await screen.findByTestId("app-shell");
    await waitFor(() => {
      expect(shell.className).toContain("grid-cols-[224px_1fr]");
      expect(shell.className).not.toContain("xl:grid-cols-[224px_1fr_380px]");
    });
    expect(screen.queryByTestId("ai-panel")).toBeNull();
  });

  it("renders the AI rail in CLOUD tier (xl: column applied)", async () => {
    mockCaps(CLOUD_CAPS);
    setCaps(CLOUD_CAPS);
    const { router } = renderAt("/dashboard");
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/dashboard");
    });
    const shell = await screen.findByTestId("app-shell");
    await waitFor(() => {
      expect(shell.className).toContain("xl:grid-cols-[224px_1fr_380px]");
    });
    expect(await screen.findByTestId("ai-panel")).toBeInTheDocument();
  });
});
