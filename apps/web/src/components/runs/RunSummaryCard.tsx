import { StatusBadge } from "@/components/shared/StatusBadge";
import type { components } from "@/lib/api-types";
import { statusToBadge } from "@/lib/badge-maps";
import { formatTimestamp } from "@/lib/date";
import { formatDuration } from "@/lib/test-case-format";

type RunDetail = components["schemas"]["RunDetail"];

interface RunSummaryCardProps {
  run: RunDetail | undefined;
}


function coveragePercent(value: unknown): string {
  if (
    typeof value === "object" &&
    value !== null &&
    "percent" in value &&
    typeof value.percent === "number"
  ) {
    return `${value.percent.toFixed(1)}%`;
  }
  return "—";
}

export function RunSummaryCard({ run }: RunSummaryCardProps): React.ReactElement {
  if (!run) {
    return (
      <section
        data-testid="run-summary-card-skeleton"
        className="rounded-md border border-border bg-bg-elev-1 p-[14px] text-[12px] text-fg-4"
      >
        Loading run…
      </section>
    );
  }
  return (
    <section
      data-testid="run-summary-card"
      className="flex flex-col gap-3 rounded-md border border-border bg-bg-elev-1 p-[14px]"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <StatusBadge status={statusToBadge(run.status)} />
          <span className="font-mono text-[12px] text-fg-3">{run.public_id}</span>
          <span className="font-mono text-[11px] text-fg-5">via {run.trigger}</span>
        </div>
        <span className="font-mono text-[11px] text-fg-5">tier={run.tier_at_runtime}</span>
      </div>
      <h2 className="text-[18px] font-semibold leading-tight tracking-[-.01em] text-fg-1">
        {run.name}
      </h2>
      <dl
        className="grid grid-cols-4 gap-3 border-t border-border pt-3 font-mono text-[11px]"
        data-testid="run-summary-meta"
      >
        <Stat label="Started" value={formatTimestamp(run.started_at)} />
        <Stat label="Duration" value={formatDuration(run.duration_ms)} />
        <Stat
          label="Steps"
          value={`${run.summary.passed_steps.toString()} / ${run.summary.total_steps.toString()} passed`}
        />
        <Stat label="Failed" value={run.summary.failed_steps.toString()} />
      </dl>
      {run.coverage_summary ? (
        <dl
          className="grid grid-cols-2 gap-3 border-t border-border pt-3 font-mono text-[11px]"
          data-testid="run-coverage-summary"
        >
          <Stat label="Line coverage" value={coveragePercent(run.coverage_summary.lines)} />
          <Stat label="Branch coverage" value={coveragePercent(run.coverage_summary.branches)} />
        </dl>
      ) : null}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }): React.ReactElement {
  return (
    <div className="flex flex-col gap-1">
      <dt className="text-[10.5px] uppercase tracking-wide text-fg-5">{label}</dt>
      <dd className="text-[13px] tabular-nums text-fg-1">{value}</dd>
    </div>
  );
}
