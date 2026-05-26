import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { useCapabilities } from "@/stores/use-capabilities";

describe("useCapabilities", () => {
  beforeEach(() => {
    useCapabilities.setState({ data: null, isLoading: false, error: null });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("populates store with ZERO tier payload on success", async () => {
    const payload = {
      tier: "ZERO" as const,
      llm: { provider: null, model: null, base_url: null, is_test_provider: false },
      embeddings: { enabled: false, backend: "none", model: null, dim: null },
      features: { manual_tcm: true, ai_generation: false },
      autonomy: { available: ["manual" as const], default: "manual" as const },
      mcp_providers: [],
      version: "0.1.0",
    };
    vi.spyOn(apiClient, "get").mockResolvedValueOnce({ data: payload } as never);

    await useCapabilities.getState().fetch();

    const state = useCapabilities.getState();
    expect(state.isLoading).toBe(false);
    expect(state.error).toBeNull();
    expect(state.data?.tier).toBe("ZERO");
    expect(state.data?.features["ai_generation"]).toBe(false);
  });

  it("records error message on failure", async () => {
    vi.spyOn(apiClient, "get").mockRejectedValueOnce(new Error("network down"));

    await useCapabilities.getState().fetch();

    const state = useCapabilities.getState();
    expect(state.data).toBeNull();
    expect(state.error).toBe("network down");
  });
});
