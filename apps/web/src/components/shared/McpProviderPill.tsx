import { cn } from "@/lib/utils";

export type McpHealth = "healthy" | "degraded" | "down" | "unchecked";
export type McpTransport = "stdio" | "SSE" | "WS";

export interface McpProviderPillProps {
  provider: {
    name: string;
    health: McpHealth;
    transport: McpTransport;
  };
  className?: string;
}

const HEALTH_DOT: Record<McpHealth, string> = {
  healthy: "bg-accent",
  degraded: "bg-amber",
  down: "bg-red",
  unchecked: "bg-fg-4",
};

/**
 * Compact pill displaying an MCP provider name, health dot and transport
 * label (UI_SPEC § 4.13). Used in the step editor, Integrations cards and
 * GenerateModal step 3.
 */
export function McpProviderPill({
  provider,
  className,
}: McpProviderPillProps): React.ReactElement {
  return (
    <span
      data-testid="mcp-provider-pill"
      data-health={provider.health}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border border-border bg-bg-elev-1 px-2 py-0.5 text-[12px]",
        className,
      )}
    >
      <span
        data-testid="mcp-provider-pill-dot"
        aria-hidden="true"
        title={provider.health}
        className={cn("inline-block h-1.5 w-1.5 shrink-0 rounded-full", HEALTH_DOT[provider.health])}
      />
      <span className="text-fg-1">{provider.name}</span>
      <span className="font-mono text-[11px] text-fg-4">{provider.transport}</span>
    </span>
  );
}
