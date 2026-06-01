import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { HealthPill, type HealthStatus } from "@/components/mcp/HealthPill";
import { ProviderModal } from "@/components/mcp/ProviderModal";
import { RegisterMcpModal } from "@/components/mcp/RegisterMcpModal";
import { RoutingEditor } from "@/components/mcp/RoutingEditor";
import { Button } from "@/components/ui/button";
import {
  fetchMcpProviders,
  type McpProviderSummary,
} from "@/lib/api-client";
import { useWorkspaceStream } from "@/lib/ws-client";

function coerceHealth(raw: string): HealthStatus {
  if (raw === "ok" || raw === "degraded" || raw === "down") return raw;
  return "unknown";
}

/**
 * Workspace-scoped MCP provider list. The card list reflects
 * ``GET /mcp/providers`` and re-fetches whenever the gateway publishes a
 * ``mcp.provider.health`` event on the active workspace channel.
 */
export function McpServersPanel(): React.ReactElement {
  const { data, refetch, isLoading, isError } = useQuery({
    queryKey: ["mcp-providers"] as const,
    queryFn: fetchMcpProviders,
  });
  const [openId, setOpenId] = useState<string | null>(null);
  const [registerOpen, setRegisterOpen] = useState(false);
  const [routingOpen, setRoutingOpen] = useState(false);

  useWorkspaceStream((e) => {
    if (e.event === "mcp.provider.health") {
      void refetch();
    }
  });

  const providers = data ?? [];

  return (
    <section className="flex flex-col gap-3" data-testid="mcp-servers-panel">
      <header className="flex items-center justify-between">
        <h3 className="text-[13px] font-semibold text-fg-1">MCP Servers</h3>
        <div className="flex items-center gap-3">
          <span className="font-mono text-[10.5px] text-fg-5">
            {providers.length.toString()} provider{providers.length === 1 ? "" : "s"}
          </span>
          <Button
            type="button"
            size="xs"
            variant="ghost"
            data-testid="mcp-routing"
            onClick={() => {
              setRoutingOpen(true);
            }}
          >
            Routing
          </Button>
          <Button
            type="button"
            size="xs"
            variant="outline"
            data-testid="mcp-add-custom"
            onClick={() => {
              setRegisterOpen(true);
            }}
          >
            Add Custom MCP
          </Button>
        </div>
      </header>

      {isLoading ? (
        <div className="text-[12px] text-fg-4" data-testid="mcp-servers-loading">
          Loading providers…
        </div>
      ) : isError ? (
        <div className="text-[12px] text-red" data-testid="mcp-servers-error">
          Failed to load MCP providers.
        </div>
      ) : providers.length === 0 ? (
        <div className="text-[12px] text-fg-4" data-testid="mcp-servers-empty">
          No MCP providers configured.
        </div>
      ) : (
        <ul className="grid grid-cols-1 gap-2" data-testid="mcp-servers-list">
          {providers.map((p) => (
            <ProviderRow
              key={p.id}
              provider={p}
              onSelect={() => {
                setOpenId(p.id);
              }}
            />
          ))}
        </ul>
      )}

      {openId !== null ? (
        <ProviderModal
          id={openId}
          onClose={() => {
            setOpenId(null);
          }}
        />
      ) : null}

      {registerOpen ? (
        <RegisterMcpModal
          onClose={() => {
            setRegisterOpen(false);
          }}
        />
      ) : null}

      {routingOpen ? (
        <RoutingEditor
          onClose={() => {
            setRoutingOpen(false);
          }}
        />
      ) : null}
    </section>
  );
}

function ProviderRow({
  provider,
  onSelect,
}: {
  provider: McpProviderSummary;
  onSelect: () => void;
}): React.ReactElement {
  const status = coerceHealth(provider.healthStatus);
  const toolCount = provider.tools?.length ?? 0;
  return (
    <li>
      <button
        type="button"
        data-testid="mcp-server-row"
        data-provider-id={provider.id}
        onClick={onSelect}
        className="flex w-full items-center gap-3 rounded-md border border-border bg-bg-elev-1 p-3 text-left hover:bg-bg-elev-2"
      >
        <HealthPill status={status} />
        <span className="font-medium text-fg-1">{provider.name}</span>
        <span className="font-mono text-[11px] text-fg-3">{provider.kind}</span>
        <span className="ml-auto font-mono text-[10.5px] text-fg-5">
          {toolCount.toString()} tool{toolCount === 1 ? "" : "s"}
        </span>
      </button>
    </li>
  );
}
