import { formatCost, formatTokens } from "@/components/shared/cost-format";
import { cn } from "@/lib/utils";

export interface CostChipProps {
  tokens: number;
  cost: number;
  currency?: string;
  provider?: string;
  toolCalls?: number;
  className?: string;
}

/**
 * Mono pill showing token + cost usage (UI_SPEC § 4.15). Caller is
 * responsible for hiding the chip in ZERO tier (e.g. via `<Gated
 * feature="ai_conversation">`); this component does not gate itself so it
 * can be reused in any cost-aware context.
 *
 * Format: `[provider · ]<tokens> tokens · <cost>[ · <toolCalls> tool calls]`.
 */
export function CostChip({
  tokens,
  cost,
  currency = "USD",
  provider,
  toolCalls,
  className,
}: CostChipProps): React.ReactElement {
  const parts: Array<string> = [];
  if (provider) parts.push(provider);
  parts.push(`${formatTokens(tokens)} tokens`);
  parts.push(formatCost(cost, currency));
  if (typeof toolCalls === "number") {
    parts.push(`${toolCalls.toString()} tool call${toolCalls === 1 ? "" : "s"}`);
  }

  return (
    <span
      data-testid="cost-chip"
      className={cn(
        "inline-flex items-center rounded-md border border-border bg-bg-elev-2 px-2 py-0.5 font-mono text-[11px] text-fg-3",
        className,
      )}
    >
      {parts.join(" · ")}
    </span>
  );
}
