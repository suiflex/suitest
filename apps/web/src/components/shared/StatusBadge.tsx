import { cn } from "@/lib/utils";

export type StatusBadgeStatus = "pass" | "fail" | "warn" | "info" | "ai" | "running" | "neutral";

export interface StatusBadgeProps {
  status: StatusBadgeStatus;
  label?: string;
  /** When false, omit the colored dot prefix. Defaults to true. */
  withDot?: boolean;
  className?: string;
}

const STATUS_CLASSES: Record<StatusBadgeStatus, string> = {
  pass: "bg-accent/10 text-accent border border-accent/20",
  fail: "bg-red/10 text-red border border-red/20",
  warn: "bg-amber/10 text-amber border border-amber/20",
  info: "bg-blue/10 text-blue border border-blue/20",
  ai: "bg-violet/10 text-violet border border-violet/20",
  running: "bg-blue/10 text-blue border border-blue/20",
  neutral: "bg-bg-elev-2 text-fg-3 border border-border",
};

const DOT_CLASSES: Record<StatusBadgeStatus, string> = {
  pass: "bg-accent",
  fail: "bg-red",
  warn: "bg-amber",
  info: "bg-blue",
  ai: "bg-violet",
  running: "bg-blue",
  neutral: "bg-fg-4",
};

const DEFAULT_LABEL: Record<StatusBadgeStatus, string> = {
  pass: "Pass",
  fail: "Fail",
  warn: "Warn",
  info: "Info",
  ai: "AI",
  running: "Running",
  neutral: "—",
};

/**
 * Small pill used for run/test statuses. Renders a colored dot + label inside
 * a tinted pill. See UI_SPEC § 4.1.
 */
export function StatusBadge({
  status,
  label,
  withDot = true,
  className,
}: StatusBadgeProps): React.ReactElement {
  return (
    <span
      data-testid="status-badge"
      data-status={status}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium",
        STATUS_CLASSES[status],
        className,
      )}
    >
      {withDot ? (
        <span
          aria-hidden="true"
          className={cn(
            "h-2 w-2 shrink-0 rounded-full",
            DOT_CLASSES[status],
            // A running test is live — pulse the dot so it reads as in-progress.
            status === "running" && "suitest-pulse",
          )}
          data-testid="status-badge-dot"
        />
      ) : null}
      <span>{label ?? DEFAULT_LABEL[status]}</span>
    </span>
  );
}
