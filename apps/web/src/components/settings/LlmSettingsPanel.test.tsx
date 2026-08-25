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
    await user.selectOptions(screen.getByLabelText(/^provider$/i), "openai");
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
    await user.selectOptions(screen.getByLabelText(/^provider$/i), "openai");
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
    // Named for a person, not the raw provider key.
    expect(status).toHaveTextContent(/Anthropic/);
    expect(status).toHaveTextContent(/CLOUD/);
  });

  it("signs in with Google on localhost by polling the loopback listener", async () => {
    let polls = 0;
    let finished: unknown = null;
    server.use(
      http.post("*/api/v1/workspaces/ws_1/llm-config/google/login", () =>
        HttpResponse.json({
          flowId: "g_1",
          mode: "browser",
          authorizeUrl: "https://accounts.example/auth",
          intervalS: 1,
        }),
      ),
      http.get("*/api/v1/workspaces/ws_1/llm-config/google/login/g_1", () => {
        polls += 1;
        return polls === 1
          ? HttpResponse.json({ status: "pending" })
          : HttpResponse.json({ status: "ready", email: "dev@example.com", hasRefreshToken: true });
      }),
      http.get("*/api/v1/workspaces/ws_1/llm-config/google/login/g_1/projects", () =>
        HttpResponse.json({ projects: [{ projectId: "my-project-123", name: "My Project" }] }),
      ),
      http.post(
        "*/api/v1/workspaces/ws_1/llm-config/google/login/g_1/finish",
        async ({ request }) => {
          finished = await request.json();
          return HttpResponse.json({
            id: "cfg_1",
            provider: "google-vertex",
            model: "google/gemini-2.5-pro",
            config: {},
            isActive: true,
            tier: "CLOUD",
          });
        },
      ),
    );

    renderPanel();
    const user = userEvent.setup();
    await screen.findByTestId("llm-none");
    await user.selectOptions(screen.getByLabelText(/^provider$/i), "google");
    await user.click(screen.getByLabelText(/sign in with google/i));
    await user.click(screen.getByTestId("google-signin-start"));

    await screen.findByTestId("google-signin-ready", undefined, { timeout: 4000 });
    expect(screen.getByTestId("google-signin-ready")).toHaveTextContent(/dev@example.com/);

    // Vertex is the backend that needs a project; Code Assist is the default.
    await user.click(screen.getByLabelText(/vertex ai/i));
    // The project list was readable, so this is a pick rather than a typed id.
    await user.selectOptions(
      await screen.findByTestId("google-signin-project-select"),
      "my-project-123",
    );
    await user.click(screen.getByTestId("google-signin-finish"));

    await waitFor(() => {
      expect(finished).toEqual({
        model: "google/gemini-2.5-pro",
        backend: "vertex",
        gcpProject: "my-project-123",
        gcpLocation: "us-central1",
      });
    });
  });

  it("falls back to pasting the callback URL when loopback cannot be reached", async () => {
    let submitted: unknown = null;
    server.use(
      http.post("*/api/v1/workspaces/ws_1/llm-config/google/login", () =>
        HttpResponse.json({
          flowId: "g_2",
          mode: "paste",
          authorizeUrl: "https://accounts.example/auth",
          intervalS: 2,
        }),
      ),
      http.get("*/api/v1/workspaces/ws_1/llm-config/google/login/g_2", () => {
        throw new Error("paste mode must not poll — there is no listener to wait on");
      }),
      http.post(
        "*/api/v1/workspaces/ws_1/llm-config/google/login/g_2/callback",
        async ({ request }) => {
          submitted = await request.json();
          return HttpResponse.json({
            status: "ready",
            email: "dev@example.com",
            hasRefreshToken: true,
          });
        },
      ),
    );

    renderPanel();
    const user = userEvent.setup();
    await screen.findByTestId("llm-none");
    await user.selectOptions(screen.getByLabelText(/^provider$/i), "google");
    await user.click(screen.getByLabelText(/sign in with google/i));
    await user.click(screen.getByTestId("google-signin-start"));

    const url = "http://127.0.0.1:8765/?state=abc&code=4/xyz";
    await user.type(await screen.findByTestId("google-signin-callback-url"), url);
    await user.click(screen.getByTestId("google-signin-submit-url"));

    await screen.findByTestId("google-signin-ready");
    expect(submitted).toEqual({ callbackUrl: url });
  });

  it("offers no auth choice for a vendor that has only one way in", async () => {
    renderPanel();
    const user = userEvent.setup();
    await screen.findByTestId("llm-none");

    // Anthropic takes a key and nothing else — a radio with one option is noise.
    await user.selectOptions(screen.getByLabelText(/^provider$/i), "anthropic");
    expect(screen.queryByTestId("llm-auth-method")).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText(/^provider$/i), "openai");
    expect(screen.getByTestId("llm-auth-method")).toBeInTheDocument();
  });

  it("puts each sign-in under the vendor it authenticates to", async () => {
    renderPanel();
    const user = userEvent.setup();
    await screen.findByTestId("llm-none");

    await user.selectOptions(screen.getByLabelText(/^provider$/i), "openai");
    expect(screen.getByLabelText(/sign in with chatgpt/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/sign in with google/i)).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText(/^provider$/i), "google");
    expect(screen.getByLabelText(/sign in with google/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/sign in with chatgpt/i)).not.toBeInTheDocument();
  });

  it("renders one form body at a time", async () => {
    renderPanel();
    const user = userEvent.setup();
    await screen.findByTestId("llm-none");

    // Both bodies carry a Model field; rendering them together would make every
    // getByLabelText(/model/i) in this file ambiguous.
    await user.selectOptions(screen.getByLabelText(/^provider$/i), "google");
    await user.click(screen.getByLabelText(/sign in with google/i));
    expect(screen.getByTestId("google-signin")).toBeInTheDocument();
    expect(screen.queryByTestId("llm-save")).not.toBeInTheDocument();

    await user.click(screen.getByLabelText(/paste a key/i));
    expect(screen.queryByTestId("google-signin")).not.toBeInTheDocument();
    expect(screen.getByTestId("llm-save")).toBeInTheDocument();
  });

  it("drops back to the key form when the new vendor has no sign-in", async () => {
    renderPanel();
    const user = userEvent.setup();
    await screen.findByTestId("llm-none");

    await user.selectOptions(screen.getByLabelText(/^provider$/i), "google");
    await user.click(screen.getByLabelText(/sign in with google/i));
    expect(screen.getByTestId("google-signin")).toBeInTheDocument();

    // Anthropic has no sign-in — the stale choice must not leave a dead panel.
    await user.selectOptions(screen.getByLabelText(/^provider$/i), "anthropic");
    expect(screen.queryByTestId("google-signin")).not.toBeInTheDocument();
    expect(screen.getByTestId("llm-save")).toBeInTheDocument();
  });

  it("saves the provider key the picked vendor maps to", async () => {
    let saved: unknown = null;
    server.use(
      http.put("*/api/v1/workspaces/ws_1/llm-config", async ({ request }) => {
        saved = await request.json();
        return HttpResponse.json({
          id: "cfg_1",
          provider: "gemini",
          model: "gemini-2.5-pro",
          config: {},
          isActive: true,
          tier: "CLOUD",
        });
      }),
    );

    renderPanel();
    const user = userEvent.setup();
    await screen.findByTestId("llm-none");
    // The vendor reads "Google"; the stored provider key is still `gemini`.
    await user.selectOptions(screen.getByLabelText(/^provider$/i), "google");
    await user.type(screen.getByLabelText(/model/i), "gemini-2.5-pro");
    await user.type(screen.getByLabelText(/api key/i), "AIza-secret");
    await user.click(screen.getByTestId("llm-save"));

    await waitFor(() => {
      expect(saved).toMatchObject({ provider: "gemini", model: "gemini-2.5-pro" });
    });
  });

  it("still lets the sign-in finish when the project list cannot be read", async () => {
    let finished: unknown = null;
    server.use(
      http.post("*/api/v1/workspaces/ws_1/llm-config/google/login", () =>
        HttpResponse.json({
          flowId: "g_3",
          mode: "paste",
          authorizeUrl: "https://x/auth",
          intervalS: 2,
        }),
      ),
      http.post("*/api/v1/workspaces/ws_1/llm-config/google/login/g_3/callback", () =>
        HttpResponse.json({ status: "ready", email: "dev@example.com", hasRefreshToken: true }),
      ),
      // Resource Manager disabled, or no permission on the account.
      http.get("*/api/v1/workspaces/ws_1/llm-config/google/login/g_3/projects", () =>
        HttpResponse.json({ projects: [] }),
      ),
      http.post(
        "*/api/v1/workspaces/ws_1/llm-config/google/login/g_3/finish",
        async ({ request }) => {
          finished = await request.json();
          return HttpResponse.json({
            id: "cfg_1",
            provider: "google-vertex",
            model: "google/gemini-2.5-pro",
            config: {},
            isActive: true,
            tier: "CLOUD",
          });
        },
      ),
    );

    renderPanel();
    const user = userEvent.setup();
    await screen.findByTestId("llm-none");
    await user.selectOptions(screen.getByLabelText(/^provider$/i), "google");
    await user.click(screen.getByLabelText(/sign in with google/i));
    await user.click(screen.getByTestId("google-signin-start"));
    await user.type(
      await screen.findByTestId("google-signin-callback-url"),
      "http://127.0.0.1:8765/?state=s&code=4/x",
    );
    await user.click(screen.getByTestId("google-signin-submit-url"));

    await user.click(screen.getByLabelText(/vertex ai/i));
    // No list, so the id is typed — the sign-in itself is still good.
    const input = await screen.findByTestId("google-signin-project-input");
    await user.type(input, "typed-project");
    await user.click(screen.getByTestId("google-signin-finish"));

    await waitFor(() => {
      expect(finished).toMatchObject({
        backend: "vertex",
        gcpProject: "typed-project",
        gcpLocation: "us-central1",
      });
    });
  });

  it("warns before a sign-in is spent on an unlicensed session", async () => {
    server.use(
      http.post("*/api/v1/workspaces/ws_1/llm-config/chatgpt/login", () =>
        HttpResponse.json({
          flowId: "c_1",
          mode: "browser",
          authorizeUrl: "https://x/a",
          intervalS: 1,
        }),
      ),
      http.get("*/api/v1/workspaces/ws_1/llm-config/chatgpt/login/c_1", () =>
        HttpResponse.json({ status: "ready", account: "dev@example.com" }),
      ),
    );

    renderPanel();
    const user = userEvent.setup();
    await screen.findByTestId("llm-none");
    await user.selectOptions(screen.getByLabelText(/^provider$/i), "openai");
    await user.click(screen.getByLabelText(/sign in with chatgpt/i));
    await user.click(screen.getByTestId("chatgpt-signin-start"));
    await screen.findByTestId("chatgpt-signin-ready");

    // The API-key mode ends in a real, licensed key — nothing to warn about.
    expect(screen.queryByTestId("unlicensed-session-notice")).not.toBeInTheDocument();

    await user.click(screen.getByLabelText(/my chatgpt plan/i));
    expect(screen.getByTestId("unlicensed-session-notice")).toBeInTheDocument();
  });

  it("asks for nothing when the sign-in is spent on code assist", async () => {
    let finished: unknown = null;
    let projectsAsked = false;
    server.use(
      http.post("*/api/v1/workspaces/ws_1/llm-config/google/login", () =>
        HttpResponse.json({
          flowId: "g_4",
          mode: "browser",
          authorizeUrl: "https://x/a",
          intervalS: 1,
        }),
      ),
      http.get("*/api/v1/workspaces/ws_1/llm-config/google/login/g_4", () =>
        HttpResponse.json({ status: "ready", email: "dev@example.com", hasRefreshToken: true }),
      ),
      http.get("*/api/v1/workspaces/ws_1/llm-config/google/login/g_4/projects", () => {
        projectsAsked = true;
        return HttpResponse.json({ projects: [] });
      }),
      http.post(
        "*/api/v1/workspaces/ws_1/llm-config/google/login/g_4/finish",
        async ({ request }) => {
          finished = await request.json();
          return HttpResponse.json({
            id: "cfg_1",
            provider: "google-codeassist",
            model: "gemini-2.5-pro",
            config: {},
            isActive: true,
            tier: "CLOUD",
          });
        },
      ),
    );

    renderPanel();
    const user = userEvent.setup();
    await screen.findByTestId("llm-none");
    await user.selectOptions(screen.getByLabelText(/^provider$/i), "google");
    await user.click(screen.getByLabelText(/sign in with google/i));
    await user.click(screen.getByTestId("google-signin-start"));
    await screen.findByTestId("google-signin-ready");

    // The whole point of this backend: the account already knows its project.
    expect(screen.queryByTestId("google-signin-project-select")).not.toBeInTheDocument();
    expect(screen.queryByTestId("google-signin-project-input")).not.toBeInTheDocument();
    // It spends an unlicensed session, so it says so.
    expect(screen.getByTestId("unlicensed-session-notice")).toBeInTheDocument();

    await user.click(screen.getByTestId("google-signin-finish"));

    await waitFor(() => {
      expect(finished).toEqual({ model: "gemini-2.5-pro", backend: "code_assist" });
    });
    // And it never went looking for a project list it does not need.
    expect(projectsAsked).toBe(false);
  });

  it("signs in to antigravity with its own oauth client and no key option", async () => {
    let startBody: unknown = null;
    let finished: unknown = null;
    server.use(
      http.post("*/api/v1/workspaces/ws_1/llm-config/google/login", async ({ request }) => {
        startBody = await request.json();
        return HttpResponse.json({
          flowId: "a_1",
          mode: "browser",
          authorizeUrl: "https://x/a",
          intervalS: 1,
        });
      }),
      http.get("*/api/v1/workspaces/ws_1/llm-config/google/login/a_1", () =>
        HttpResponse.json({ status: "ready", email: "dev@example.com", hasRefreshToken: true }),
      ),
      http.post(
        "*/api/v1/workspaces/ws_1/llm-config/google/login/a_1/finish",
        async ({ request }) => {
          finished = await request.json();
          return HttpResponse.json({
            id: "cfg_1",
            provider: "antigravity",
            model: "gemini-2.5-pro",
            config: {},
            isActive: true,
            tier: "CLOUD",
          });
        },
      ),
    );

    renderPanel();
    const user = userEvent.setup();
    await screen.findByTestId("llm-none");
    await user.selectOptions(screen.getByLabelText(/^provider$/i), "antigravity");

    // There is no key to paste for this one, so no choice is offered — the
    // sign-in panel is simply what the vendor is.
    expect(screen.queryByTestId("llm-auth-method")).not.toBeInTheDocument();
    expect(screen.getByTestId("google-signin")).toBeInTheDocument();

    await user.click(screen.getByTestId("google-signin-start"));
    expect(startBody).toEqual({ mode: "auto", variant: "antigravity" });

    await screen.findByTestId("google-signin-ready");
    // One backend, so no backend choice and no project question.
    expect(screen.queryByLabelText(/vertex ai/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("google-signin-project-input")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("google-signin-finish"));
    await waitFor(() => {
      expect(finished).toEqual({ model: "gemini-2.5-pro", backend: "code_assist" });
    });
  });
});
