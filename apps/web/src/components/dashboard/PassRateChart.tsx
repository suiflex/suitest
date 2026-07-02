import { lazy, Suspense, useMemo } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import type { components } from "@/lib/api-types";

type PassRateSeries = components["schemas"]["PassRateSeriesOut"];

interface Props {
  data: PassRateSeries;
}

// Recharts is ~120kb minzipped; defer it until the dashboard mounts so the
// initial app shell stays thin. Loading falls back to a Skeleton so the
// chart card never collapses.
const ResponsiveContainer = lazy(() =>
  import("recharts").then((m) => ({ default: m.ResponsiveContainer })),
);
const LineChart = lazy(() => import("recharts").then((m) => ({ default: m.LineChart })));
const Line = lazy(() => import("recharts").then((m) => ({ default: m.Line })));
const XAxis = lazy(() => import("recharts").then((m) => ({ default: m.XAxis })));
const YAxis = lazy(() => import("recharts").then((m) => ({ default: m.YAxis })));
const Tooltip = lazy(() => import("recharts").then((m) => ({ default: m.Tooltip })));

const CHART_H = "h-[200px]";

/** No samples at all — nudge the user to run a suite. */
function EmptyState(): React.ReactElement {
  return (
    <div
      data-testid="pass-rate-chart-empty"
      className={`flex ${CHART_H} flex-col items-center justify-center gap-1.5 rounded-md border border-dashed border-border text-center`}
    >
      <span className="text-[12.5px] font-medium text-fg-2">No pass-rate samples yet</span>
      <span className="text-[11px] text-fg-4">Runs will chart a daily pass-rate trend here.</span>
    </div>
  );
}

/**
 * Exactly one sample: a line needs two points to draw a segment, so render an
 * elegant single-value state with a baseline marker instead of an empty plot.
 */
function SinglePoint({ value, date }: { value: number; date: string }): React.ReactElement {
  return (
    <div
      data-testid="pass-rate-chart-single"
      className={`relative flex ${CHART_H} flex-col justify-between rounded-md border border-border/70 bg-bg-elev-2/40 p-4`}
    >
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-[34px] font-semibold leading-none tabular-nums text-accent">
          {value}
          <span className="text-[18px] text-fg-4">%</span>
        </span>
        <span className="text-[11px] text-fg-4">on {date}</span>
      </div>

      {/* Minimal baseline with a single plotted marker */}
      <div className="relative mb-1 mt-4 h-px w-full bg-border">
        <span
          className="absolute -top-[3px] left-1/2 h-2 w-2 -translate-x-1/2 rounded-full bg-accent ring-4 ring-accent/15"
          aria-hidden="true"
        />
        <span className="absolute -bottom-5 left-1/2 -translate-x-1/2 font-mono text-[9.5px] text-fg-4">
          {date}
        </span>
      </div>

      <p className="text-[11px] leading-snug text-fg-4">
        More runs will build a trend line across days.
      </p>
    </div>
  );
}

/**
 * Pass-rate line chart. Renders as a percentage Y axis 0..100 with the accent
 * stroke. Degrades to a single-value state (1 sample) or an empty state
 * (0 samples) so the card never shows a lonely blank plot.
 */
export function PassRateChart({ data }: Props): React.ReactElement {
  const points = useMemo(
    () => (data.series ?? []).map((p) => ({ date: p.date, value: Math.round(p.passRate * 100) })),
    [data.series],
  );

  if (points.length === 0) return <EmptyState />;
  if (points.length === 1) {
    const p = points[0]!;
    return <SinglePoint value={p.value} date={p.date} />;
  }

  return (
    <div data-testid="pass-rate-chart" className={CHART_H}>
      <Suspense fallback={<Skeleton className="h-full w-full rounded-md" />}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: -8 }}>
            <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#737373" }} stroke="#262626" />
            <YAxis
              tick={{ fontSize: 10, fill: "#737373" }}
              stroke="#262626"
              domain={[0, 100]}
              width={28}
            />
            <Tooltip
              contentStyle={{
                background: "#161616",
                border: "1px solid #262626",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: "#a3a3a3" }}
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke="#4ade80"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 3, fill: "#4ade80", stroke: "#0a0a0a", strokeWidth: 2 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </Suspense>
    </div>
  );
}
