import { useQuery } from "@tanstack/react-query";

import { HealthPill } from "@/components/mcp/HealthPill";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { fetchMcpProvider, type McpProviderTool } from "@/lib/api-client";

interface ProviderModalProps {
  id: string;
  onClose: () => void;
}

/**
 * Read-only modal listing the tools discovered on the MCP server. The
 * "try it" form lands in M2 — until then we render name + description +
 * a compact preview of the argument schema (top-level keys).
 */
export function ProviderModal({ id, onClose }: ProviderModalProps): React.ReactElement {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["mcp-provider", id] as const,
    queryFn: () => fetchMcpProvider(id),
  });

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
    <ul className="flex max-h-[420px] flex-col gap-2 overflow-auto" data-testid="provider-tool-list">
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
          {t.description ? (
            <p className="mt-1 text-[12px] text-fg-3">{t.description}</p>
          ) : null}
          {t.argSchema && Object.keys(t.argSchema).length > 0 ? (
            <pre
              className="mt-2 overflow-x-auto rounded-md bg-[#060606] p-2 font-mono text-[11px] text-fg-3"
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
