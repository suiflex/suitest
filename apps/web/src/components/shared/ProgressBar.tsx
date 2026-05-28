import { cn } from "@/lib/utils";

export type ProgressBarVariant = "default" | "warn" | "fail";

export interface ProgressBarProps {
  /** 0..100. Out-of-range values are clamped. */
  value: number;
  variant?: ProgressBarVariant;
  /** Optional label shown above the track. */
  label?: string;
  className?: string;
}

const FILL_CLASSES: Record<ProgressBarVariant, string> = {
  default: "bg-accent",
  warn: "bg-amber",
  fail: "bg-red",
};

function clamp(value: number): number {
  if (Number.isNaN(value)) return 0;
  if (value < 0) return 0;
  if (value > 100) return 100;
  return value;
}

/**
 * Slim progress track + animated fill (UI_SPEC § 4.5). Used for coverage rows
 * and similar inline metrics.
 */
export function ProgressBar({
  value,
  variant = "default",
  label,
  className,
}: ProgressBarProps): React.ReactElement {
  const pct = clamp(value);
  return (
    <div
      data-testid="progress-bar"
      data-variant={variant}
      className={cn("flex flex-col gap-1", className)}
    >
      {label ? (
        <div className="flex items-center justify-between text-[11.5px] text-fg-3">
          <span>{label}</span>
          <span className="font-mono tabular-nums text-fg-4">{Math.round(pct)}%</span>
        </div>
      ) : null}
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
        aria-label={label ?? `Progress ${Math.round(pct).toString()}%`}
        className="h-1 w-full overflow-hidden rounded bg-bg-elev-3"
      >
        <div
          data-testid="progress-bar-fill"
          className={cn("h-full rounded transition-[width] duration-300", FILL_CLASSES[variant])}
          style={{ width: `${pct.toString()}%` }}
        />
      </div>
    </div>
  );
}
