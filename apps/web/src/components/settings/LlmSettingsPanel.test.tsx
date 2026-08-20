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

  it("signs in with ChatGPT and stores the credential", async () => {
    let polls = 0;
    let finished: unknown = null;
    server.use(
      http.post("*/api/v1/workspaces/ws_1/llm-config/chatgpt/login", () =>
        HttpResponse.json({
          flowId: "flow_1",
          mode: "device",
          verificationUrl: "https://auth.openai.com/codex/device",
          userCode: "ABCD-EFGH",
          intervalS: 1,
        }),
      ),
      http.get("*/api/v1/workspaces/ws_1/llm-config/chatgpt/login/flow_1", () => {
        polls += 1;
        return polls === 1
          ? HttpResponse.json({ status: "pending" })
          : HttpResponse.json({ status: "ready", account: "dev@example.com" });
      }),
      http.post(
        "*/api/v1/workspaces/ws_1/llm-config/chatgpt/login/flow_1/finish",
        async ({ request }) => {
          finished = await request.json();
          return HttpResponse.json({
            id: "llmcfg_1",
            provider: "chatgpt",
            model: "gpt-5.6",
            apiKeyHint: null,
            config: {},
            isActive: true,
            tier: "CLOUD",
            lastValidatedAt: null,
            authMethod: "oauth",
            oauthAccount: "dev@example.com",
          });
        },
      ),
    );

    renderPanel();
    const user = userEvent.setup();
    await screen.findByTestId("llm-none");
    await user.click(screen.getByLabelText(/sign in with chatgpt/i));
    await user.click(screen.getByTestId("chatgpt-signin-start"));

    // The device code is what the user has to carry to the browser.
    expect(await screen.findByTestId("chatgpt-signin-pending")).toHaveTextContent("ABCD-EFGH");

    const ready = await screen.findByTestId("chatgpt-signin-ready", {}, { timeout: 3000 });
    expect(ready).toHaveTextContent(/dev@example.com/);

    await user.type(screen.getByLabelText(/model/i), "gpt-5.6");
    await user.click(screen.getByLabelText(/my chatgpt plan/i));
    await user.click(screen.getByTestId("chatgpt-signin-finish"));

    await waitFor(() => {
      expect(finished).toEqual({ credentialMode: "subscription", model: "gpt-5.6" });
    });
  });

  it("reports the status when the sign-in route answers an error", async () => {
    // The regression this guards: an API older than the bundle answered 405 and
    // the panel said only "Could not start the sign-in.", which reads like a
    // rejected credential rather than a route that is not there.
    server.use(
      http.post("*/api/v1/workspaces/ws_1/llm-config/chatgpt/login", () =>
        HttpResponse.json({ detail: "Method Not Allowed" }, { status: 405 }),
      ),
    );
    renderPanel();
    const user = userEvent.setup();
    await screen.findByTestId("llm-none");
    await user.click(screen.getByLabelText(/sign in with chatgpt/i));
    await user.click(screen.getByTestId("chatgpt-signin-start"));

    const err = await screen.findByText(/could not start the sign-in/i);
    expect(err).toHaveTextContent(/405/);
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
