import { act } from "react";

import { useCapabilities, type Capabilities } from "@/stores/use-capabilities";

/**
 * ZERO tier (no LLM) — the safe default. Agent surfaces collapse to empty
 * states and AI auto-actions are disabled.
 */
export const ZERO_CAPS: Capabilities = {
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

/**
 * CLOUD tier with all AI features enabled. Used to assert that AI surfaces
 * render in non-ZERO tiers.
 */
export const CLOUD_CAPS: Capabilities = {
  tier: "CLOUD",
  llm: {
    provider: "anthropic",
    model: "claude-opus-4-7",
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
  mcpProviders: [
    {
      id: "playwright-mcp",
      name: "Playwright MCP",
      kind: "FE_WEB",
      health: "healthy",
      isDefault: true,
    },
  ],
  version: "1.0.0",
};

/**
 * Synchronously seed the capabilities store inside an `act()` block.
 * Use from `beforeEach` to ensure `<Gated>` resolves before render asserts.
 */
export function setCaps(caps: Capabilities): void {
  act(() => {
    useCapabilities.setState({ capabilities: caps, loading: false, error: null });
  });
}

/** Reset the store to its initial (pre-fetch) state. */
export function resetCaps(): void {
  act(() => {
    useCapabilities.setState({ capabilities: null, loading: true, error: null });
  });
}
