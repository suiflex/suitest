import { KeyRound, Layers, Database, Globe, Lock } from "lucide-react";

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { ResolvedVariableItem } from "@/hooks/use-variables";

export interface VariableBadgeProps {
  variableKey?: string;
  name?: string;
  scope?: "workspace" | "suite" | "dataset" | "env" | string;
  value?: string | null;
  isSecret?: boolean;
  description?: string | null;
  allRowValues?: Array<{ rowName: string; value: string }> | undefined;
  resolvedItem?: ResolvedVariableItem;
  className?: string;
}

export function VariableBadge({
  variableKey,
  name,
  scope: propScope,
  value: propValue,
  isSecret: propIsSecret,
  description: propDesc,
  allRowValues,
  resolvedItem,
  className,
}: VariableBadgeProps) {
  const effectiveKey = variableKey ?? name ?? "";
  const scope = resolvedItem?.sourceScope ?? propScope ?? "workspace";
  const isSecret = resolvedItem?.isSecret ?? propIsSecret ?? false;
  const value = resolvedItem?.value ?? propValue;
  const description = resolvedItem?.description ?? propDesc;

  const scopeStyles = {
    dataset: "border-purple-500/30 bg-purple-500/10 text-purple-300 hover:bg-purple-500/20",
    suite: "border-sky-500/30 bg-sky-500/10 text-sky-300 hover:bg-sky-500/20",
    workspace: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20",
    env: "border-amber-500/30 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20",
    unbound: "border-amber-500/40 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20",
  }[scope] || "border-border bg-muted/30 text-muted-foreground";

  const ScopeIcon = {
    dataset: Database,
    suite: Layers,
    workspace: KeyRound,
    env: Globe,
    unbound: Globe,
  }[scope] || KeyRound;

  const scopeLabel = {
    dataset: "Case Dataset Row",
    suite: "Suite Override",
    workspace: "Workspace Default",
    env: "Environment Variable",
    unbound: "Custom / Unbound",
  }[scope] || scope;

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn(
              "inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md font-mono text-xs border transition-colors cursor-pointer select-none",
              scopeStyles,
              className
            )}
          >
            <ScopeIcon className="w-3 h-3 opacity-70" />
            <span>{`{{${effectiveKey}}}`}</span>
            {isSecret && <Lock className="w-2.5 h-2.5 opacity-60 text-amber-400" />}
          </span>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          sideOffset={6}
          className="p-3 max-w-sm rounded-lg shadow-2xl bg-bg-elev-2 border border-border-strong text-fg-1 text-xs z-[100]"
        >
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2 border-b border-border/80 pb-1.5">
              <span className="font-semibold text-fg-1 font-mono text-xs">{`{{${effectiveKey}}}`}</span>
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium uppercase tracking-wider bg-bg-elev-3 text-fg-3 border border-border">
                <ScopeIcon className="w-2.5 h-2.5" />
                {scopeLabel}
              </span>
            </div>
            {description && (
              <p className="text-fg-4 text-[11px] leading-relaxed">{description}</p>
            )}
            <div className="pt-0.5">
              <div className="text-[10px] text-fg-4 uppercase font-medium tracking-wider mb-1">
                Current Value Preview
              </div>
              <div className="font-mono text-xs p-2 rounded bg-bg-code border border-border text-fg-2 break-all select-all">
                {isSecret ? (
                  <span className="tracking-widest text-fg-4 select-none">••••••••</span>
                ) : value !== undefined && value !== null ? (
                  <span>{String(value)}</span>
                ) : scope === "unbound" ? (
                  <span className="italic text-amber-400/90">Undefined (will resolve at runtime if provided)</span>
                ) : (
                  <span className="italic text-fg-5">Not set / resolved at runtime</span>
                )}
              </div>
            </div>

            {/* All Scenarios Preview (for multi-row DDT datasets) */}
            {allRowValues && allRowValues.length > 1 && (
              <div className="pt-2 border-t border-border/70 space-y-1.5">
                <div className="flex items-center justify-between text-[10px] text-fg-4 uppercase font-medium tracking-wider">
                  <span>All Scenarios ({allRowValues.length})</span>
                  <span className="text-[9.5px] text-purple-400 font-mono">DDT Matrix</span>
                </div>
                <div className="space-y-1 max-h-28 overflow-y-auto pr-0.5 font-mono text-[11px]">
                  {allRowValues.map((r, i) => (
                    <div
                      key={i}
                      className={cn(
                        "flex items-center justify-between gap-2 px-1.5 py-1 rounded border",
                        r.value === value
                          ? "bg-purple-500/15 border-purple-500/40 text-purple-200 font-semibold"
                          : "bg-bg-code/60 border-border/40 text-fg-3",
                      )}
                    >
                      <span className="text-fg-4 truncate max-w-[120px] text-[10.5px]">
                        {r.rowName}:
                      </span>
                      <span className="truncate select-all">
                        {isSecret ? (
                          <span className="tracking-widest text-fg-4 select-none">••••••••</span>
                        ) : r.value ? (
                          r.value
                        ) : (
                          <span className="italic text-fg-5 font-normal">(empty)</span>
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
