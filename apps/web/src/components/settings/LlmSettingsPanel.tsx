import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  deleteLlmConfig,
  fetchLlmConfig,
  type LlmConfigWriteBody,
  type LlmTestResult,
  putLlmConfig,
  testLlmConfig,
} from "@/lib/api-client";

import { providerLabel, vendorById, vendorForProvider, vendorsInGroup } from "@/lib/llm-vendors";
import { useCapabilities } from "@/stores/use-capabilities";

import { ChatGptSignIn } from "./ChatGptSignIn";
import { GoogleSignIn } from "./GoogleSignIn";

const CUSTOM_VENDOR = "custom";

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

  // The vendor is who the user picks; which provider key gets stored depends on
  // how they authenticate to it (see lib/llm-vendors).
  const [vendorId, setVendorId] = useState("anthropic");
  const [authMethod, setAuthMethod] = useState<"api_key" | "oauth">("api_key");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [testResult, setTestResult] = useState<LlmTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [testingTrigger, setTestingTrigger] = useState<"banner" | "form" | null>(null);

  const vendor = vendorById(vendorId);
  // A vendor with no sign-in has only one way in, so the radio never shows and
  // the choice can never be left pointing at a flow that is not there.
  // A vendor with no key path is always signing in; one with no sign-in never is.
  const signingIn =
    vendor?.oauth !== undefined && (vendor.oauthOnly === true || authMethod === "oauth");

  const body = (): LlmConfigWriteBody => {
    const next: LlmConfigWriteBody = {
      provider: vendor?.apiKeyProvider ?? vendorId,
      model,
      config: vendor?.needsBaseUrl && baseUrl ? { base_url: baseUrl } : {},
    };
    if (apiKey) next.apiKey = apiKey;
    return next;
  };

  const refresh = async (): Promise<void> => {
    await queryClient.invalidateQueries({ queryKey: ["workspace", workspaceId, "llm-config"] });
    // Readiness may have changed — refetch capabilities so gated UI updates.
    await queryClient.invalidateQueries({ queryKey: ["capabilities"] });
    // Immediately sync Zustand capabilities so AI panel, status chips, and gated features update without page refresh
    void useCapabilities.getState().fetch();
  };

  const saveMutation = useMutation({
    mutationFn: () => putLlmConfig(workspaceId, body()),
    onSuccess: () => {
      setError(null);
      setApiKey("");
      setHasUnsavedChanges(false);
      void refresh();
    },
    onError: () => setError("Could not save LLM config. Check the provider and key."),
  });

  const testMutation = useMutation({
    mutationFn: () => testLlmConfig(workspaceId),
    onSuccess: (r) => {
      setTestResult(r);
      if (r.ok) {
        setHasUnsavedChanges(false);
        void refresh();
      }
    },
    onError: () => setError("Connection test failed to run."),
    onSettled: () => setTestingTrigger(null),
  });

  const removeMutation = useMutation({
    mutationFn: () => deleteLlmConfig(workspaceId),
    onSuccess: () => {
      setTestResult(null);
      void refresh();
    },
  });

  const active = configQuery.data;

  // Auto-sync when capabilities change externally (e.g. from topbar status badge)
  const llmStatus = useCapabilities((state) => state.capabilities?.llm?.status);
  useEffect(() => {
    if (llmStatus === "ready") {
      void queryClient.invalidateQueries({ queryKey: ["workspace", workspaceId, "llm-config"] });
    }
  }, [llmStatus, queryClient, workspaceId]);

  // Pre-populate form when active config loads and user hasn't made unsaved edits
  useEffect(() => {
    if (active && !hasUnsavedChanges) {
      const v = vendorForProvider(active.provider);
      if (v) setVendorId(v.id);
      if (active.authMethod === "oauth" || active.authMethod === "api_key") {
        setAuthMethod(active.authMethod);
      }
      setModel(active.model ?? "");
      const base =
        typeof active.config["base_url"] === "string" ? active.config["base_url"] : "";
      setBaseUrl(base);
    }
  }, [active, hasUnsavedChanges]);

  const handleTestOrSaveAndTest = async (trigger: "banner" | "form" = "form"): Promise<void> => {
    setError(null);
    setTestingTrigger(trigger);
    if (!active || hasUnsavedChanges) {
      try {
        await saveMutation.mutateAsync();
        testMutation.mutate();
      } catch {
        // saveMutation.onError displays user-facing error message
        setTestingTrigger(null);
      }
    } else {
      testMutation.mutate();
    }
  };

  return (
    <section className="max-w-xl space-y-5" data-testid="llm-settings-panel">
      <div className="rounded-lg border border-border bg-bg-elev-1 p-5">
        <h2 className="text-[15px] font-semibold text-fg-1">LLM provider</h2>
        <p className="mt-1 text-[12.5px] text-fg-3">
          Bring your own model. Save and validate a provider to unlock MCP execution and AI
          features. Keys are encrypted and never shown again.
        </p>

        <div className="mt-4 text-[13px] text-fg-1" data-testid="llm-current-status">
          {configQuery.isLoading ? (
            <span className="text-fg-3">Loading…</span>
          ) : active ? (
            active.status === "validation_required" ? (
              <div
                className="space-y-3 rounded-md border border-amber/40 bg-amber/10 p-3.5"
                data-testid="llm-validation-warning-banner"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-start gap-2.5">
                    <span className="mt-0.5 text-base leading-none" aria-hidden="true">
                      ⚠️
                    </span>
                    <div className="space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-[13px] font-semibold text-fg-1">
                          Active: <strong>{providerLabel(active.provider)}</strong> / {active.model}
                        </span>
                        <span className="rounded bg-amber/20 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-amber uppercase tracking-wider">
                          validation required
                        </span>
                      </div>
                      <p className="text-[12px] text-fg-2">
                        Configuration is saved, but connection has not been verified yet. AI features (Assistant Chat, AI generator) remain locked until connection succeeds.
                      </p>
                      {active.apiKeyHint ? (
                        <span className="font-mono text-[11px] text-fg-4">{active.apiKeyHint}</span>
                      ) : null}
                      {typeof active.config["base_url"] === "string" && active.config["base_url"] ? (
                        <span className="block truncate font-mono text-[11px] text-fg-4">
                          {active.config["base_url"]}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  {canWrite ? (
                    <button
                      type="button"
                      onClick={() => removeMutation.mutate()}
                      className="shrink-0 text-[12px] text-red hover:underline"
                      data-testid="llm-remove"
                    >
                      Remove
                    </button>
                  ) : null}
                </div>

                {canWrite ? (
                  <div className="flex items-center gap-3 pt-1">
                    <button
                      type="button"
                      onClick={() => void handleTestOrSaveAndTest("banner")}
                      disabled={testMutation.isPending || saveMutation.isPending}
                      className="inline-flex h-8 items-center justify-center gap-1.5 rounded-md bg-amber px-3 text-[12px] font-semibold text-black hover:bg-amber/90 disabled:opacity-60 transition-opacity"
                      data-testid="llm-verify-banner-btn"
                    >
                      {testingTrigger === "banner"
                        ? "Verifying connection…"
                        : "⚡ Verify Connection Now"}
                    </button>
                    <span className="text-[11px] text-fg-3">Runs a quick 1-token roundtrip test</span>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="flex items-center justify-between rounded-md border border-accent/30 bg-accent/10 px-3 py-2">
                <span className="min-w-0">
                  Active: <strong>{providerLabel(active.provider)}</strong> / {active.model}{" "}
                  <span className="text-fg-3">({active.status.replaceAll("_", " ")})</span>
                  {active.apiKeyHint ? (
                    <span className="ml-2 font-mono text-fg-4">{active.apiKeyHint}</span>
                  ) : null}
                  {active.authMethod === "oauth" ? (
                    <span className="ml-2 text-violet" data-testid="llm-oauth-account">
                      signed in{active.oauthAccount ? ` as ${active.oauthAccount}` : ""}
                    </span>
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
            )
          ) : (
            <span className="text-fg-3" data-testid="llm-none">
              No LLM configured. Manual test management remains available.
            </span>
          )}
        </div>
      </div>

      {canWrite ? (
        <div
          className="space-y-4 rounded-lg border border-border bg-bg-elev-1 p-5"
          data-testid="llm-vendor-picker"
        >
          <div className="space-y-2">
            <label htmlFor="llm-provider" className="text-[12.5px] font-medium text-fg-1">
              Provider
            </label>
            <select
              id="llm-provider"
              value={vendorId}
              onChange={(e) => {
                setVendorId(e.target.value);
                setHasUnsavedChanges(true);
                // The new vendor may not offer a sign-in; start from the way in
                // that every vendor has.
                setAuthMethod("api_key");
                setTestResult(null);
              }}
              className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none focus:border-accent"
            >
              <optgroup label="Hosted providers">
                {vendorsInGroup("cloud").map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Self-hosted providers">
                {vendorsInGroup("local").map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Other">
                {vendorsInGroup("other").map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                  </option>
                ))}
              </optgroup>
            </select>
            {vendorId === CUSTOM_VENDOR ? (
              <p className="text-[11.5px] text-fg-4">
                Any OpenAI-compatible endpoint: LLM gateways/routers, LiteLLM proxy, or a hosted
                inference server. Point the base URL at its <code>/v1</code> root.
              </p>
            ) : null}
          </div>

          {vendor?.oauth && !vendor.oauthOnly ? (
            <fieldset className="flex gap-4" data-testid="llm-auth-method">
              <legend className="px-1 text-[12.5px] font-medium text-fg-1">Authentication</legend>
              {(
                [
                  // Reads as an action, and keeps the field below it the only
                  // thing on screen labelled "API key".
                  ["api_key", "Paste a key"],
                  ["oauth", vendor.oauth.label],
                ] as const
              ).map(([value, label]) => (
                <label key={value} className="flex items-center gap-2 text-[13px] text-fg-1">
                  <input
                    type="radio"
                    name="llm-auth-method"
                    value={value}
                    checked={authMethod === value}
                    onChange={() => {
                      setAuthMethod(value);
                      setHasUnsavedChanges(true);
                    }}
                    className="accent-accent"
                  />
                  {label}
                </label>
              ))}
            </fieldset>
          ) : null}
        </div>
      ) : null}

      {canWrite && signingIn && vendor?.oauth?.flow === "chatgpt" ? (
        <ChatGptSignIn workspaceId={workspaceId} onDone={refresh} />
      ) : null}

      {canWrite && signingIn && vendor?.oauth?.flow === "google" ? (
        <GoogleSignIn workspaceId={workspaceId} onDone={refresh} />
      ) : null}

      {canWrite && signingIn && vendor?.oauth?.flow === "antigravity" ? (
        <GoogleSignIn workspaceId={workspaceId} onDone={refresh} variant="antigravity" />
      ) : null}

      {canWrite && !signingIn ? (
        <form
          className="space-y-4 rounded-lg border border-border bg-bg-elev-1 p-5"
          onSubmit={(e) => {
            e.preventDefault();
            saveMutation.mutate();
          }}
        >
          <div className="space-y-2">
            <label htmlFor="llm-model" className="text-[12.5px] font-medium text-fg-1">
              Model
            </label>
            <input
              id="llm-model"
              autoComplete="off"
              value={model}
              onChange={(e) => {
                setModel(e.target.value);
                setHasUnsavedChanges(true);
              }}
              placeholder="claude-sonnet-4-5"
              required
              className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none focus:border-accent"
            />
          </div>

          {vendor?.needsBaseUrl ? (
            <div className="space-y-2">
              <label htmlFor="llm-base-url" className="text-[12.5px] font-medium text-fg-1">
                Base URL
              </label>
              <input
                id="llm-base-url"
                value={baseUrl}
                onChange={(e) => {
                  setBaseUrl(e.target.value);
                  setHasUnsavedChanges(true);
                }}
                placeholder={
                  vendorId === CUSTOM_VENDOR
                    ? "https://your-gateway.example.com/v1"
                    : "http://localhost:11434"
                }
                required={vendorId === CUSTOM_VENDOR}
                className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none focus:border-accent"
              />
            </div>
          ) : null}

          {!vendor?.keyless ? (
            <div className="space-y-2">
              <label htmlFor="llm-api-key" className="text-[12.5px] font-medium text-fg-1">
                API key{vendorId === CUSTOM_VENDOR ? " (optional)" : ""}
              </label>
              <input
                id="llm-api-key"
                type="password"
                value={apiKey}
                onChange={(e) => {
                  setApiKey(e.target.value);
                  setHasUnsavedChanges(true);
                }}
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
            <div
              role="status"
              data-testid="llm-test-result"
              className={`space-y-1 rounded-md border px-3 py-2 text-[12.5px] ${
                testResult.ok
                  ? "border-accent/30 bg-accent/10 text-accent"
                  : "border-red/30 bg-red/10 text-red"
              }`}
            >
              <p>
                {testResult.ok
                  ? `OK — ${testResult.modelEcho} (${testResult.latencyMs}ms)`
                  : `Failed — ${testResult.error?.code ?? "ERROR"}: ${testResult.error?.message ?? ""}`}
              </p>
              {!testResult.ok && testResult.error?.code === "UPSTREAM_DISCONNECTED" ? (
                <p className="text-[11px] text-fg-3">
                  Tip: Upstream connection closed or reset. If using a local LLM or proxy (e.g. port 20128/11434), check that the proxy is healthy and reachable.
                </p>
              ) : null}
            </div>
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
              onClick={() => void handleTestOrSaveAndTest("form")}
              disabled={
                testMutation.isPending ||
                saveMutation.isPending ||
                !model ||
                Boolean(vendor?.needsBaseUrl && !baseUrl)
              }
              className="inline-flex h-9 items-center justify-center rounded-md border border-border px-4 text-[13px] font-medium text-fg-1 hover:bg-bg-elev-2 disabled:opacity-60"
              data-testid="llm-test"
            >
              {testingTrigger === "form" ? "Testing…" : "Test connection"}
            </button>
          </div>
          {!active || hasUnsavedChanges ? (
            <p className="text-[11.5px] text-fg-4">
              {model
                ? "Saves draft before testing connection."
                : "Save before testing."}
            </p>
          ) : null}
        </form>
      ) : null}
    </section>
  );
}
