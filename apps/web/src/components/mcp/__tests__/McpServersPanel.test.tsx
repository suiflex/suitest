import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { McpServersPanel } from "@/components/mcp/McpServersPanel";
import { server } from "@/mocks/server";
import { installMockWs, type MockWs } from "@/test/mock-ws";
import { useActiveWorkspace } from "@/stores/use-active-workspace";

const WS_ID = "ws_test";

function renderPanel(): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <McpServersPanel />
    </QueryClientProvider>,
  );
}

interface TestRefs {
  ws: MockWs;
  restore: () => void;
  providersCallCount: { value: number };
}

function withFreshMocks(initial: {
  id: string;
  name: string;
  kind: string;
  transport?: string;
  healthStatus: "ok" | "degraded" | "down" | "unknown";
  tools?: { name: string }[];
}[]): TestRefs {
  const providersCallCount = { value: 0 };
  // Mutable so the "health changes" test can flip a provider's status between
  // refetches and assert the pill updates in the DOM.
  const state = { items: initial };

  server.use(
    http.get("*/api/v1/mcp/providers", () => {
      providersCallCount.value += 1;
      return HttpResponse.json({
        items: state.items.map((p) => ({
          id: p.id,
          name: p.name,
          kind: p.kind,
          transport: p.transport ?? "stdio",
          endpoint: "stdio://demo",
          healthStatus: p.healthStatus,
          lastHealthAt: null,
          isBundled: false,
          tools: p.tools,
        })),
      });
    }),
    http.get("*/api/v1/mcp/providers/:id", ({ params }) =>
      HttpResponse.json({
        id: String(params["id"]),
        name: "Playwright MCP",
        kind: "FE_WEB",
        transport: "stdio",
        endpoint: "stdio://playwright",
        healthStatus: "ok",
        isBundled: true,
        tools: [
          {
            name: "browser.navigate",
            description: "Navigate the browser to a URL",
            argSchema: { url: "string" },
          },
          { name: "browser.click", description: "Click an element", argSchema: { selector: "string" } },
        ],
      }),
    ),
  );

  const { ws, restore } = installMockWs();
  return { ws, restore, providersCallCount };
}

describe("<McpServersPanel />", () => {
  let refs: TestRefs;

  beforeEach(() => {
    useActiveWorkspace.setState({ workspaceId: WS_ID });
    refs = withFreshMocks([
      {
        id: "playwright-mcp",
        name: "playwright-mcp",
        kind: "browser",
        healthStatus: "ok",
        tools: [{ name: "browser.navigate" }],
      },
    ]);
    vi.stubGlobal("location", { pathname: "/integrations", assign: vi.fn(), origin: "http://localhost" });
  });

  afterEach(() => {
    refs.restore();
    useActiveWorkspace.setState({ workspaceId: null });
    vi.unstubAllGlobals();
  });

  it("renders providers from the API", async () => {
    renderPanel();
    expect(await screen.findByText("playwright-mcp")).toBeInTheDocument();
    expect(screen.getByText("1 tool")).toBeInTheDocument();
    const pill = screen.getByTestId("health-pill");
    expect(pill).toHaveAttribute("data-status", "ok");
  });

  it("updates the health pill on `mcp.provider.health` WS event", async () => {
    // The first GET responds with `ok`; once the WS event fires, the refetch
    // will see the mutated `state.items` and reflect "degraded".
    const localCount = { value: 0 };
    server.use(
      http.get("*/api/v1/mcp/providers", () => {
        localCount.value += 1;
        return HttpResponse.json({
          items: [
            {
              id: "playwright-mcp",
              name: "playwright-mcp",
              kind: "browser",
              transport: "stdio",
              endpoint: "stdio://demo",
              healthStatus: localCount.value === 1 ? "ok" : "degraded",
              lastHealthAt: null,
              isBundled: false,
              tools: [{ name: "browser.navigate" }],
            },
          ],
        });
      }),
    );

    renderPanel();
    await screen.findByText("playwright-mcp");
    expect(screen.getByTestId("health-pill")).toHaveAttribute("data-status", "ok");

    await act(async () => {
      refs.ws.emit({
        topic: `workspace:${WS_ID}`,
        event: "mcp.provider.health",
        data: { providerId: "playwright-mcp", status: "degraded" },
      });
    });

    await waitFor(() => {
      expect(screen.getByTestId("health-pill")).toHaveAttribute("data-status", "degraded");
    });
  });

  it("opens the modal with the tool list when a row is clicked", async () => {
    const user = userEvent.setup();
    renderPanel();
    const row = await screen.findByTestId("mcp-server-row");
    await user.click(row);

    expect(await screen.findByTestId("provider-modal")).toBeInTheDocument();
    const tools = await screen.findAllByTestId("provider-tool");
    expect(tools.length).toBe(2);
    expect(screen.getByText("browser.navigate")).toBeInTheDocument();
    expect(screen.getByText("browser.click")).toBeInTheDocument();
  });
});
