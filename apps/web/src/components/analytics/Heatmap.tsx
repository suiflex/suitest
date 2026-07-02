import { Activity, CalendarDays, Clock, Grid3x3 } from "lucide-react";
import { useMemo, useState } from "react";

import type { components } from "@/lib/api-types";
import { cn } from "@/lib/utils";

// The API contract is `HeatmapCell { count, day, hour }`. `passed`/`failed`
// are optional enrichments — when the backend supplies them the tooltip shows
// a pass/fail breakdown; otherwise it gracefully falls back to run count only.
type Cell = components["schemas"]["HeatmapCell"] & {
  passed?: number;
  failed?: number;
};

const DAYS = 14;
const HOURS = 20;
const HOUR_OFFSET = 4; // render hour buckets 4..23 (20 buckets, working hours)
const LOW_DATA_RUNS = 6; // total runs at/below which we surface the low-data hint

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const HOUR_LABELS = new Set([4, 8, 12, 16, 20, 23]);

const DAY_MS = 86_400_000;

function colorFor(count: number, max: number): string {
  if (max === 0 || count === 0) return "bg-bg-elev-3";
  const ratio = count / max;
  if (ratio < 0.2) return "bg-accent/25";
  if (ratio < 0.4) return "bg-accent/45";
  if (ratio < 0.6) return "bg-accent/65";
  if (ratio < 0.8) return "bg-accent/80";
  return "bg-accent";
}

function pad2(n: number): string {
  return n.toString().padStart(2, "0");
}

type DayMeta = { key: string; dom: number; weekday: number; label: string };

type CellAgg = { count: number; passed: number; failed: number; hasBreakdown: boolean };

type HoverCell = {
  date: string;
  hourRange: string;
  agg: CellAgg;
  x: number;
  y: number;
};

type Model = {
  matrix: CellAgg[][]; // matrix[dayIndex][hourIndex]
  days: DayMeta[];
  max: number;
  total: number;
  activeCells: number;
  peakHour: { hour: number; count: number } | null;
  busiestDay: (DayMeta & { count: number }) | null;
  busiestSlot: { day: DayMeta; hour: number; count: number } | null;
};

function emptyAgg(): CellAgg {
  return { count: 0, passed: 0, failed: 0, hasBreakdown: false };
}

function todayKey(): string {
  // App-runtime only (never a workflow script) so `new Date()` is safe here.
  return new Date().toISOString().slice(0, 10);
}

function buildModel(cells: Cell[]): Model {
  const lookup = new Map<string, CellAgg>(); // `${dateKey}#${hour}` -> agg
  let latestKey = "";
  for (const c of cells) {
    const key = c.day.slice(0, 10);
    if (key > latestKey) latestKey = key;
    const lk = `${key}#${c.hour.toString()}`;
    const agg = lookup.get(lk) ?? emptyAgg();
    agg.count += c.count;
    if (c.passed !== undefined || c.failed !== undefined) {
      agg.passed += c.passed ?? 0;
      agg.failed += c.failed ?? 0;
      agg.hasBreakdown = true;
    }
    lookup.set(lk, agg);
  }
  if (latestKey === "") latestKey = todayKey();

  const base = Date.parse(`${latestKey}T00:00:00Z`);
  const days: DayMeta[] = Array.from({ length: DAYS }, (_, i) => {
    const d = new Date(base - (DAYS - 1 - i) * DAY_MS);
    return {
      key: d.toISOString().slice(0, 10),
      dom: d.getUTCDate(),
      weekday: d.getUTCDay(),
      label: `${WEEKDAYS[d.getUTCDay()]!}, ${MONTHS[d.getUTCMonth()]!} ${d.getUTCDate().toString()}`,
    };
  });

  const matrix: CellAgg[][] = days.map((day) =>
    Array.from(
      { length: HOURS },
      (_, hi) => lookup.get(`${day.key}#${(hi + HOUR_OFFSET).toString()}`) ?? emptyAgg(),
    ),
  );

  let max = 0;
  let total = 0;
  let activeCells = 0;
  const hourTotals = Array<number>(HOURS).fill(0);
  const dayTotals = Array<number>(DAYS).fill(0);
  let busiestSlot: Model["busiestSlot"] = null;

  matrix.forEach((row, di) => {
    row.forEach((agg, hi) => {
      const { count } = agg;
      if (count > max) max = count;
      total += count;
      if (count > 0) activeCells += 1;
      hourTotals[hi]! += count;
      dayTotals[di]! += count;
      if (count > 0 && (busiestSlot === null || count > busiestSlot.count)) {
        busiestSlot = { day: days[di]!, hour: hi + HOUR_OFFSET, count };
      }
    });
  });

  let peakHour: Model["peakHour"] = null;
  hourTotals.forEach((c, hi) => {
    if (c > 0 && (peakHour === null || c > peakHour.count)) {
      peakHour = { hour: hi + HOUR_OFFSET, count: c };
    }
  });

  let busiestDay: Model["busiestDay"] = null;
  dayTotals.forEach((c, di) => {
    if (c > 0 && (busiestDay === null || c > busiestDay.count)) {
      busiestDay = { ...days[di]!, count: c };
    }
  });

  return { matrix, days, max, total, activeCells, peakHour, busiestDay, busiestSlot };
}

// ── Sub-components ──────────────────────────────────────────────────────────

function IntensityLegend({ max }: { max: number }): React.ReactElement {
  const swatches = [
    "bg-bg-elev-3",
    "bg-accent/25",
    "bg-accent/45",
    "bg-accent/65",
    "bg-accent/80",
    "bg-accent",
  ];
  const buckets = [
    { cls: "bg-bg-elev-3", label: "None" },
    { cls: "bg-accent/25", label: "Low" },
    { cls: "bg-accent/65", label: "Medium" },
    { cls: "bg-accent", label: "High" },
  ];
  return (
    <div className="flex flex-col gap-2" data-testid="heatmap-legend">
      <div className="flex items-center gap-2 text-[10.5px] text-fg-4">
        <span>Less</span>
        <div className="flex items-center gap-[3px]">
          {swatches.map((c) => (
            <span
              key={c}
              className={cn("h-3 w-3 rounded-[3px] ring-1 ring-inset ring-white/[0.04]", c)}
            />
          ))}
        </div>
        <span>More</span>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        {buckets.map((b) => (
          <span key={b.label} className="flex items-center gap-1.5 text-[10.5px] text-fg-4">
            <span className={cn("h-2.5 w-2.5 rounded-[3px]", b.cls)} />
            {b.label}
          </span>
        ))}
        <span className="ml-auto font-mono text-[10.5px] text-fg-3">
          peak {max.toString()} runs
        </span>
      </div>
    </div>
  );
}

function InsightCard({
  icon: Icon,
  label,
  value,
  hint,
  accent,
  testId,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;
  hint?: string | undefined;
  accent?: boolean | undefined;
  testId?: string | undefined;
}): React.ReactElement {
  return (
    <div
      className="flex flex-col gap-1 rounded-lg border border-border/80 bg-bg-elev-2/60 px-3 py-2.5"
      data-testid={testId}
    >
      <div className="flex items-center gap-1.5 text-fg-4">
        <Icon className="h-3 w-3" />
        <span className="text-[10px] font-medium uppercase tracking-wide">{label}</span>
      </div>
      <span
        className={cn(
          "font-mono text-[15px] font-semibold leading-none tabular-nums",
          accent ? "text-accent" : "text-fg-1",
        )}
      >
        {value}
      </span>
      {hint !== undefined && <span className="text-[10.5px] text-fg-4">{hint}</span>}
    </div>
  );
}

function Tooltip({ hover }: { hover: HoverCell }): React.ReactElement {
  const { agg } = hover;
  const denom = agg.passed + agg.failed;
  const passRate = denom > 0 ? Math.round((agg.passed / denom) * 100) : null;
  return (
    <div
      className="pointer-events-none absolute z-20 -translate-x-1/2 -translate-y-full rounded-lg border border-border bg-bg-elev-2/95 px-3 py-2 shadow-xl backdrop-blur-sm"
      style={{ left: hover.x, top: hover.y - 10 }}
      data-testid="heatmap-tooltip"
    >
      <div className="whitespace-nowrap text-[11.5px] font-semibold text-fg-1">{hover.date}</div>
      <div className="mb-1 whitespace-nowrap font-mono text-[10.5px] text-fg-4">
        {hover.hourRange}
      </div>
      <div className="flex items-center gap-1.5 whitespace-nowrap text-[11.5px]">
        <span className="h-1.5 w-1.5 rounded-full bg-accent" />
        <span className="font-mono font-semibold text-fg-1">{agg.count}</span>
        <span className="text-fg-4">{agg.count === 1 ? "run" : "runs"}</span>
      </div>
      {agg.hasBreakdown && (
        <div className="mt-1 flex flex-col gap-0.5 border-t border-border pt-1 font-mono text-[10.5px]">
          <div className="flex items-center justify-between gap-4">
            <span className="text-fg-4">Passed</span>
            <span className="text-accent">{agg.passed}</span>
          </div>
          <div className="flex items-center justify-between gap-4">
            <span className="text-fg-4">Failed</span>
            <span className={agg.failed > 0 ? "text-red" : "text-fg-3"}>{agg.failed}</span>
          </div>
          {passRate !== null && (
            <div className="flex items-center justify-between gap-4">
              <span className="text-fg-4">Pass rate</span>
              <span className="text-fg-1">{passRate}%</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main ────────────────────────────────────────────────────────────────────

export function Heatmap({ cells }: { cells: Cell[] }): React.ReactElement {
  const model = useMemo(() => buildModel(cells), [cells]);
  const [hover, setHover] = useState<HoverCell | null>(null);

  const { matrix, days, max, total, activeCells, peakHour, busiestDay, busiestSlot } = model;
  const rows = Array.from({ length: HOURS }, (_, hi) => hi);
  const lowData = total > 0 && total <= LOW_DATA_RUNS;
  const noData = total === 0;

  return (
    <div className="grid gap-6 lg:grid-cols-[auto_minmax(0,1fr)] lg:gap-8" data-testid="heatmap">
      {/* ── Chart column ── */}
      <div
        className="relative"
        style={{ ["--cell" as string]: "clamp(14px, 1.3vw, 18px)" }}
        onMouseLeave={() => {
          setHover(null);
        }}
      >
        <div className="flex gap-2">
          {/* Hour axis */}
          <div className="flex flex-col gap-[3px] pt-[1px] font-mono text-[9.5px] text-fg-4">
            {rows.map((hi) => {
              const hour = hi + HOUR_OFFSET;
              return (
                <div
                  key={hi}
                  className="flex items-center justify-end pr-1"
                  style={{ height: "var(--cell)", width: "30px" }}
                >
                  {HOUR_LABELS.has(hour) ? `${pad2(hour)}:00` : ""}
                </div>
              );
            })}
          </div>

          {/* Grid + day axis */}
          <div className="flex flex-col gap-2">
            <div
              className="grid gap-[3px]"
              style={{
                gridTemplateColumns: `repeat(${DAYS.toString()}, var(--cell))`,
                gridTemplateRows: `repeat(${HOURS.toString()}, var(--cell))`,
              }}
              data-testid="heatmap-grid"
            >
              {rows.map((hi) =>
                days.map((day, di) => {
                  const agg = matrix[di]![hi]!;
                  const hour = hi + HOUR_OFFSET;
                  const isHot =
                    busiestSlot !== null &&
                    busiestSlot.day.key === day.key &&
                    busiestSlot.hour === hour;
                  return (
                    <div
                      key={`${di.toString()}-${hi.toString()}`}
                      data-testid="heatmap-cell"
                      data-count={agg.count}
                      role="img"
                      aria-label={`${day.label}, ${pad2(hour)}:00 — ${agg.count.toString()} runs`}
                      className={cn(
                        "rounded-[3px] ring-1 ring-inset ring-white/[0.03] transition-[transform,box-shadow] duration-100",
                        colorFor(agg.count, max),
                        "hover:z-10 hover:scale-[1.35] hover:ring-2 hover:ring-fg-1/60",
                        isHot && "ring-2 ring-accent/70",
                      )}
                      onMouseEnter={(e) => {
                        const host = e.currentTarget.closest(
                          "[data-testid='heatmap']",
                        ) as HTMLElement | null;
                        const hostBox = host?.getBoundingClientRect();
                        const box = e.currentTarget.getBoundingClientRect();
                        setHover({
                          date: day.label,
                          hourRange: `${pad2(hour)}:00 – ${pad2(hour + 1)}:00`,
                          agg,
                          x: box.left - (hostBox?.left ?? 0) + box.width / 2,
                          y: box.top - (hostBox?.top ?? 0),
                        });
                      }}
                    />
                  );
                }),
              )}
            </div>

            {/* Day axis */}
            <div
              className="grid gap-[3px] font-mono text-[9px] text-fg-4"
              style={{ gridTemplateColumns: `repeat(${DAYS.toString()}, var(--cell))` }}
            >
              {days.map((day, di) => (
                <div key={day.key} className="flex justify-center">
                  {di % 2 === 0 ? day.dom.toString() : ""}
                </div>
              ))}
            </div>

            <div className="pt-1">
              <IntensityLegend max={max} />
            </div>
          </div>
        </div>

        {hover !== null && <Tooltip hover={hover} />}
      </div>

      {/* ── Insights column ── */}
      <div className="flex flex-col gap-3">
        {(lowData || noData) && (
          <div
            className="flex items-start gap-2.5 rounded-lg border border-amber/25 bg-amber/[0.06] px-3 py-2.5"
            data-testid="heatmap-lowdata"
          >
            <Activity className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber" />
            <div className="flex flex-col gap-0.5">
              <span className="text-[12px] font-medium text-fg-1">
                {noData ? "No run activity yet" : "Not enough run history yet"}
              </span>
              <span className="text-[11px] leading-snug text-fg-4">
                Run more tests to reveal activity patterns across days and hours.
              </span>
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <InsightCard
            icon={Clock}
            label="Peak hour"
            value={peakHour ? `${pad2(peakHour.hour)}:00` : "—"}
            hint={
              peakHour
                ? `${peakHour.count.toString()} ${peakHour.count === 1 ? "run" : "runs"}`
                : "no runs yet"
            }
            accent
            testId="heatmap-peak"
          />
          <InsightCard
            icon={CalendarDays}
            label="Busiest day"
            value={
              busiestDay ? `${WEEKDAYS[busiestDay.weekday]!} ${busiestDay.dom.toString()}` : "—"
            }
            hint={
              busiestDay
                ? `${busiestDay.count.toString()} ${busiestDay.count === 1 ? "run" : "runs"}`
                : "no runs yet"
            }
          />
          <InsightCard
            icon={Activity}
            label="Total runs"
            value={total.toString()}
            hint="last 14 days"
          />
          <InsightCard
            icon={Grid3x3}
            label="Active slots"
            value={`${activeCells.toString()} / ${(DAYS * HOURS).toString()}`}
            hint="hour buckets"
          />
        </div>

        <div
          className="rounded-lg border border-border/80 bg-bg-elev-2/60 px-3 py-2.5"
          data-testid="heatmap-busiest-slot"
        >
          <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-fg-4">
            <span className="h-1.5 w-1.5 rounded-full bg-accent" />
            Busiest window
          </div>
          {busiestSlot !== null ? (
            <>
              <div className="mt-1.5 text-[12.5px] font-medium text-fg-1">
                {busiestSlot.day.label}
              </div>
              <div className="font-mono text-[11px] text-fg-3">
                {pad2(busiestSlot.hour)}:00 ·{" "}
                <span className="text-accent">{busiestSlot.count} runs</span>
              </div>
            </>
          ) : (
            <div className="mt-1.5 text-[12px] text-fg-4">No activity recorded yet.</div>
          )}
        </div>

        <p className="mt-auto text-[11px] leading-relaxed text-fg-4">
          Columns are the last 14 days; rows are hours {pad2(HOUR_OFFSET)}:00–23:00. Brighter cells
          mean more runs — hover any cell for its pass/fail breakdown.
        </p>
      </div>
    </div>
  );
}
