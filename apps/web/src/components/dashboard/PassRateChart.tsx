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
const LineChart = lazy(() =>
  import("recharts").then((m) => ({ default: m.LineChart })),
);
const Line = lazy(() => import("recharts").then((m) => ({ default: m.Line })));
const XAxis = lazy(() => import("recharts").then((m) => ({ default: m.XAxis })));
const YAxis = lazy(() => import("recharts").then((m) => ({ default: m.YAxis })));
const Tooltip = lazy(() =>
  import("recharts").then((m) => ({ default: m.Tooltip })),
);

/**
 * Pass-rate line chart used in the dashboard row 2. Renders as a
 * percentage Y axis 0..100 with the accent stroke + soft gradient fill.
 * Wrapped in Suspense so the lazy recharts modules can stream in.
 */
export function PassRateChart({ data }: Props): React.ReactElement {
  const points = useMemo(
    () =>
      (data.series ?? []).map((p) => ({ date: p.date, value: Math.round(p.passRate * 100) })),
    [data.series],
  );

  if (points.length === 0) {
    return (
      <div
        data-testid="pass-rate-chart-empty"
        className="flex h-[200px] items-center justify-center text-[12.5px] text-fg-4"
      >
        No pass-rate samples yet.
      </div>
    );
  }

  return (
    <div data-testid="pass-rate-chart" className="h-[200px]">
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
                fontSize: 12,
              }}
              labelStyle={{ color: "#a3a3a3" }}
            />
            <Line
              type="monotone"
              dataKey="value"
              stroke="#4ade80"
              strokeWidth={1.5}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </Suspense>
    </div>
  );
}
