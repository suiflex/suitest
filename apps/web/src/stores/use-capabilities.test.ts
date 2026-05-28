import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api-client";
import { server } from "@/mocks/server";
import { useCapabilities, type Capabilities } from "@/stores/use-capabilities";

function resetStore(): void {
  useCapabilities.setState({
    capabilities: null,
    loading: true,
    error: null,
  });
}

const ZERO_PAYLOAD: Capabilities = {
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

describe("useCapabilities", () => {
  beforeEach(() => {
    resetStore();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("populates store with ZERO tier payload on success", async () => {
    vi.spyOn(api, "get").mockResolvedValueOnce({ data: ZERO_PAYLOAD } as never);

    await useCapabilities.getState().fetch();

    const state = useCapabilities.getState();
    expect(state.loading).toBe(false);
    expect(state.error).toBeNull();
    expect(state.capabilities?.tier).toBe("ZERO");
    expect(state.capabilities?.features.ai_generation).toBe(false);
    expect(state.capabilities?.features.manual_tcm).toBe(true);
    expect(state.capabilities?.autonomy.default).toBe("manual");
  });

  it("records error message on failure", async () => {
    vi.spyOn(api, "get").mockRejectedValueOnce(new Error("network down"));

    await useCapabilities.getState().fetch();

    const state = useCapabilities.getState();
    expect(state.capabilities).toBeNull();
    expect(state.loading).toBe(false);
    expect(state.error).toBe("network down");
  });

  it("escapes the /api/v1 baseURL prefix when fetching /capabilities", async () => {
    // MSW handler at the application root (no /api/v1 prefix). If the store
    // forgets to override baseURL, the request will be sent to
    //   http://localhost/api/v1/capabilities
    // which has no handler and would 404/throw.
    server.use(
      http.get("http://localhost/capabilities", () => HttpResponse.json(ZERO_PAYLOAD)),
    );

    await useCapabilities.getState().fetch();

    const state = useCapabilities.getState();
    expect(state.error).toBeNull();
    expect(state.capabilities?.tier).toBe("ZERO");
  });

  it("setCapabilities updates store directly without fetch", () => {
    useCapabilities.getState().setCapabilities(ZERO_PAYLOAD);
    const state = useCapabilities.getState();
    expect(state.capabilities?.tier).toBe("ZERO");
    expect(state.loading).toBe(false);
    expect(state.error).toBeNull();
  });

  it("rejects malformed response (missing tier field)", async () => {
    // Regression: when the Vite dev proxy doesn't route /capabilities to the
    // backend, the SPA fallback can return index.html, or a partial fixture
    // can omit fields. The store must NOT hydrate garbage shapes — it should
    // surface a visible error so downstream consumers (TierBadge, Gated)
    // don't crash on undefined nested fields.
    server.use(
      http.get("http://localhost/capabilities", () => HttpResponse.json({ foo: "bar" })),
    );

    await useCapabilities.getState().fetch();

    const state = useCapabilities.getState();
    expect(state.capabilities).toBeNull();
    expect(state.loading).toBe(false);
    expect(state.error).toBeTruthy();
    expect(state.error).toMatch(/Invalid capabilities response/i);
  });
});
