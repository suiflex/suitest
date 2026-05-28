import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AutonomyIndicator } from "@/components/shared/AutonomyIndicator";
import { useCapabilities, type Capabilities } from "@/stores/use-capabilities";

const BASE: Capabilities = {
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

function withAutonomy(level: Capabilities["autonomy"]["default"]): Capabilities {
  return { ...BASE, autonomy: { available: [level], default: level } };
}

function setCaps(caps: Capabilities): void {
  act(() => {
    useCapabilities.setState({ capabilities: caps, loading: false, error: null });
  });
}

describe("<AutonomyIndicator>", () => {
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

  it.each([
    ["manual", "manual", "text-fg-3"],
    ["assist", "assist", "text-blue"],
    ["semi_auto", "semi-auto", "text-violet"],
    ["auto", "auto", "text-accent"],
  ] as const)("renders %s as 'Mode: %s'", (level, levelLabel, klass) => {
    setCaps(withAutonomy(level));
    render(<AutonomyIndicator />);
    const el = screen.getByTestId("autonomy-indicator");
    expect(el).toHaveAttribute("data-level", level);
    // Render emits two inline <span>s, so the DOM textContent has no space
    // between them — assert each segment instead of a glued string.
    expect(el).toHaveTextContent(/Mode:/);
    expect(el).toHaveTextContent(levelLabel);
    expect(el.className).toContain(klass);
  });

  it("links to /settings/automation", () => {
    setCaps(withAutonomy("assist"));
    render(<AutonomyIndicator />);
    expect(screen.getByTestId("autonomy-indicator")).toHaveAttribute(
      "href",
      "/settings/automation",
    );
  });

  it("falls back to manual when capabilities not loaded", () => {
    render(<AutonomyIndicator />);
    expect(screen.getByTestId("autonomy-indicator")).toHaveAttribute("data-level", "manual");
  });
});
