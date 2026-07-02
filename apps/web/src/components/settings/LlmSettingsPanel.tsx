import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  deleteLlmConfig,
  fetchLlmConfig,
  type LlmConfigWriteBody,
  type LlmTestResult,
  putLlmConfig,
  testLlmConfig,
} from "@/lib/api-client";

/** Providers offered in the picker, grouped by tier (label only — backend validates). */
const CLOUD_PROVIDERS = [
  "anthropic",
  "openai",
  "gemini",
  "groq",
  "openrouter",
  "deepseek",
] as const;
const LOCAL_PROVIDERS = ["ollama", "llamacpp", "vllm", "lmstudio"] as const;

/** Any hosted OpenAI-compatible endpoint (gateway / router / LiteLLM proxy). */
const CUSTOM_PROVIDER = "custom";

/** LOCAL providers require a base URL instead of an API key. */
function isLocal(provider: string): boolean {
  return (LOCAL_PROVIDERS as readonly string[]).includes(provider);
}

/** Providers that talk to a user-supplied endpoint, so the form shows Base URL. */
function needsBaseUrl(provider: string): boolean {
  return isLocal(provider) || provider === CUSTOM_PROVIDER;
}

interface LlmSettingsPanelProps {
  workspaceId: string;
  /** ADMIN+ may write; others see read-only status. */
  canWrite: boolean;
}

export function LlmSettingsPanel({
  workspaceId,
  canWrite,
}: LlmSettingsPanelProps): React.ReactElement {
  const queryClient = useQueryClient();
  const configQuery = useQuery({
    queryKey: ["workspace", workspaceId, "llm-config"],
    queryFn: () => fetchLlmConfig(workspaceId),
  });

  const [provider, setProvider] = useState("anthropic");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [testResult, setTestResult] = useState<LlmTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const body = (): LlmConfigWriteBody => {
    const next: LlmConfigWriteBody = {
      provider,
      model,
      config: needsBaseUrl(provider) && baseUrl ? { base_url: baseUrl } : {},
    };
    if (apiKey) next.apiKey = apiKey;
    return next;
  };

  const refresh = (): void => {
    void queryClient.invalidateQueries({ queryKey: ["workspace", workspaceId, "llm-config"] });
    // Tier may have flipped — refetch capabilities so gated UI updates (M3-3).
    void queryClient.invalidateQueries({ queryKey: ["capabilities"] });
  };

  const saveMutation = useMutation({
    mutationFn: () => putLlmConfig(workspaceId, body()),
    onSuccess: () => {
      setError(null);
      setApiKey("");
      refresh();
    },
    onError: () => setError("Could not save LLM config. Check the provider and key."),
  });

  const testMutation = useMutation({
    mutationFn: () => testLlmConfig(workspaceId, body()),
    onSuccess: (r) => setTestResult(r),
    onError: () => setError("Connection test failed to run."),
  });

  const removeMutation = useMutation({
    mutationFn: () => deleteLlmConfig(workspaceId),
    onSuccess: () => {
      setTestResult(null);
      refresh();
    },
  });

  const active = configQuery.data;

  return (
    <section className="max-w-xl space-y-5" data-testid="llm-settings-panel">
      <div className="rounded-lg border border-border bg-bg-elev-1 p-5">
        <h2 className="text-[15px] font-semibold text-fg-1">LLM provider</h2>
        <p className="mt-1 text-[12.5px] text-fg-3">
          Bring your own model. Setting a provider upgrades this workspace from ZERO to CLOUD/LOCAL
          and unlocks AI features. Keys are encrypted and never shown again.
        </p>

        <div className="mt-4 text-[13px] text-fg-1" data-testid="llm-current-status">
          {configQuery.isLoading ? (
            <span className="text-fg-3">Loading…</span>
          ) : active ? (
            <div className="flex items-center justify-between rounded-md border border-accent/30 bg-accent/10 px-3 py-2">
              <span className="min-w-0">
                Active: <strong>{active.provider}</strong> / {active.model}{" "}
                <span className="text-fg-3">({active.tier})</span>
                {active.apiKeyHint ? (
                  <span className="ml-2 font-mono text-fg-4">{active.apiKeyHint}</span>
                ) : null}
                {typeof active.config["base_url"] === "string" && active.config["base_url"] ? (
                  <span className="mt-0.5 block truncate font-mono text-[11px] text-fg-4">
                    {active.config["base_url"]}
                  </span>
                ) : null}
              </span>
              {canWrite ? (
                <button
                  type="button"
                  onClick={() => removeMutation.mutate()}
                  className="text-[12.5px] text-red hover:underline"
                  data-testid="llm-remove"
                >
                  Remove
                </button>
              ) : null}
            </div>
          ) : (
            <span className="text-fg-3" data-testid="llm-none">
              No LLM configured — workspace is in ZERO tier.
            </span>
          )}
        </div>
      </div>

      {canWrite ? (
        <form
          className="space-y-4 rounded-lg border border-border bg-bg-elev-1 p-5"
          onSubmit={(e) => {
            e.preventDefault();
            saveMutation.mutate();
          }}
        >
          <div className="space-y-2">
            <label htmlFor="llm-provider" className="text-[12.5px] font-medium text-fg-1">
              Provider
            </label>
            <select
              id="llm-provider"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none focus:border-accent"
            >
              <optgroup label="Cloud">
                {CLOUD_PROVIDERS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Local">
                {LOCAL_PROVIDERS.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Other">
                <option value={CUSTOM_PROVIDER}>custom (OpenAI-compatible URL)</option>
              </optgroup>
            </select>
            {provider === CUSTOM_PROVIDER ? (
              <p className="text-[11.5px] text-fg-4">
                Any OpenAI-compatible endpoint: LLM gateways/routers, LiteLLM proxy, or a hosted
                inference server. Point the base URL at its <code>/v1</code> root.
              </p>
            ) : null}
          </div>

          <div className="space-y-2">
            <label htmlFor="llm-model" className="text-[12.5px] font-medium text-fg-1">
              Model
            </label>
            <input
              id="llm-model"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="claude-sonnet-4-5"
              required
              className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none focus:border-accent"
            />
          </div>

          {needsBaseUrl(provider) ? (
            <div className="space-y-2">
              <label htmlFor="llm-base-url" className="text-[12.5px] font-medium text-fg-1">
                Base URL
              </label>
              <input
                id="llm-base-url"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder={
                  provider === CUSTOM_PROVIDER
                    ? "https://your-gateway.example.com/v1"
                    : "http://localhost:11434"
                }
                required={provider === CUSTOM_PROVIDER}
                className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none focus:border-accent"
              />
            </div>
          ) : null}

          {!isLocal(provider) ? (
            <div className="space-y-2">
              <label htmlFor="llm-api-key" className="text-[12.5px] font-medium text-fg-1">
                API key{provider === CUSTOM_PROVIDER ? " (optional)" : ""}
              </label>
              <input
                id="llm-api-key"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={active ? "•••••••• (rotate)" : "sk-…"}
                autoComplete="off"
                className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none focus:border-accent"
              />
            </div>
          ) : null}

          {error ? (
            <p
              role="alert"
              className="rounded-md border border-red/30 bg-red/10 px-3 py-2 text-[12.5px] text-red"
            >
              {error}
            </p>
          ) : null}

          {testResult ? (
            <p
              role="status"
              data-testid="llm-test-result"
              className={`rounded-md border px-3 py-2 text-[12.5px] ${
                testResult.ok
                  ? "border-accent/30 bg-accent/10 text-accent"
                  : "border-red/30 bg-red/10 text-red"
              }`}
            >
              {testResult.ok
                ? `OK — ${testResult.modelEcho} (${testResult.latencyMs}ms)`
                : `Failed — ${testResult.error?.code ?? "ERROR"}: ${testResult.error?.message ?? ""}`}
            </p>
          ) : null}

          <div className="flex gap-2">
            <button
              type="submit"
              disabled={saveMutation.isPending || !model}
              className="inline-flex h-9 items-center justify-center rounded-md bg-accent px-4 text-[13px] font-medium text-accent-fg hover:opacity-90 disabled:opacity-60"
              data-testid="llm-save"
            >
              {saveMutation.isPending ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              onClick={() => testMutation.mutate()}
              disabled={testMutation.isPending || !model}
              className="inline-flex h-9 items-center justify-center rounded-md border border-border px-4 text-[13px] font-medium text-fg-1 hover:bg-bg-elev-2 disabled:opacity-60"
              data-testid="llm-test"
            >
              {testMutation.isPending ? "Testing…" : "Test connection"}
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
