import { create } from "zustand";

import { apiClient } from "@/lib/api-client";

export type Tier = "ZERO" | "LOCAL" | "CLOUD";
export type AutonomyLevel = "manual" | "assist" | "semi_auto" | "auto";

export interface LLMInfo {
  provider: string | null;
  model: string | null;
  base_url: string | null;
  is_test_provider: boolean;
}

export interface McpProviderInfo {
  id: string;
  name: string;
  kind: string;
  health: string;
  is_default: boolean;
}

export interface Capabilities {
  tier: Tier;
  llm: LLMInfo;
  embeddings: { enabled: boolean; backend: string; model: string | null; dim: number | null };
  features: Record<string, boolean>;
  autonomy: { available: AutonomyLevel[]; default: AutonomyLevel };
  mcp_providers: McpProviderInfo[];
  version: string;
}

interface CapabilitiesState {
  data: Capabilities | null;
  isLoading: boolean;
  error: string | null;
  fetch: () => Promise<void>;
}

export const useCapabilities = create<CapabilitiesState>((set) => ({
  data: null,
  isLoading: false,
  error: null,
  fetch: async () => {
    set({ isLoading: true, error: null });
    try {
      const response = await apiClient.get<Capabilities>("/capabilities");
      set({ data: response.data, isLoading: false });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load capabilities";
      set({ error: message, isLoading: false });
    }
  },
}));
