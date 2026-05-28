import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { TierBadge } from "@/components/shared/TierBadge";
import { useCapabilities, type Capabilities } from "@/stores/use-capabilities";

const BASE_FEATURES = {
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
};

const ZERO_CAPS: Capabilities = {
  tier: "ZERO",
  llm: { provider: "none", model: null, base_url: null, is_test_provider: false },
  embeddings: { enabled: false, backend: "none", model: null, dim: null },
  features: BASE_FEATURES,
  autonomy: { available: ["manual"], default: "manual" },
  mcpProviders: [],
  version: "1.0.0",
};

const LOCAL_CAPS: Capabilities = {
  ...ZERO_CAPS,
  tier: "LOCAL",
  llm: { provider: "ollama", model: "llama3.1", base_url: "http://localhost:11434", is_test_provider: false },
  features: { ...BASE_FEATURES, ai_generation: true, ai_conversation: true },
  autonomy: { available: ["manual", "assist"], default: "assist" },
};

const CLOUD_CAPS: Capabilities = {
  ...ZERO_CAPS,
  tier: "CLOUD",
  llm: { provider: "anthropic", model: "claude-sonnet-4-5", base_url: null, is_test_provider: false },
  features: { ...BASE_FEATURES, ai_generation: true, ai_conversation: true },
  autonomy: { available: ["manual", "assist", "semi_auto", "auto"], default: "assist" },
};

function setCaps(caps: Capabilities): void {
  act(() => {
    useCapabilities.setState({ capabilities: caps, loading: false, error: null });
  });
}

describe("<TierBadge>", () => {
  beforeEach(() => {
    act(() => {
      useCapabilities.setState({ capabilities: null, loading: true, error: null });
    });
  });
  afterEach(() => {
    act(() => {
      useCapabilities.setState({ capabilities: null, loading: true, error: null });
    });
  });

  it("renders ZERO with no provider/model suffix", () => {
    setCaps(ZERO_CAPS);
    render(<TierBadge />);
    const badge = screen.getByTestId("tier-badge");
    expect(badge).toHaveAttribute("data-tier", "ZERO");
    expect(badge).toHaveTextContent("ZERO");
    expect(badge.textContent).not.toContain("·");
  });

  it("renders LOCAL with provider:model suffix and blue tone", () => {
    setCaps(LOCAL_CAPS);
    render(<TierBadge />);
    const badge = screen.getByTestId("tier-badge");
    expect(badge).toHaveTextContent("LOCAL · ollama:llama3.1");
    expect(badge.className).toContain("text-blue");
  });

  it("renders CLOUD with provider:model suffix and violet tone", () => {
    setCaps(CLOUD_CAPS);
    render(<TierBadge />);
    const badge = screen.getByTestId("tier-badge");
    expect(badge).toHaveTextContent("CLOUD · anthropic:claude-sonnet-4-5");
    expect(badge.className).toContain("text-violet");
  });

  it("opens popover on click with provider/model rows + Configure link", async () => {
    setCaps(CLOUD_CAPS);
    render(<TierBadge />);
    await userEvent.click(screen.getByTestId("tier-badge"));
    const popover = await screen.findByTestId("tier-badge-popover");
    expect(popover).toHaveTextContent("anthropic");
    expect(popover).toHaveTextContent("claude-sonnet-4-5");
    expect(screen.getByTestId("tier-badge-configure")).toHaveAttribute("href", "/settings/llm");
  });

  it("falls back to ZERO when capabilities are not loaded yet", () => {
    render(<TierBadge />);
    expect(screen.getByTestId("tier-badge")).toHaveAttribute("data-tier", "ZERO");
  });

  it("renders ZERO fallback when capabilities.llm is undefined (malformed response)", () => {
    // Regression: a misconfigured Vite proxy or a mock fixture missing fields
    // can leave `capabilities` non-null but `.llm` undefined. Previously this
    // crashed with "Cannot read properties of undefined (reading 'provider')".
    setCaps({ tier: "ZERO" } as unknown as Capabilities);
    render(<TierBadge />);
    const badge = screen.getByTestId("tier-badge");
    expect(badge).toHaveAttribute("data-tier", "ZERO");
    expect(badge).toHaveTextContent("ZERO");
  });
});
