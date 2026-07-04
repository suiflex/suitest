import { StatusBadge } from "@/components/shared/StatusBadge";
import type { components } from "@/lib/api-types";
import { outcomeToBadge } from "@/lib/badge-maps";
import { formatDuration } from "@/lib/test-case-format";
import { cn } from "@/lib/utils";

import { stepTitle, stepTypeLabel } from "./case-grouping";

type RunStepPublic = components["schemas"]["RunStepPublic"];
type StepOutcome = components["schemas"]["StepOutcome"];

interface StepTableProps {
  steps: RunStepPublic[];
  /** id of the currently-previewed step (its screenshot is shown on the right). */
  selectedStepId?: string | null;
  /** Click a row to preview that step's screenshot ("Preview: Step N"). */
  onSelectStep?: (stepId: string) => void;
}

function outcomeLabel(outcome: StepOutcome): string {
  switch (outcome) {
    case "PASS":
      return "PASS";
    case "FAIL":
      return "FAIL";
    case "SKIP":
      return "SKIP";
    case "ERROR":
      return "ERROR";
    default:
      return "PENDING";
  }
}

export function StepTable({
  steps,
  selectedStepId,
  onSelectStep,
}: StepTableProps): React.ReactElement {
  if (steps.length === 0) {
    return (
      <div
        className="rounded-md border border-border bg-bg-elev-1 p-3 text-[12px] text-fg-4"
        data-testid="step-table-empty"
      >
        No steps recorded yet.
      </div>
    );
  }
  return (
    <div className="rounded-md border border-border bg-bg-elev-1" data-testid="step-table">
      <table className="w-full text-[12px]">
        <thead className="text-fg-5">
          <tr className="border-b border-border">
            <th className="px-3 py-2 text-left font-mono text-[10.5px] uppercase tracking-wide">
              #
            </th>
            <th className="px-3 py-2 text-left font-mono text-[10.5px] uppercase tracking-wide">
              Step
            </th>
            <th className="px-3 py-2 text-left font-mono text-[10.5px] uppercase tracking-wide">
              Outcome
            </th>
            <th className="px-3 py-2 text-right font-mono text-[10.5px] uppercase tracking-wide">
              Duration
            </th>
          </tr>
        </thead>
        <tbody>
          {steps.map((s) => (
            <tr
              key={s.id}
              className={cn(
                "border-b border-border align-top transition-colors last:border-b-0",
                onSelectStep && "cursor-pointer hover:bg-bg-elev-2",
                selectedStepId === s.id && "bg-accent/[0.08]",
              )}
              data-testid="step-row"
              data-outcome={s.outcome}
              data-selected={selectedStepId === s.id ? "true" : undefined}
              onClick={onSelectStep ? () => onSelectStep(s.id) : undefined}
            >
              <td className="px-3 py-2 font-mono text-[11px] text-fg-4">{s.step_order}</td>
              <td className="px-3 py-2">
                <div className="flex flex-col gap-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[12px] text-fg-2" data-testid="step-title">
                      {stepTitle(s)}
                    </span>
                    <span
                      className="shrink-0 rounded bg-bg-elev-2 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide text-fg-4"
                      data-testid="step-type-badge"
                    >
                      {stepTypeLabel(s.type)}
                    </span>
                  </div>
                  {s.error_message ? (
                    <pre
                      className="overflow-x-auto rounded-md bg-bg-code p-2 font-mono text-[11px] text-red"
                      data-testid="step-error-message"
                    >
                      {s.error_message}
                    </pre>
                  ) : null}
                </div>
              </td>
              <td className="px-3 py-2">
                <StatusBadge status={outcomeToBadge(s.outcome)} label={outcomeLabel(s.outcome)} />
              </td>
              <td className="px-3 py-2 text-right font-mono text-[11px] text-fg-4 tabular-nums">
                {formatDuration(s.duration_ms)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
