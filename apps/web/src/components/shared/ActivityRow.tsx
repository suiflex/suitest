import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type ActivityTone = "accent" | "amber" | "red" | "violet" | "blue" | "neutral";

export interface ActivityRowProps {
  icon: LucideIcon;
  tone: ActivityTone;
  text: ReactNode;
  time: string;
  actions?: ReactNode;
  className?: string;
}

const TONE_CLASSES: Record<ActivityTone, string> = {
  accent: "bg-accent/10 text-accent",
  amber: "bg-amber/10 text-amber",
  red: "bg-red/10 text-red",
  violet: "bg-violet/10 text-violet",
  blue: "bg-blue/10 text-blue",
  neutral: "bg-bg-elev-2 text-fg-3",
};

/**
 * One row of an activity / audit feed (UI_SPEC § 4.7). Used in dashboard
 * agent activity, inbox, and run timelines.
 */
export function ActivityRow({
  icon: Icon,
  tone,
  text,
  time,
  actions,
  className,
}: ActivityRowProps): React.ReactElement {
  return (
    <div
      data-testid="activity-row"
      data-tone={tone}
      className={cn(
        "flex items-start gap-3 rounded-md px-2 py-1.5 hover:bg-bg-elev-2",
        className,
      )}
    >
      <span
        aria-hidden="true"
        className={cn(
          "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full",
          TONE_CLASSES[tone],
        )}
      >
        <Icon className="h-3.5 w-3.5" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="text-[12.5px] leading-tight text-fg-1">{text}</div>
        <div className="font-mono text-[11px] text-fg-5">{time}</div>
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-1">{actions}</div> : null}
    </div>
  );
}
