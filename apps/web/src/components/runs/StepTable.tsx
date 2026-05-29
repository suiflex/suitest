import { StatusBadge, type StatusBadgeStatus } from "@/components/shared/StatusBadge";
import type { components } from "@/lib/api-types";

type RunStepPublic = components["schemas"]["RunStepPublic"];
type StepOutcome = components["schemas"]["StepOutcome"];

interface StepTableProps {
  steps: RunStepPublic[];
}

const OUTCOME_TO_BADGE: Record<StepOutcome, StatusBadgeStatus> = {
  PASS: "pass",
  FAIL: "fail",
  ERROR: "fail",
  SKIP: "warn",
  PENDING: "neutral",
};

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

function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms.toString()}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m.toString()}m ${Math.round(s % 60).toString()}s`;
}

export function StepTable({ steps }: StepTableProps): React.ReactElement {
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
    <div
      className="rounded-md border border-border bg-bg-elev-1"
      data-testid="step-table"
    >
      <table className="w-full text-[12px]">
        <thead className="text-fg-5">
          <tr className="border-b border-border">
            <th className="px-3 py-2 text-left font-mono text-[10.5px] uppercase tracking-wide">#</th>
            <th className="px-3 py-2 text-left font-mono text-[10.5px] uppercase tracking-wide">Case</th>
            <th className="px-3 py-2 text-left font-mono text-[10.5px] uppercase tracking-wide">Outcome</th>
            <th className="px-3 py-2 text-right font-mono text-[10.5px] uppercase tracking-wide">Duration</th>
          </tr>
        </thead>
        <tbody>
          {steps.map((s) => (
            <tr
              key={s.id}
              className="border-b border-border last:border-b-0 align-top"
              data-testid="step-row"
              data-outcome={s.outcome}
            >
              <td className="px-3 py-2 font-mono text-[11px] text-fg-4">{s.step_order}</td>
              <td className="px-3 py-2">
                <div className="flex flex-col gap-1">
                  <span className="font-mono text-[11px] text-fg-3">{s.case_public_id}</span>
                  {s.error_message ? (
                    <pre
                      className="overflow-x-auto rounded-md bg-[#060606] p-2 font-mono text-[11px] text-red"
                      data-testid="step-error-message"
                    >
                      {s.error_message}
                    </pre>
                  ) : null}
                </div>
              </td>
              <td className="px-3 py-2">
                <StatusBadge
                  status={OUTCOME_TO_BADGE[s.outcome]}
                  label={outcomeLabel(s.outcome)}
                />
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
