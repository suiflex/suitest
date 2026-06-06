import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  fetchMcpProviders,
  fetchMcpRouting,
  updateMcpRouting,
  type McpRoutingOverrides,
} from "@/lib/api-client";

interface RoutingEditorProps {
  onClose: () => void;
}

interface RowState {
  targetKind: string;
  override: boolean;
  primary: string;
  fallback: string;
}

const NONE = "__none__";

/**
 * Workspace routing override editor (M2-9). Each `target_kind` shows its
 * effective provider; toggling "override" pins a custom primary (+ optional
 * fallback) stored in `workspace_capabilities.features_json.routing_overrides`
 * — the map the runner consumes. Toggling off restores the bundled default.
 */
export function RoutingEditor({ onClose }: RoutingEditorProps): React.ReactElement {
  const qc = useQueryClient();
  const routing = useQuery({ queryKey: ["mcp-routing"] as const, queryFn: fetchMcpRouting });
  const providers = useQuery({
    queryKey: ["mcp-providers"] as const,
    queryFn: fetchMcpProviders,
  });
  const [rows, setRows] = useState<RowState[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (routing.data) {
      setRows(
        routing.data.map((r) => ({
          targetKind: r.targetKind,
          override: r.isOverride,
          primary: r.primary,
          fallback: r.fallback ?? "",
        })),
      );
    }
  }, [routing.data]);

  const providerNames = (providers.data ?? []).map((p) => p.name);

  const save = useMutation({
    mutationFn: () => {
      const overrides: McpRoutingOverrides = {};
      for (const row of rows) {
        if (row.override && row.primary) {
          overrides[row.targetKind] = {
            primary: row.primary,
            fallback: row.fallback === "" ? null : row.fallback,
          };
        }
      }
      return updateMcpRouting(overrides);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["mcp-routing"] });
      onClose();
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : "Failed to save routing");
    },
  });

  function patchRow(kind: string, patch: Partial<RowState>): void {
    setRows((prev) => prev.map((r) => (r.targetKind === kind ? { ...r, ...patch } : r)));
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent
        data-testid="routing-editor"
        className="border border-border bg-bg-elev-1 sm:max-w-2xl"
      >
        <DialogHeader>
          <DialogTitle className="text-fg-1">MCP Routing</DialogTitle>
          <DialogDescription className="text-fg-3">
            Override which MCP provider services each target kind. Off = bundled default.
          </DialogDescription>
        </DialogHeader>

        {routing.isLoading ? (
          <div className="text-[12px] text-fg-4">Loading routing…</div>
        ) : (
          <div className="flex flex-col gap-2" data-testid="routing-rows">
            {rows.map((row) => (
              <div
                key={row.targetKind}
                className="flex items-center gap-2 rounded-md border border-border bg-bg-elev-2 p-2"
                data-testid={`routing-row-${row.targetKind}`}
              >
                <label className="flex w-40 items-center gap-2">
                  <input
                    type="checkbox"
                    data-testid={`routing-toggle-${row.targetKind}`}
                    checked={row.override}
                    onChange={(e) => {
                      patchRow(row.targetKind, { override: e.target.checked });
                    }}
                  />
                  <span className="font-mono text-[11px] text-fg-1">{row.targetKind}</span>
                </label>
                <select
                  data-testid={`routing-primary-${row.targetKind}`}
                  className="h-8 flex-1 rounded-md border border-border bg-bg-elev-1 px-2 text-[12px] text-fg-1 disabled:opacity-40"
                  disabled={!row.override}
                  value={row.primary}
                  onChange={(e) => {
                    patchRow(row.targetKind, { primary: e.target.value });
                  }}
                >
                  {providerNames.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
                <select
                  data-testid={`routing-fallback-${row.targetKind}`}
                  className="h-8 flex-1 rounded-md border border-border bg-bg-elev-1 px-2 text-[12px] text-fg-3 disabled:opacity-40"
                  disabled={!row.override}
                  value={row.fallback === "" ? NONE : row.fallback}
                  onChange={(e) => {
                    patchRow(row.targetKind, {
                      fallback: e.target.value === NONE ? "" : e.target.value,
                    });
                  }}
                >
                  <option value={NONE}>no fallback</option>
                  {providerNames.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </div>
            ))}
          </div>
        )}

        {error ? (
          <p className="text-[12px] text-red" data-testid="routing-error">
            {error}
          </p>
        ) : null}

        <DialogFooter>
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            size="sm"
            data-testid="routing-save"
            disabled={save.isPending}
            onClick={() => {
              setError(null);
              save.mutate();
            }}
          >
            {save.isPending ? "Saving…" : "Save routing"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
