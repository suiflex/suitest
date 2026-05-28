import { create } from "zustand";

import { api } from "@/lib/api-client";

export type Tier = "ZERO" | "LOCAL" | "CLOUD";
export type AutonomyLevel = "manual" | "assist" | "semi_auto" | "auto";

export interface LLMInfo {
  provider: string | null;
  model: string | null;
  base_url: string | null;
  is_test_provider: boolean;
}

export interface EmbeddingsInfo {
  enabled: boolean;
  backend: string;
  model: string | null;
  dim: number | null;
}

export interface McpProviderInfo {
  id: string;
  name: string;
  kind: string;
  health: string;
  isDefault: boolean;
}

/**
 * 13 capability flags returned by the backend `/capabilities` endpoint.
 * Mirrors `FeaturesSection` in `packages/shared/.../schemas/capabilities.py`
 * (CAPABILITY_TIERS.md § 10).
 */
export interface CapabilityFeatures {
  manual_tcm: boolean;
  deterministic_runner: boolean;
  deterministic_generator_openapi: boolean;
  deterministic_generator_recorder: boolean;
  deterministic_generator_crawler: boolean;
  ai_generation: boolean;
  ai_execution_agentic: boolean;
  ai_diagnose: boolean;
  ai_conversation: boolean;
  semantic_search: boolean;
  fts_search: boolean;
  auto_defect_filing_ai: boolean;
  auto_defect_filing_rule: boolean;
}

export interface Capabilities {
  tier: Tier;
  llm: LLMInfo;
  embeddings: EmbeddingsInfo;
  features: CapabilityFeatures;
  autonomy: { available: AutonomyLevel[]; default: AutonomyLevel };
  mcpProviders?: McpProviderInfo[];
  version: string;
  build?: string | null;
}

/**
 * Feature keys understood by `useFeatureEnabled` and `<Gated>`.
 *
 * Direct keys map 1:1 to `Capabilities.features.*`. Derived keys are computed
 * from other fields:
 *   - `ai_panel`         = any AI feature enabled (ai_generation || ai_conversation)
 *   - `autonomy_assist`  = `autonomy.available.includes("assist")`
 *   - `autonomy_semi_auto` = `autonomy.available.includes("semi_auto")`
 *   - `autonomy_auto`    = `autonomy.available.includes("auto")`
 */
export type FeatureKey =
  | keyof CapabilityFeatures
  | "ai_panel"
  | "autonomy_assist"
  | "autonomy_semi_auto"
  | "autonomy_auto";

interface CapabilitiesState {
  capabilities: Capabilities | null;
  loading: boolean;
  error: string | null;
  fetch: () => Promise<void>;
  setCapabilities: (c: Capabilities) => void;
}

export const useCapabilities = create<CapabilitiesState>((set) => ({
  capabilities: null,
  loading: true,
  error: null,
  fetch: async () => {
    set({ loading: true, error: null });
    try {
      // The backend mounts `/capabilities` at the application root, NOT under
      // `/api/v1`. The shared axios client uses `baseURL: ".../api/v1"`, so we
      // override `baseURL` to empty for this one call to escape the prefix.
      const response = await api.get<Capabilities>("/capabilities", { baseURL: "" });
      const data = response.data as unknown;
      // Guard: if the Vite proxy is misconfigured the SPA fallback may return
      // `index.html` (a string), or a mock fixture may return a partial body.
      // Reject anything that doesn't look like a capability snapshot so the
      // failure surfaces as a visible error state rather than a downstream
      // "Cannot read properties of undefined" crash in TierBadge / Gated.
      if (!data || typeof data !== "object" || !("tier" in data)) {
        throw new Error(
          "Invalid capabilities response (expected JSON object with a `tier` field)",
        );
      }
      set({ capabilities: data as Capabilities, loading: false });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load capabilities";
      set({ error: message, loading: false });
    }
  },
  setCapabilities: (c) => set({ capabilities: c, loading: false, error: null }),
}));
