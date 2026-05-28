import { clampGaugeValue, gaugeColorClass } from "@/components/shared/gauge-utils";
import { cn } from "@/lib/utils";

export interface GaugeProps {
  /** 0..100 — clamped at the edges. */
  value: number;
  label?: string;
  sublabel?: string;
  className?: string;
}

interface InternalGaugeProps extends GaugeProps {
  size: number;
  stroke: number;
  /** Test id forwarded to the wrapper. */
  testId: string;
}

function GaugeBase({
  value,
  label,
  sublabel,
  size,
  stroke,
  testId,
  className,
}: InternalGaugeProps): React.ReactElement {
  const pct = clampGaugeValue(value);
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - pct / 100);
  const colorClass = gaugeColorClass(pct);

  return (
    <div
      data-testid={testId}
      data-value={Math.round(pct)}
      className={cn("relative inline-flex flex-col items-center justify-center", className)}
      style={{ width: size, height: size }}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size.toString()} ${size.toString()}`}
        className={cn("-rotate-90", colorClass)}
        aria-hidden="true"
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="currentColor"
          strokeOpacity="0.15"
          strokeWidth={stroke}
          fill="none"
        />
        <circle
          data-testid={`${testId}-arc`}
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="currentColor"
          strokeWidth={stroke}
          strokeLinecap="round"
          fill="none"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          style={{ transition: "stroke-dashoffset 300ms ease-out" }}
        />
      </svg>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
        <span className="font-mono text-[20px] font-semibold tabular-nums text-fg-1">
          {Math.round(pct)}
        </span>
        {label ? (
          <span className="text-[11px] uppercase tracking-wide text-fg-4">{label}</span>
        ) : null}
        {sublabel ? <span className="text-[10.5px] text-fg-5">{sublabel}</span> : null}
      </div>
    </div>
  );
}

/**
 * 120px radial gauge (UI_SPEC § 4.6). Color thresholds:
 *   - ≥ 80 → accent
 *   - 60–79 → amber
 *   - < 60 → red
 */
export function Gauge(props: GaugeProps): React.ReactElement {
  return <GaugeBase {...props} size={120} stroke={10} testId="gauge" />;
}

/** 90×90 compact variant used in analytics rows. */
export function SmallGauge(props: GaugeProps): React.ReactElement {
  return <GaugeBase {...props} size={90} stroke={8} testId="small-gauge" />;
}
