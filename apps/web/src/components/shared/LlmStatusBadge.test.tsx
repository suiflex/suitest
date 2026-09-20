import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";

import { LlmStatusBadge } from "@/components/shared/LlmStatusBadge";
import { useCapabilitySync } from "@/hooks/use-capability-sync";
import { setWsTransport } from "@/lib/ws-client";
import { server } from "@/mocks/server";
import { CLOUD_CAPS, setCaps, ZERO_CAPS } from "@/test/capabilities";
import { MockWs } from "@/test/mock-ws";
import { useActiveWorkspace } from "@/stores/use-active-workspace";
import { useCapabilities } from "@/stores/use-capabilities";

function Harness(): React.ReactElement {
  useCapabilitySync();
  return <LlmStatusBadge />;
}

function renderHarness(): void {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <Harness />
    </QueryClientProvider>,
  );
}

/** Route the capabilities endpoint to the given snapshot for this test. */
function mockCapabilitiesEndpoint(caps: Parameters<typeof HttpResponse.json>[1] | object): void {
  server.use(http.get("*/capabilities", () => HttpResponse.json(caps)));
}

describe("header LLM status immediacy", () => {
  afterEach(() => {
    useActiveWorkspace.setState({ workspaceId: null });
    useCapabilities.setState({ capabilities: null, loading: true, error: null });
  });

  it("flips the badge to ready the moment capability.changed arrives", async () => {
    setCaps(ZERO_CAPS);
    useActiveWorkspace.setState({ workspaceId: "ws_1" });
    const ws = new MockWs();
    const restore = setWsTransport(ws);
    mockCapabilitiesEndpoint(CLOUD_CAPS);
    renderHarness();

    const badge = screen.getByTestId("llm-status-badge");
    expect(badge).toHaveAttribute("data-llm-status", "not_configured");

    act(() => {
      ws.emit({ topic: "workspace:ws_1", event: "capability.changed", data: { llmStatus: "ready" } });
    });
    // The handler kicks an async refetch; let it settle before asserting.
    await waitFor(() => {
      expect(screen.getByTestId("llm-status-badge")).toHaveAttribute("data-llm-status", "ready");
    });
    restore();
  });

  it("flips the badge back to disconnected on a disconnect event", async () => {
    setCaps(CLOUD_CAPS);
    useActiveWorkspace.setState({ workspaceId: "ws_1" });
    const ws = new MockWs();
    const restore = setWsTransport(ws);
    mockCapabilitiesEndpoint(ZERO_CAPS);
    renderHarness();

    expect(screen.getByTestId("llm-status-badge")).toHaveAttribute("data-llm-status", "ready");

    act(() => {
      ws.emit({
        topic: "workspace:ws_1",
        event: "capability.changed",
        data: { llmStatus: "not_configured" },
      });
    });

    await waitFor(() => {
      expect(screen.getByTestId("llm-status-badge")).toHaveAttribute(
        "data-llm-status",
        "not_configured",
      );
    });
    restore();
  });

  it("never reports connected from the refetch when the endpoint still says disconnected", () => {
    // Optimistic-connected regression: the store must only ever mirror the
    // backend snapshot — an event with no readiness change cannot manufacture
    // a connected state.
    setCaps(ZERO_CAPS);
    useActiveWorkspace.setState({ workspaceId: "ws_1" });
    const ws = new MockWs();
    const restore = setWsTransport(ws);
    mockCapabilitiesEndpoint(ZERO_CAPS);
    renderHarness();

    act(() => {
      ws.emit({
        topic: "workspace:ws_1",
        event: "capability.changed",
        data: { llmStatus: "validation_required" },
      });
    });

    expect(
      useCapabilities.getState().capabilities?.llm.status,
    ).toBe("not_configured");
    restore();
  });
});
