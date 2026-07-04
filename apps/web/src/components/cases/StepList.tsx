import { Sparkles } from "lucide-react";

import { StatusBadge } from "@/components/shared/StatusBadge";
import type { components } from "@/lib/api-types";
import { outcomeToBadge } from "@/lib/badge-maps";
import type { DerivedStep, StepType } from "@/lib/test-case-format";
import { stepTypeLabel } from "@/lib/test-case-format";
import { cn } from "@/lib/utils";

type StepOutcome = components["schemas"]["StepOutcome"];

const TYPE_BADGE: Record<StepType, string> = {
  navigation: "bg-blue/10 text-blue border-blue/20",
  action: "bg-bg-elev-2 text-fg-3 border-border",
  assertion: "bg-accent/10 text-accent border-accent/20",
  wait: "bg-amber/10 text-amber border-amber/20",
  api: "bg-violet/10 text-violet border-violet/20",
};

export interface StepListProps {
  steps: DerivedStep[];
  /** True when the steps were synthesised because the case had none. */
  isFallback?: boolean;
  /** Per-step run outcome, keyed by 1-based step order (from the last run). */
  outcomeByOrder?: Map<number, StepOutcome>;
  /** Per-step cumulative start offset in ms, keyed by 1-based order. */
  offsetByOrder?: Map<number, number>;
  selectedOrder?: number | null;
  onSelectStep?: (order: number) => void;
}

/** mm:ss.d label for a step's start offset in the evidence timeline. */
function formatOffset(ms: number): string {
  const totalSec = ms / 1000;
  const m = Math.floor(totalSec / 60);
  const s = Math.floor(totalSec % 60);
  const d = Math.floor((totalSec % 1) * 10);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}.${d.toString()}`;
}

/**
 * QA-readable list of a case's steps. Each step shows a type badge, the
 * instruction, the expected result, and (when a run exists) its outcome. Never
 * renders a bare TC id or an empty step — the parent guarantees a non-empty
 * list (real or fallback).
 */
export function StepList({
  steps,
  isFallback = false,
  outcomeByOrder,
  offsetByOrder,
  selectedOrder,
  onSelectStep,
}: StepListProps): React.ReactElement {
  return (
    <div className="flex flex-col gap-2" data-testid="case-step-list">
      {isFallback ? (
        <div
          className="flex items-center gap-2 rounded-md border border-amber/20 bg-amber/[0.06] px-3 py-2 text-[11.5px] text-amber"
          data-testid="step-fallback-note"
        >
          <Sparkles className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          Generated fallback steps — real MCP steps are not available for this case yet.
        </div>
      ) : null}

      <ol className="flex flex-col gap-2">
        {steps.map((step) => {
          const outcome = outcomeByOrder?.get(step.order);
          const offset = offsetByOrder?.get(step.order);
          const selectable = Boolean(onSelectStep);
          const selected = selectedOrder === step.order;
          return (
            <li key={step.id}>
              <button
                type="button"
                data-testid="case-step"
                data-step-order={step.order}
                data-step-type={step.type}
                data-selected={selected ? "true" : undefined}
                disabled={!selectable}
                onClick={selectable ? () => onSelectStep?.(step.order) : undefined}
                className={cn(
                  "w-full rounded-md border border-border bg-bg-elev-1 p-3 text-left",
                  selectable && "transition-colors hover:bg-bg-elev-2",
                  selected && "border-accent/40 bg-accent/[0.06]",
                  !selectable && "cursor-default",
                )}
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[11px] text-fg-4">Step {step.order}</span>
                  {offset !== undefined ? (
                    <span
                      className="font-mono text-[10.5px] text-fg-5 tabular-nums"
                      data-testid="case-step-offset"
                    >
                      {formatOffset(offset)}
                    </span>
                  ) : null}
                  <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-fg-1">
                    {step.title}
                  </span>
                  <span
                    className={cn(
                      "shrink-0 rounded-full border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide",
                      TYPE_BADGE[step.type],
                    )}
                    data-testid="case-step-type"
                  >
                    {stepTypeLabel(step.type)}
                  </span>
                  {outcome ? (
                    <StatusBadge status={outcomeToBadge(outcome)} label={outcome} />
                  ) : null}
                </div>

                <dl className="mt-2 grid grid-cols-1 gap-1.5 text-[12px] sm:grid-cols-[84px_1fr]">
                  <dt className="text-[10.5px] uppercase tracking-wide text-fg-5">Instruction</dt>
                  <dd className="text-fg-2">{step.instruction}</dd>
                  <dt className="text-[10.5px] uppercase tracking-wide text-fg-5">Expected</dt>
                  <dd className="text-fg-3">{step.expected}</dd>
                </dl>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
