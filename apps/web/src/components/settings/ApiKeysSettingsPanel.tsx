import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, KeyRound, Loader2 } from "lucide-react";
import { type FormEvent, useState } from "react";

import { API_KEYS_QUERY_KEY, ApiKeysPanel } from "@/components/mcp/ApiKeysPanel";
import { CopyButton } from "@/components/shared/CopyButton";
import { Button } from "@/components/ui/button";
import { type ApiKeyCreated, createApiKey } from "@/lib/api-client";

/**
 * Dedicated API-keys management for a workspace (Settings → API Keys).
 *
 * Keys are scoped to THIS workspace and let an AI IDE / SDK / CI reach it over
 * MCP. The plaintext token is shown once at creation; the list below persists
 * (name, prefix, usage) and survives refresh — revoke removes a key.
 */
export function ApiKeysSettingsPanel({ canWrite }: { canWrite: boolean }): React.ReactElement {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = (event: FormEvent<HTMLFormElement>): void => {
    event.preventDefault();
    const trimmed = name.trim();
    if (trimmed.length === 0) {
      setError("Give the key a name so you can recognise it later.");
      return;
    }
    setCreating(true);
    setError(null);
    setCreated(null);
    void createApiKey(trimmed)
      .then((key) => {
        setCreated(key);
        setName("");
        void queryClient.invalidateQueries({ queryKey: API_KEYS_QUERY_KEY });
      })
      .catch(() => {
        setError("Couldn't create a key. Admin access to this workspace is required.");
      })
      .finally(() => {
        setCreating(false);
      });
  };

  return (
    <div className="space-y-6">
      <section className="space-y-4 rounded-lg border border-border bg-bg-elev-1 p-5">
        <div className="space-y-1">
          <h2 className="text-[15px] font-semibold text-fg-1">API keys</h2>
          <p className="text-[12.5px] text-fg-3">
            Scoped to this workspace. Used by AI IDEs, the SDK, and CI to reach Suitest over MCP. A
            key only ever unlocks this workspace.
          </p>
        </div>

        {canWrite ? (
          <form onSubmit={onSubmit} className="flex items-end gap-2">
            <div className="flex flex-1 flex-col gap-1.5">
              <label htmlFor="api-key-name" className="text-[12px] font-medium text-fg-2">
                Key name
              </label>
              <input
                id="api-key-name"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                }}
                placeholder="e.g. maya-laptop, ci-pipeline"
                maxLength={120}
                className="h-9 w-full rounded-md border border-border bg-bg-base px-3 text-[13px] text-fg-1 outline-none focus:border-accent"
                data-testid="api-key-name-input"
              />
            </div>
            <Button
              type="submit"
              variant="default"
              disabled={creating}
              data-testid="create-api-key-settings"
            >
              {creating ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              ) : (
                <KeyRound className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              Create key
            </Button>
          </form>
        ) : (
          <p className="text-[12px] text-fg-4">Only workspace admins can create or revoke keys.</p>
        )}

        {error ? (
          <p
            role="alert"
            className="rounded-md border border-red/30 bg-red/10 px-3 py-2 text-[12.5px] text-red"
          >
            {error}
          </p>
        ) : null}

        {created ? (
          <div
            className="space-y-2 rounded-md border border-accent/30 bg-accent/[0.06] p-3"
            data-testid="api-key-created"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-[12px] font-medium text-fg-1">
                Key “{created.name}” created
              </span>
              <CopyButton value={created.key} label="Copy API key" />
            </div>
            <code className="block overflow-x-auto rounded bg-bg-code px-2 py-1.5 font-mono text-[11.5px] text-fg-1">
              {created.key}
            </code>
            <div className="flex items-center justify-between gap-2">
              <p className="flex items-start gap-1.5 text-[11.5px] text-amber">
                <AlertTriangle className="mt-[1px] h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                Copy it now — shown once, can&apos;t be retrieved again.
              </p>
              <Button
                type="button"
                size="xs"
                variant="secondary"
                onClick={() => {
                  setCreated(null);
                }}
                data-testid="api-key-dismiss"
              >
                <Check className="h-3 w-3" aria-hidden="true" />
                Done
              </Button>
            </div>
          </div>
        ) : null}
      </section>

      {canWrite ? (
        <section className="space-y-3">
          <h3 className="text-[13px] font-semibold text-fg-1">Active keys</h3>
          <ApiKeysPanel />
        </section>
      ) : null}
    </div>
  );
}
