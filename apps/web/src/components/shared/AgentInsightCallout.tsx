import { Sparkles } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type AgentConfidence = "High" | "Medium" | "Low";

export interface AgentInsightCalloutProps {
  title: string;
  body: ReactNode;
  confidence?: AgentConfidence;
  className?: string;
}

const CONFIDENCE_CLASSES: Record<AgentConfidence, string> = {
  High: "bg-accent/10 text-accent border-accent/20",
  Medium: "bg-amber/10 text-amber border-amber/20",
  Low: "bg-red/10 text-red border-red/20",
};

/**
 * Violet-tinted card used to surface AI annotations inline with deterministic
 * content (UI_SPEC § 4.8). Caller is responsible for wrapping in `<Gated>`
 * when the surrounding context might be ZERO-tier.
 */
export function AgentInsightCallout({
  title,
  body,
  confidence,
  className,
}: AgentInsightCalloutProps): React.ReactElement {
  return (
    <div
      data-testid="agent-insight"
      className={cn(
        "flex items-start gap-3 rounded-md border border-violet/20 bg-violet/10 p-3",
        className,
      )}
    >
      <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-violet" aria-hidden="true" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-center justify-between gap-2">
          <div className="text-[12.5px] font-semibold text-fg-1">{title}</div>
          {confidence ? (
            <span
              data-testid="agent-insight-confidence"
              className={cn(
                "inline-flex shrink-0 items-center rounded-full border px-1.5 py-0.5 text-[10.5px] font-medium",
                CONFIDENCE_CLASSES[confidence],
              )}
            >
              {confidence}
            </span>
          ) : null}
        </div>
        <div className="text-[12.5px] text-fg-3">{body}</div>
      </div>
    </div>
  );
}
