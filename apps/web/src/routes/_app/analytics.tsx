import { createFileRoute } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  Flame,
  Minus,
  ShieldCheck,
} from "lucide-react";
import { Suspense } from "react";
import { useTranslation } from "react-i18next";

import { AnalyticsSkeleton } from "@/components/analytics/skeleton";
import { Heatmap } from "@/components/analytics/Heatmap";
import { PassRateChart } from "@/components/dashboard/PassRateChart";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { SmallGauge } from "@/components/shared/Gauge";
import { cn } from "@/lib/utils";
import {
  useAnalyticsCoverage,
  useAnalyticsFlaky,
  useAnalyticsHeatmap,
  useAnalyticsPassRate,
  useAnalyticsReadiness,
} from "@/hooks/use-analytics";

type Trend = { dir: "up" | "down" | "flat"; text: string } | undefined;

function GaugesRow(): React.ReactElement {
  const { data: readiness } = useAnalyticsReadiness();
  const { data: coverage } = useAnalyticsCoverage();
  const { data: passRate } = useAnalyticsPassRate("7d");

  const totalCovered = coverage.bySuite?.reduce((acc, s) => acc + s.covered, 0) ?? 0;
  const totalCases = coverage.bySuite?.reduce((acc, s) => acc + s.total, 0) ?? 0;
  const coveragePct = totalCases === 0 ? 0 : Math.round((totalCovered / totalCases) * 100);

  const series = passRate.series ?? [];
  const lastPoint = series.at(-1);
  const prevPoint = series.at(-2);
  const passPct = lastPoint ? Math.round(lastPoint.passRate * 100) : 0;

  const blockerCount = readiness.blockers?.length ?? 0;

  let passTrend: Trend;
  if (lastPoint && prevPoint) {
    const delta = passPct - Math.round(prevPoint.passRate * 100);
    passTrend =
      delta === 0
        ? { dir: "flat", text: "flat vs prev day" }
        : {
            dir: delta > 0 ? "up" : "down",
            text: `${delta > 0 ? "+" : ""}${delta.toString()}pp vs prev day`,
          };
  }

  return (
    <section className="grid grid-cols-1 gap-3 sm:grid-cols-3" data-testid="analytics-gauges">
      <MetricCard
        title="Release readiness"
        value={readiness.score}
        sub="Deterministic score"
        helper={
          blockerCount === 0
            ? "All gates green"
            : `${blockerCount.toString()} gating blocker${blockerCount === 1 ? "" : "s"}`
        }
        helperTone={blockerCount === 0 ? "good" : "bad"}
      />
      <MetricCard
        title="Test coverage"
        value={coveragePct}
        sub="Cases with requirements"
        helper={
          totalCases === 0
            ? "No linked requirements yet"
            : `${totalCovered.toString()} / ${totalCases.toString()} cases linked`
        }
        helperTone={totalCases === 0 ? "muted" : "neutral"}
      />
      <MetricCard
        title="Pass rate"
        value={passPct}
        sub="Last 7 days"
        helper={lastPoint ? `sampled through ${lastPoint.date}` : "No runs in period"}
        helperTone={lastPoint ? "neutral" : "muted"}
        trend={passTrend}
      />
    </section>
  );
}

function TrendPill({ trend }: { trend: NonNullable<Trend> }): React.ReactElement {
  const Icon = trend.dir === "up" ? ArrowUpRight : trend.dir === "down" ? ArrowDownRight : Minus;
  const tone = trend.dir === "up" ? "text-accent" : trend.dir === "down" ? "text-red" : "text-fg-4";
  return (
    <span className={cn("inline-flex items-center gap-1 text-[11px] font-medium", tone)}>
      <Icon className="h-3 w-3" />
      {trend.text}
    </span>
  );
}

function MetricCard({
  title,
  value,
  sub,
  helper,
  helperTone = "neutral",
  trend,
}: {
  title: string;
  value: number;
  sub: string;
  helper: string;
  helperTone?: "good" | "bad" | "muted" | "neutral";
  trend?: Trend;
}): React.ReactElement {
  const helperCls =
    helperTone === "good"
      ? "text-accent"
      : helperTone === "bad"
        ? "text-amber"
        : helperTone === "muted"
          ? "text-fg-5"
          : "text-fg-3";
  return (
    <div
      className="flex items-center gap-4 rounded-md border border-border bg-bg-elev-1 p-4 transition-colors hover:border-border-strong"
      data-testid="analytics-gauge-block"
    >
      <SmallGauge value={value} />
      <div className="flex min-w-0 flex-col gap-1">
        <span className="text-[13px] font-semibold text-fg-1">{title}</span>
        <span className="text-[11.5px] text-fg-4">{sub}</span>
        <span className={cn("truncate text-[11.5px]", helperCls)}>{helper}</span>
        {trend && <TrendPill trend={trend} />}
      </div>
    </div>
  );
}

function TrendCard(): React.ReactElement {
  const { data } = useAnalyticsPassRate("14d");
  const total = data.total;
  return (
    <section
      className="flex flex-col rounded-md border border-border bg-bg-elev-1 p-[14px]"
      data-testid="analytics-trend"
    >
      <header className="mb-3 flex items-start justify-between">
        <div>
          <h3 className="text-[13px] font-semibold text-fg-1">Pass rate trend</h3>
          <p className="text-[11.5px] text-fg-4">Daily, last 14 days</p>
        </div>
        <span className="font-mono text-[11px] text-fg-4">{total.toString()} runs</span>
      </header>
      <PassRateChart data={data} />
    </section>
  );
}

function FlakyCard(): React.ReactElement {
  const { data } = useAnalyticsFlaky(5);
  const empty = data.items.length === 0;
  return (
    <section
      className="flex flex-col rounded-md border border-border bg-bg-elev-1 p-[14px]"
      data-testid="analytics-flaky"
    >
      <header className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-[13px] font-semibold text-fg-1">Top flaky</h3>
          <p className="text-[11.5px] text-fg-4">Inconsistent pass/fail history</p>
        </div>
        <Flame className="h-3.5 w-3.5 text-amber" aria-hidden="true" />
      </header>
      {empty ? (
        <div
          className="flex flex-1 flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border py-6 text-center"
          data-testid="analytics-flaky-empty"
        >
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-accent/10">
            <ShieldCheck className="h-4 w-4 text-accent" aria-hidden="true" />
          </span>
          <span className="text-[13px] font-medium text-fg-1">No flaky tests</span>
          <span className="max-w-[240px] text-[11.5px] leading-snug text-fg-4">
            No test case has shown inconsistent results in the selected period.
          </span>
          <span className="mt-0.5 inline-flex items-center rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-accent">
            Stable
          </span>
        </div>
      ) : (
        <ul className="flex flex-col gap-1">
          {data.items.map((it) => {
            const pct = Math.round(it.flakeRate * 100);
            const tone = pct >= 15 ? "text-red" : pct >= 8 ? "text-amber" : "text-fg-1";
            return (
              <li
                key={it.caseId}
                className="flex items-center gap-3 rounded-md px-2 py-1.5 text-[12.5px] transition-colors hover:bg-bg-elev-2"
                data-testid="analytics-flaky-row"
              >
                <span className="font-mono text-[11px] text-fg-3">{it.publicId}</span>
                <div className="h-1 flex-1 overflow-hidden rounded-full bg-bg-elev-3">
                  <span
                    className={cn("block h-full rounded-full", pct >= 15 ? "bg-red" : "bg-amber")}
                    style={{ width: `${Math.min(pct, 100).toString()}%` }}
                  />
                </div>
                <span className="font-mono tabular-nums">
                  <span className={tone}>{pct}%</span>{" "}
                  <span className="text-fg-5">/ {it.sampleSize}</span>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function HeatmapCard(): React.ReactElement {
  const { data } = useAnalyticsHeatmap(14);
  return (
    <section
      className="rounded-md border border-border bg-bg-elev-1 p-[18px]"
      data-testid="analytics-heatmap-card"
    >
      <header className="mb-4 flex items-center justify-between">
        <div>
          <h3 className="text-[13px] font-semibold text-fg-1">Run heatmap</h3>
          <p className="text-[11.5px] text-fg-4">Runs by hour · last 14 days (04:00–23:00)</p>
        </div>
      </header>
      <Heatmap cells={data.cells} />
    </section>
  );
}

function AnalyticsBody(): React.ReactElement {
  return (
    <div className="flex flex-col gap-4">
      <GaugesRow />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
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
  const { t } = useTranslation();
  return (
    <section className="flex flex-col gap-4" data-testid="analytics-screen">
      <header>
        <h2 className="text-[20px] font-semibold tracking-[-.01em] text-fg-1">
          {t("analytics.title")}
        </h2>
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
