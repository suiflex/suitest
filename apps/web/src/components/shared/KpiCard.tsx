import { ArrowDown, ArrowUp, type LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

export interface KpiCardProps {
  label: string;
  value: string | number;
  delta?: string;
  deltaDirection?: "up" | "down";
  icon?: LucideIcon;
  className?: string;
}

/**
 * Compact KPI tile used on the Dashboard grid. See UI_SPEC § 3.1 and § 4.2.
 *
 * Layout:
 *   - 14px padding
 *   - Eyebrow label `text-[11px] uppercase tracking-wide text-fg-5`
 *   - Value `text-[24px] font-semibold tabular-nums`
 *   - Optional delta row with arrow icon + colored text (up=accent, down=red).
 */
export function KpiCard({
  label,
  value,
  delta,
  deltaDirection,
  icon: Icon,
  className,
}: KpiCardProps): React.ReactElement {
  const deltaIsUp = deltaDirection === "up";
  return (
    <div
      data-testid="kpi-card"
      className={cn(
        "flex flex-col gap-1.5 rounded-md border border-border bg-bg-elev-1 p-[14px]",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div
          className="text-[11px] font-medium uppercase tracking-wide text-fg-5"
          data-testid="kpi-card-label"
        >
          {label}
        </div>
        {Icon ? <Icon className="h-3.5 w-3.5 text-fg-4" aria-hidden="true" /> : null}
      </div>
      <div
        className="text-[24px] font-semibold leading-none tabular-nums text-fg-1"
        data-testid="kpi-card-value"
      >
        {value}
      </div>
      {delta ? (
        <div
          data-testid="kpi-card-delta"
          data-delta-direction={deltaDirection ?? "neutral"}
          className={cn(
            "inline-flex items-center gap-1 text-[11.5px] font-medium",
            deltaIsUp ? "text-accent" : deltaDirection === "down" ? "text-red" : "text-fg-3",
          )}
        >
          {deltaIsUp ? (
            <ArrowUp className="h-3 w-3" aria-hidden="true" />
          ) : deltaDirection === "down" ? (
            <ArrowDown className="h-3 w-3" aria-hidden="true" />
          ) : null}
          <span>{delta}</span>
        </div>
      ) : null}
    </div>
  );
}
