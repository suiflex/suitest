import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { HealthPill } from "@/components/mcp/HealthPill";
import { RegisterMcpModal } from "@/components/mcp/RegisterMcpModal";
import { TryItPanel } from "@/components/mcp/TryItPanel";
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
  deleteMcpProvider,
  discoverMcpProviderTools,
  fetchMcpProvider,
  type McpProviderTool,
} from "@/lib/api-client";

interface ProviderModalProps {
  id: string;
  onClose: () => void;
}

/**
 * Provider detail — lists discovered tools (M1c) plus the M2-6 edit / delete
 * actions for custom (non-bundled) providers. Bundled builtins are read-only,
 * so the action footer is hidden for them.
 */
export function ProviderModal({ id, onClose }: ProviderModalProps): React.ReactElement {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["mcp-provider", id] as const,
    queryFn: () => fetchMcpProvider(id),
  });

  const remove = useMutation({
    mutationFn: () => deleteMcpProvider(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["mcp-providers"] });
      onClose();
    },
  });

  const rediscover = useMutation({
    mutationFn: () => discoverMcpProviderTools(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["mcp-provider", id] });
      void qc.invalidateQueries({ queryKey: ["mcp-providers"] });
    },
  });

  const canManage = data !== undefined && !data.isBundled;

  if (editing && data) {
    return (
      <RegisterMcpModal
        existing={data}
        onClose={() => {
          setEditing(false);
          onClose();
        }}
      />
    );
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent
        data-testid="provider-modal"
        className="border border-border bg-bg-elev-1 sm:max-w-2xl"
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-fg-1">
            {data ? data.name : "MCP Provider"}
            {data ? <HealthPill status={data.healthStatus} /> : null}
          </DialogTitle>
          <DialogDescription className="text-fg-3">
            {data
              ? `${data.kind} target · ${data.transport} transport`
              : "Loading provider details…"}
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="text-[12px] text-fg-4" data-testid="provider-modal-loading">
            Loading tools…
          </div>
        ) : isError || !data ? (
          <div className="text-[12px] text-red" data-testid="provider-modal-error">
            Failed to load provider details.
          </div>
        ) : (
          <ToolList tools={data.tools} />
        )}

        {canManage && data ? <TryItPanel providerId={data.id} tools={data.tools} /> : null}

        {canManage ? (
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              data-testid="provider-rediscover"
              disabled={rediscover.isPending}
              onClick={() => {
                rediscover.mutate();
              }}
            >
              {rediscover.isPending ? "Discovering…" : "Re-discover"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              data-testid="provider-edit"
              onClick={() => {
                setEditing(true);
              }}
            >
              Edit
            </Button>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              data-testid="provider-delete"
              disabled={remove.isPending}
              onClick={() => {
                remove.mutate();
              }}
            >
              {remove.isPending ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function ToolList({ tools }: { tools: McpProviderTool[] }): React.ReactElement {
  if (tools.length === 0) {
    return (
      <div className="text-[12px] text-fg-4" data-testid="provider-modal-empty">
        No tools discovered on this provider yet.
      </div>
    );
  }
  return (
    <ul
      className="flex max-h-[420px] flex-col gap-2 overflow-auto"
      data-testid="provider-tool-list"
    >
      {tools.map((t) => (
        <li
          key={t.name}
          className="rounded-md border border-border bg-bg-elev-2 p-3"
          data-testid="provider-tool"
        >
          <div className="flex items-center justify-between">
            <span className="font-mono text-[12px] text-fg-1">{t.name}</span>
            <span className="font-mono text-[10.5px] text-fg-5">
              {t.argSchema ? `${Object.keys(t.argSchema).length.toString()} args` : "no args"}
            </span>
          </div>
          {t.description ? <p className="mt-1 text-[12px] text-fg-3">{t.description}</p> : null}
          {t.argSchema && Object.keys(t.argSchema).length > 0 ? (
            <pre
              className="mt-2 overflow-x-auto rounded-md bg-bg-code p-2 font-mono text-[11px] text-fg-3"
              data-testid="provider-tool-schema"
            >
              {Object.keys(t.argSchema).join(", ")}
            </pre>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
