import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { LlmSettingsPanel } from "@/components/settings/LlmSettingsPanel";
import { server } from "@/mocks/server";

function renderPanel(canWrite = true) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <LlmSettingsPanel workspaceId="ws_1" canWrite={canWrite} />
    </QueryClientProvider>,
  );
}

describe("LlmSettingsPanel", () => {
  it("shows ZERO-tier empty state when no config is set", async () => {
    renderPanel();
    expect(await screen.findByTestId("llm-none")).toBeInTheDocument();
  });

  it("hides the write form for non-admins", async () => {
    renderPanel(false);
    await screen.findByTestId("llm-none");
    expect(screen.queryByTestId("llm-save")).not.toBeInTheDocument();
  });

  it("saves a provider and clears the key input", async () => {
    renderPanel();
    const user = userEvent.setup();
    await screen.findByTestId("llm-none");
    await user.type(screen.getByLabelText(/model/i), "claude-sonnet-4-5");
    await user.type(screen.getByLabelText(/api key/i), "sk-secret-123456");
    await user.click(screen.getByTestId("llm-save"));
    await waitFor(() => {
      expect(screen.getByLabelText(/api key/i)).toHaveValue("");
    });
  });

  it("runs a connection test and renders the result", async () => {
    renderPanel();
    const user = userEvent.setup();
    await screen.findByTestId("llm-none");
    await user.type(screen.getByLabelText(/model/i), "mock-1");
    await user.click(screen.getByTestId("llm-test"));
    const result = await screen.findByTestId("llm-test-result");
    expect(result).toHaveTextContent(/OK — mock-1/);
  });

  it("shows active config + Remove when configured", async () => {
    server.use(
      http.get("*/api/v1/workspaces/ws_1/llm-config", () =>
        HttpResponse.json({
          id: "llmcfg_1",
          provider: "anthropic",
          model: "claude-sonnet-4-5",
          apiKeyHint: "sk-a…7890",
          config: {},
          isActive: true,
          tier: "CLOUD",
          lastValidatedAt: null,
        }),
      ),
    );
    renderPanel();
    expect(await screen.findByTestId("llm-remove")).toBeInTheDocument();
    const status = screen.getByTestId("llm-current-status");
    expect(status).toHaveTextContent(/anthropic/);
    expect(status).toHaveTextContent(/CLOUD/);
  });
});
