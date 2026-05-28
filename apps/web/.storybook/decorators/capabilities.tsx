import type { Decorator } from "@storybook/react-vite";
import { useEffect } from "react";

import { CLOUD_CAPS, ZERO_CAPS } from "../../src/test/capabilities";
import { useCapabilities, type Capabilities } from "../../src/stores/use-capabilities";

const LOCAL_CAPS: Capabilities = {
  ...CLOUD_CAPS,
  tier: "LOCAL",
  llm: { provider: "ollama", model: "llama3:8b", base_url: "http://localhost:11434", is_test_provider: false },
};

type TierKey = "ZERO" | "LOCAL" | "CLOUD";

const TIER_MAP: Record<TierKey, Capabilities> = {
  ZERO: ZERO_CAPS,
  LOCAL: LOCAL_CAPS,
  CLOUD: CLOUD_CAPS,
};

/**
 * Seeds the `useCapabilities` Zustand store on each render so stories can
 * mount components that depend on tier resolution (Gated, AiPanel, etc.)
 * without a backend round-trip. Default tier is CLOUD because the mockup
 * was authored at CLOUD-tier feature completeness.
 *
 * Override per story via `parameters.capabilities = "ZERO" | "LOCAL" | "CLOUD"`.
 */
export const withCapabilities: Decorator = (Story, ctx) => {
  const tier = (ctx.parameters.capabilities as TierKey | undefined) ?? "CLOUD";
  useEffect(() => {
    useCapabilities.setState({
      capabilities: TIER_MAP[tier],
      loading: false,
      error: null,
    });
  }, [tier]);
  // Seed synchronously so the first render sees the tier (no flash).
  useCapabilities.setState({
    capabilities: TIER_MAP[tier],
    loading: false,
    error: null,
  });
  return <Story />;
};
