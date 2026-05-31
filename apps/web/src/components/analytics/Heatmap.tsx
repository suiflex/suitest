import { useMemo } from "react";

import type { components } from "@/lib/api-types";
import { cn } from "@/lib/utils";

type Cell = components["schemas"]["HeatmapCell"];

const DAYS = 14;
const HOURS = 20;
const HOUR_OFFSET = 4; // render hour buckets 4..23 (20 buckets, working hours)

function colorFor(count: number, max: number): string {
  if (max === 0 || count === 0) return "bg-bg-elev-3";
  const ratio = count / max;
  if (ratio < 0.2) return "bg-accent/20";
  if (ratio < 0.4) return "bg-accent/40";
  if (ratio < 0.6) return "bg-accent/60";
  if (ratio < 0.8) return "bg-accent/80";
  return "bg-accent";
}

export function Heatmap({ cells }: { cells: Cell[] }): React.ReactElement {
  const { matrix, max, peak } = useMemo(() => {
    const m: number[][] = Array.from({ length: DAYS }, () => Array<number>(HOURS).fill(0));
    let peakHour = 0;
    let peakCount = 0;
    let maxLocal = 0;
    // Sort cells by day so the most-recent days are on the right edge.
    const byDay = [...cells].sort((a, b) => a.day.localeCompare(b.day));
    const dayIdx = new Map<string, number>();
    for (const c of byDay) {
      const key = c.day.slice(0, 10);
      if (!dayIdx.has(key)) {
        if (dayIdx.size >= DAYS) continue;
        dayIdx.set(key, dayIdx.size);
      }
      const di = dayIdx.get(key)!;
      const hi = c.hour - HOUR_OFFSET;
      if (hi < 0 || hi >= HOURS) continue;
      m[di]![hi]! += c.count;
      if (m[di]![hi]! > maxLocal) maxLocal = m[di]![hi]!;
      if (c.count > peakCount) {
        peakCount = c.count;
        peakHour = c.hour;
      }
    }
    return { matrix: m, max: maxLocal, peak: peakHour };
  }, [cells]);

  const flat = matrix.flatMap((row, di) =>
    row.map((count, hi) => ({ count, key: `${di.toString()}-${hi.toString()}` })),
  );

  return (
    <div className="flex flex-col gap-3" data-testid="heatmap">
      <div
        className="grid gap-[3px]"
        style={{ gridTemplateColumns: `repeat(${HOURS.toString()}, minmax(0, 1fr))` }}
        data-testid="heatmap-grid"
      >
        {flat.map((c) => (
          <div
            key={c.key}
            data-testid="heatmap-cell"
            data-count={c.count}
            title={`${c.count.toString()} runs`}
            className={cn("aspect-square rounded-sm", colorFor(c.count, max))}
          />
        ))}
      </div>
      <div className="flex items-center justify-between text-[11px] text-fg-4">
        <span>Less</span>
        <div className="flex items-center gap-[3px]">
          <span className="h-2.5 w-2.5 rounded-sm bg-bg-elev-3" />
          <span className="h-2.5 w-2.5 rounded-sm bg-accent/20" />
          <span className="h-2.5 w-2.5 rounded-sm bg-accent/40" />
          <span className="h-2.5 w-2.5 rounded-sm bg-accent/60" />
          <span className="h-2.5 w-2.5 rounded-sm bg-accent/80" />
          <span className="h-2.5 w-2.5 rounded-sm bg-accent" />
        </div>
        <span>More</span>
      </div>
      <div className="text-[11.5px] text-fg-3" data-testid="heatmap-peak">
        Peak hour:{" "}
        <span className="font-mono text-fg-1">{peak.toString().padStart(2, "0")}:00</span>
      </div>
    </div>
  );
}
