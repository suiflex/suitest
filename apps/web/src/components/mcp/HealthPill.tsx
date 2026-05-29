import { cn } from "@/lib/utils";

export type HealthStatus = "ok" | "degraded" | "down" | "unknown";

interface HealthPillProps {
  status: HealthStatus;
  className?: string;
}

const DOT: Record<HealthStatus, string> = {
  ok: "bg-accent",
  degraded: "bg-amber",
  down: "bg-red",
  unknown: "bg-fg-4",
};

const LABEL: Record<HealthStatus, string> = {
  ok: "OK",
  degraded: "Degraded",
  down: "Down",
  unknown: "Unknown",
};

const TINT: Record<HealthStatus, string> = {
  ok: "text-accent",
  degraded: "text-amber",
  down: "text-red",
  unknown: "text-fg-4",
};

/** Tiny colored dot + label that mirrors the provider's WS-streamed health. */
export function HealthPill({ status, className }: HealthPillProps): React.ReactElement {
  return (
    <span
      data-testid="health-pill"
      data-status={status}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-border bg-bg-elev-1 px-2 py-0.5 font-mono text-[10.5px]",
        TINT[status],
        className,
      )}
    >
      <span
        aria-hidden="true"
        className={cn("inline-block h-1.5 w-1.5 shrink-0 rounded-full", DOT[status])}
      />
      {LABEL[status]}
    </span>
  );
}
