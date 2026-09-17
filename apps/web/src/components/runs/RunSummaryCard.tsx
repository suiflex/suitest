import { ProgressBar } from "@/components/shared/ProgressBar";
import { StatusBadge } from "@/components/shared/StatusBadge";
import type { components } from "@/lib/api-types";
import { buildRunSegments, runToBadge } from "@/lib/badge-maps";
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
  const totalStepsFromCases =
    run.cases && run.cases.length > 0
      ? run.cases.reduce((acc, c) => acc + (c.total_steps ?? 0), 0)
      : 0;
  const totalSteps =
    totalStepsFromCases > 0
      ? Math.max(totalStepsFromCases, run.summary?.total_steps ?? 0)
      : run.summary?.total_steps ?? 0;
  const effectiveSummary = run.summary
    ? { ...run.summary, total_steps: totalSteps }
    : { total_steps: totalSteps, passed_steps: 0, failed_steps: 0, duration_ms: 0 };
  const badge = runToBadge(run.status, effectiveSummary);
  const segments = buildRunSegments(run.status, effectiveSummary);
  const passedSteps = effectiveSummary.passed_steps;
  const failedSteps = effectiveSummary.failed_steps;
  const skippedSteps = Math.max(0, totalSteps - (passedSteps + failedSteps));
  const isRunning = run.status === "RUNNING";
  const isQueued = run.status === "QUEUED";
  const isTerminal =
    run.status === "PASS" ||
    run.status === "FAIL" ||
    run.status === "ERROR" ||
    run.status === "CANCELLED";

  return (
    <section
      data-testid="run-summary-card"
      className="flex flex-col gap-3 rounded-md border border-border bg-bg-elev-1 p-[14px]"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <StatusBadge status={badge.status} label={badge.label} />
          <span className="font-mono text-[12px] text-fg-3">{run.public_id}</span>
          <span className="font-mono text-[11px] text-fg-5">via {run.trigger}</span>
        </div>
      </div>
      <h2 className="text-[18px] font-semibold leading-tight tracking-[-.01em] text-fg-1">
        {run.name}
      </h2>

      <div className="flex flex-col gap-2 border-t border-border pt-3" data-testid="run-progress-section">
        <ProgressBar
          segments={segments}
          total={totalSteps > 0 ? totalSteps : 100}
          className="h-2"
        />
        <div className="flex flex-wrap items-center gap-3 font-mono text-[11px] text-fg-4">
          {totalSteps === 0 ? (
            run.status === "CANCELLED" ? (
              <span className="flex items-center gap-1.5 text-red">
                <span className="inline-block h-2 w-2 rounded-full bg-red" />
                Run aborted (No steps executed)
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-amber">
                <span className="inline-block h-2 w-2 rounded-full bg-amber" />
                No steps defined (Skipped)
              </span>
            )
          ) : isQueued ? (
            <span className="flex items-center gap-1.5 text-fg-3">
              <span className="inline-block h-2 w-2 rounded-full bg-fg-4" />
              Queued ({totalSteps} {totalSteps === 1 ? "step" : "steps"} pending)
            </span>
          ) : (
            <>
              {passedSteps > 0 || isTerminal ? (
                <span className="flex items-center gap-1.5 text-fg-3">
                  <span className="inline-block h-2 w-2 rounded-full bg-accent" />
                  {passedSteps} passed
                </span>
              ) : null}
              {failedSteps > 0 ? (
                <span className="flex items-center gap-1.5 text-red">
                  <span className="inline-block h-2 w-2 rounded-full bg-red" />
                  {failedSteps} failed
                </span>
              ) : null}
              {run.status === "CANCELLED" ? (
                <span className="flex items-center gap-1.5 text-red">
                  <span className="inline-block h-2 w-2 rounded-full bg-red" />
                  {skippedSteps > 0 ? `${skippedSteps} aborted` : "Run aborted"}
                </span>
              ) : isTerminal && skippedSteps > 0 ? (
                <span className="flex items-center gap-1.5 text-amber">
                  <span className="inline-block h-2 w-2 rounded-full bg-amber" />
                  {run.status === "FAIL" || run.status === "ERROR"
                    ? `${skippedSteps} aborted`
                    : `${skippedSteps} skipped`}
                </span>
              ) : null}
              {isRunning ? (
                <span className="flex items-center gap-1.5 text-blue">
                  <span className="inline-block h-2 w-2 rounded-full bg-blue suitest-pulse" />
                  Running live
                </span>
              ) : null}
            </>
          )}
        </div>
      </div>

      <dl
        className="grid grid-cols-4 gap-3 border-t border-border pt-3 font-mono text-[11px]"
        data-testid="run-summary-meta"
      >
        <Stat label="Started" value={formatTimestamp(run.started_at)} />
        <Stat label="Duration" value={formatDuration(run.duration_ms)} />
        <Stat
          label="Steps"
          value={`${effectiveSummary.passed_steps.toString()} / ${effectiveSummary.total_steps.toString()} passed`}
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
