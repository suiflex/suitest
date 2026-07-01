import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { invokeMcpTool, type McpInvokeResult, type McpProviderTool } from "@/lib/api-client";

interface TryItPanelProps {
  providerId: string;
  tools: McpProviderTool[];
}

/**
 * MCP tool browser "Try it" form (M2-8 / MCP_PLUGINS §11). Pick a tool, supply
 * JSON arguments, invoke ad-hoc, and inspect the result. Backed by the
 * role-gated, audit-logged ``POST /mcp/providers/:id/invoke`` endpoint.
 */
export function TryItPanel({ providerId, tools }: TryItPanelProps): React.ReactElement {
  const [tool, setTool] = useState(tools[0]?.name ?? "");
  const [argsText, setArgsText] = useState("{}");
  const [parseError, setParseError] = useState<string | null>(null);

  const invoke = useMutation({
    mutationFn: (): Promise<McpInvokeResult> => {
      const args = JSON.parse(argsText) as Record<string, unknown>;
      return invokeMcpTool(providerId, { tool, arguments: args });
    },
    onError: (err: unknown) => {
      setParseError(err instanceof Error ? err.message : "Invocation failed");
    },
  });

  if (tools.length === 0) {
    return (
      <p className="text-[12px] text-fg-4" data-testid="tryit-no-tools">
        Discover tools first to use the Try-it form.
      </p>
    );
  }

  const result = invoke.data;

  return (
    <div className="flex flex-col gap-2 border-t border-border pt-3" data-testid="tryit-panel">
      <span className="text-[11px] font-medium text-fg-3">Try a tool</span>
      <div className="flex gap-2">
        <select
          data-testid="tryit-tool"
          className="h-8 flex-1 rounded-md border border-border bg-bg-elev-1 px-2 text-[12px] text-fg-1"
          value={tool}
          onChange={(e) => {
            setTool(e.target.value);
          }}
        >
          {tools.map((t) => (
            <option key={t.name} value={t.name}>
              {t.name}
            </option>
          ))}
        </select>
        <Button
          type="button"
          size="sm"
          data-testid="tryit-invoke"
          disabled={invoke.isPending}
          onClick={() => {
            setParseError(null);
            invoke.mutate();
          }}
        >
          {invoke.isPending ? "Invoking…" : "Invoke"}
        </Button>
      </div>
      <textarea
        data-testid="tryit-args"
        className="rounded-md border border-border bg-bg-elev-1 p-2 font-mono text-[11px] text-fg-1 focus:outline-none focus:ring-1 focus:ring-accent/40"
        rows={3}
        value={argsText}
        onChange={(e) => {
          setArgsText(e.target.value);
        }}
      />
      {parseError ? (
        <p className="text-[12px] text-red" data-testid="tryit-error">
          {parseError}
        </p>
      ) : null}
      {result ? (
        <div data-testid="tryit-result" className="flex flex-col gap-1">
          <span className={`text-[11px] font-medium ${result.ok ? "text-accent" : "text-red"}`}>
            {result.ok ? `OK · ${result.durationMs.toString()}ms` : `Error: ${result.error ?? ""}`}
          </span>
          {result.stdout ? (
            <pre className="max-h-40 overflow-auto rounded-md bg-bg-code p-2 font-mono text-[11px] text-fg-3">
              {result.stdout}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
