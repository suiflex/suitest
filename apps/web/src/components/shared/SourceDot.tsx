import { cn } from "@/lib/utils";

export type SourceDotStatus = "pass" | "fail" | "warn" | "running" | "neutral";

export interface SourceDotProps {
  status: SourceDotStatus;
  className?: string;
  /** Optional tooltip / a11y label. */
  title?: string;
}

const DOT_CLASSES: Record<SourceDotStatus, string> = {
  pass: "bg-accent",
  fail: "bg-red",
  warn: "bg-amber",
  running: "bg-blue suitest-pulse",
  neutral: "bg-fg-4",
};

/**
 * Tiny 6×6 status dot used inside Test Case tree rows (UI_SPEC § 4.3).
 */
export function SourceDot({
  status,
  className,
  title,
}: SourceDotProps): React.ReactElement {
  return (
    <span
      data-testid="source-dot"
      data-status={status}
      role={title ? "img" : undefined}
      aria-label={title}
      title={title}
      className={cn(
        "inline-block h-1.5 w-1.5 shrink-0 rounded-full",
        DOT_CLASSES[status],
        className,
      )}
    />
  );
}
