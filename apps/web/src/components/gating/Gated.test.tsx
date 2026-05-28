import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { Gated } from "@/components/gating/Gated";
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

function setCaps(caps: Capabilities): void {
  act(() => {
    useCapabilities.setState({ capabilities: caps, loading: false, error: null });
  });
}

describe("<Gated>", () => {
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

  it("renders fallback when feature is disabled (ZERO tier, ai_generation)", () => {
    setCaps(ZERO_CAPS);
    render(
      <Gated feature="ai_generation" fallback={<span data-testid="fallback">locked</span>}>
        <span data-testid="children">go</span>
      </Gated>,
    );
    expect(screen.queryByTestId("children")).toBeNull();
    expect(screen.getByTestId("fallback")).toBeInTheDocument();
  });

  it("renders children when feature is enabled (CLOUD tier, ai_generation)", () => {
    setCaps(CLOUD_CAPS);
    render(
      <Gated feature="ai_generation" fallback={<span data-testid="fallback">locked</span>}>
        <span data-testid="children">go</span>
      </Gated>,
    );
    expect(screen.getByTestId("children")).toBeInTheDocument();
    expect(screen.queryByTestId("fallback")).toBeNull();
  });

  it("renders nothing (null) for disabled feature without a fallback", () => {
    setCaps(ZERO_CAPS);
    const { container } = render(
      <Gated feature="ai_conversation">
        <span data-testid="children">go</span>
      </Gated>,
    );
    expect(screen.queryByTestId("children")).toBeNull();
    expect(container.textContent).toBe("");
  });

  it("renders fallback when capabilities have not loaded yet", () => {
    // Default loading state: capabilities = null → all features disabled.
    render(
      <Gated feature="manual_tcm" fallback={<span data-testid="fallback">wait</span>}>
        <span data-testid="children">go</span>
      </Gated>,
    );
    expect(screen.getByTestId("fallback")).toBeInTheDocument();
  });

  it("derives ai_panel from ai_conversation || ai_generation", () => {
    setCaps(CLOUD_CAPS);
    render(
      <Gated feature="ai_panel" fallback={<span data-testid="fallback">locked</span>}>
        <span data-testid="children">panel</span>
      </Gated>,
    );
    expect(screen.getByTestId("children")).toBeInTheDocument();
  });

  it("derives autonomy_assist=false when autonomy.available is [manual] only", () => {
    setCaps(ZERO_CAPS);
    render(
      <Gated feature="autonomy_assist" fallback={<span data-testid="fallback">locked</span>}>
        <span data-testid="children">assist</span>
      </Gated>,
    );
    expect(screen.getByTestId("fallback")).toBeInTheDocument();
    expect(screen.queryByTestId("children")).toBeNull();
  });

  it("derives autonomy_assist=true when autonomy.available includes assist", () => {
    setCaps(CLOUD_CAPS);
    render(
      <Gated feature="autonomy_assist" fallback={<span data-testid="fallback">locked</span>}>
        <span data-testid="children">assist</span>
      </Gated>,
    );
    expect(screen.getByTestId("children")).toBeInTheDocument();
  });
});
