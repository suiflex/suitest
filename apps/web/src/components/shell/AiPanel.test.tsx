import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AiPanel } from "@/components/shell/AiPanel";
import { fetchLlmModels } from "@/lib/api-client";
import { useActiveWorkspace } from "@/stores/use-active-workspace";
import { useCapabilities, type Capabilities } from "@/stores/use-capabilities";

vi.mock("@/lib/api-client", () => ({ fetchLlmModels: vi.fn() }));

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

const CLOUD_ASSIST_CAPS: Capabilities = {
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

function setCaps(caps: Capabilities): void {
  act(() => {
    useCapabilities.setState({ capabilities: caps, loading: false, error: null });
  });
}

describe("<AiPanel>", () => {
  beforeEach(() => {
    act(() => {
      useCapabilities.setState({ capabilities: null, loading: true, error: null });
    });
  });
  afterEach(() => {
    act(() => {
      useCapabilities.setState({ capabilities: null, loading: true, error: null });
      useActiveWorkspace.setState({ workspaceId: null });
    });
    localStorage.removeItem("suitest.agentModel");
    vi.mocked(fetchLlmModels).mockReset();
  });

  it("renders nothing in ZERO tier (ai_conversation disabled)", () => {
    setCaps(ZERO_CAPS);
    const { container } = render(<AiPanel />);
    expect(container.textContent).toBe("");
    expect(screen.queryByTestId("ai-panel")).toBeNull();
  });

  it("renders the panel in CLOUD tier with provider + model + autonomy subtitle", () => {
    setCaps(CLOUD_ASSIST_CAPS);
    render(<AiPanel />);
    expect(screen.getByTestId("ai-panel")).toBeInTheDocument();
    expect(screen.getByText("Suitest Agent")).toBeInTheDocument();
    expect(screen.getByTestId("ai-panel-subtitle")).toHaveTextContent(
      "Anthropic:claude-sonnet-4-5 · assist",
    );
  });

  it("renders the empty-thread agent greeting", () => {
    setCaps(CLOUD_ASSIST_CAPS);
    render(<AiPanel />);
    expect(screen.getByTestId("ai-panel-thread")).toHaveTextContent(/or ask me to edit a test/i);
  });

  it("renders an enabled composer (send gated until input typed)", () => {
    setCaps(CLOUD_ASSIST_CAPS);
    render(<AiPanel />);
    const input = screen.getByTestId("ai-panel-composer-input");
    expect(input).not.toBeDisabled();
    expect(input).toHaveAttribute("placeholder", "Ask the agent…");
    // Send is disabled until the user types something.
    expect(screen.getByTestId("ai-panel-send")).toBeDisabled();
  });

  it("renders nothing while capabilities are still loading", () => {
    // beforeEach already sets capabilities=null; do nothing.
    const { container } = render(<AiPanel />);
    expect(container.textContent).toBe("");
  });

  it("offers the provider's models and remembers the pick", async () => {
    vi.mocked(fetchLlmModels).mockResolvedValue([
      { id: "claude-sonnet-4-5" },
      { id: "claude-haiku-4-5" },
    ] as Awaited<ReturnType<typeof fetchLlmModels>>);
    localStorage.removeItem("suitest.agentModel");
    act(() => {
      useActiveWorkspace.setState({ workspaceId: "ws_1" });
    });
    setCaps(CLOUD_ASSIST_CAPS);
    render(<AiPanel />);

    const picker = await screen.findByTestId("ai-panel-model");
    expect(picker).toHaveValue("claude-sonnet-4-5");

    await userEvent.selectOptions(picker, "claude-haiku-4-5");
    expect(localStorage.getItem("suitest.agentModel")).toBe("claude-haiku-4-5");
  });

  it("keeps the plain subtitle when the provider has no model catalog", async () => {
    vi.mocked(fetchLlmModels).mockResolvedValue([]);
    act(() => {
      useActiveWorkspace.setState({ workspaceId: "ws_1" });
    });
    setCaps(CLOUD_ASSIST_CAPS);
    render(<AiPanel />);
    await waitFor(() => expect(fetchLlmModels).toHaveBeenCalled());
    expect(screen.getByTestId("ai-panel-subtitle")).toHaveTextContent(
      "Anthropic:claude-sonnet-4-5 · assist",
    );
    expect(screen.queryByTestId("ai-panel-model")).toBeNull();
  });

  it("toggles auto-approve and surfaces the warning", async () => {
    setCaps(CLOUD_ASSIST_CAPS);
    localStorage.removeItem("suitest.agentAutoApprove");
    render(<AiPanel />);
    const toggle = screen.getByTestId("ai-panel-autoapprove");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByTestId("ai-panel-autoapprove-warning")).toBeNull();

    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("ai-panel-autoapprove-warning")).toBeInTheDocument();
    expect(localStorage.getItem("suitest.agentAutoApprove")).toBe("1");
  });
});
