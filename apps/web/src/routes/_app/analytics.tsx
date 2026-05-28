import { createFileRoute } from "@tanstack/react-router";
import { AlertTriangle, Flame } from "lucide-react";
import { Suspense } from "react";

import { AnalyticsSkeleton } from "@/components/analytics/skeleton";
import { Heatmap } from "@/components/analytics/Heatmap";
import { PassRateChart } from "@/components/dashboard/PassRateChart";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { SmallGauge } from "@/components/shared/Gauge";
import {
  useAnalyticsCoverage,
  useAnalyticsFlaky,
  useAnalyticsHeatmap,
  useAnalyticsPassRate,
  useAnalyticsReadiness,
} from "@/hooks/use-analytics";

function GaugesRow(): React.ReactElement {
  const { data: readiness } = useAnalyticsReadiness();
  const { data: coverage } = useAnalyticsCoverage();
  const { data: passRate } = useAnalyticsPassRate("7d");

  const totalCovered =
    coverage.bySuite?.reduce((acc, s) => acc + s.covered, 0) ?? 0;
  const totalCases = coverage.bySuite?.reduce((acc, s) => acc + s.total, 0) ?? 0;
  const coveragePct = totalCases === 0 ? 0 : Math.round((totalCovered / totalCases) * 100);

  const lastPoint = passRate.series?.at(-1);
  const passPct = lastPoint ? Math.round(lastPoint.passRate * 100) : 0;

  return (
    <section
      className="grid grid-cols-3 gap-4 rounded-md border border-border bg-bg-elev-1 p-[14px]"
      data-testid="analytics-gauges"
    >
      <GaugeBlock title="Release readiness" value={readiness.score} sub="Deterministic" />
      <GaugeBlock title="Test coverage" value={coveragePct} sub="Cases with requirements" />
      <GaugeBlock title="Pass rate" value={passPct} sub="Last 7 days" />
    </section>
  );
}

function GaugeBlock({
  title,
  value,
  sub,
}: {
  title: string;
  value: number;
  sub: string;
}): React.ReactElement {
  return (
    <div className="flex items-center gap-4" data-testid="analytics-gauge-block">
      <SmallGauge value={value} />
      <div className="flex flex-col gap-0.5">
        <span className="text-[13px] font-semibold text-fg-1">{title}</span>
        <span className="text-[11.5px] text-fg-4">{sub}</span>
      </div>
    </div>
  );
}

function TrendCard(): React.ReactElement {
  const { data } = useAnalyticsPassRate("14d");
  return (
    <section
      className="rounded-md border border-border bg-bg-elev-1 p-[14px]"
      data-testid="analytics-trend"
    >
      <header className="mb-3">
        <h3 className="text-[13px] font-semibold text-fg-1">Pass rate trend</h3>
        <p className="text-[11.5px] text-fg-4">Daily, last 14 days</p>
      </header>
      <PassRateChart data={data} />
    </section>
  );
}

function FlakyCard(): React.ReactElement {
  const { data } = useAnalyticsFlaky(5);
  return (
    <section
      className="rounded-md border border-border bg-bg-elev-1 p-[14px]"
      data-testid="analytics-flaky"
    >
      <header className="mb-3 flex items-center justify-between">
        <h3 className="text-[13px] font-semibold text-fg-1">Top flaky</h3>
        <Flame className="h-3.5 w-3.5 text-amber" aria-hidden="true" />
      </header>
      {data.items.length === 0 ? (
        <div className="text-[12px] text-fg-4">No flaky cases detected.</div>
      ) : (
        <ul className="flex flex-col gap-2">
          {data.items.map((it) => (
            <li
              key={it.caseId}
              className="flex items-center justify-between text-[12.5px]"
              data-testid="analytics-flaky-row"
            >
              <span className="font-mono text-[11px] text-fg-3">{it.publicId}</span>
              <span className="font-mono text-fg-1">
                {Math.round(it.flakeRate * 100)}%{" "}
                <span className="text-fg-5">over {it.sampleSize}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function HeatmapCard(): React.ReactElement {
  const { data } = useAnalyticsHeatmap(14);
  return (
    <section
      className="rounded-md border border-border bg-bg-elev-1 p-[14px]"
      data-testid="analytics-heatmap-card"
    >
      <header className="mb-3">
        <h3 className="text-[13px] font-semibold text-fg-1">Run heatmap</h3>
        <p className="text-[11.5px] text-fg-4">14 days × 20 hours</p>
      </header>
      <Heatmap cells={data.cells} />
    </section>
  );
}

function AnalyticsBody(): React.ReactElement {
  return (
    <div className="flex flex-col gap-4">
      <GaugesRow />
      <div className="grid grid-cols-2 gap-4">
        <TrendCard />
        <FlakyCard />
      </div>
      <HeatmapCard />
    </div>
  );
}

function AnalyticsError({ reset }: { reset: () => void }): React.ReactElement {
  return (
    <EmptyState
      icon={AlertTriangle}
      title="Couldn't load analytics"
      action={{ label: "Retry", onClick: reset }}
    />
  );
}

function Analytics(): React.ReactElement {
  return (
    <section className="flex flex-col gap-4" data-testid="analytics-screen">
      <header>
        <h2 className="text-[20px] font-semibold tracking-[-.01em] text-fg-1">Analytics</h2>
      </header>
      <ErrorBoundary fallback={({ reset }) => <AnalyticsError reset={reset} />}>
        <Suspense fallback={<AnalyticsSkeleton />}>
          <AnalyticsBody />
        </Suspense>
      </ErrorBoundary>
    </section>
  );
}

export const Route = createFileRoute("/_app/analytics")({
  component: Analytics,
  staticData: { title: "Analytics" },
});
