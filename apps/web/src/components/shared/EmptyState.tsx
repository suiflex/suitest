import type { LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface EmptyStateAction {
  label: string;
  onClick?: () => void;
  href?: string;
  variant?: "default" | "outline";
}

export interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  subtitle?: string;
  /** Single CTA, or an array for multi-CTA empty states (UI_SPEC § 6). */
  action?: EmptyStateAction | ReadonlyArray<EmptyStateAction>;
  className?: string;
}

/**
 * Centered icon + title + subtitle + optional CTA(s). Used wherever a list,
 * tab, or screen has no data to show.
 */
export function EmptyState({
  icon: Icon,
  title,
  subtitle,
  action,
  className,
}: EmptyStateProps): React.ReactElement {
  const actions = action == null ? [] : Array.isArray(action) ? [...action] : [action];

  return (
    <div
      data-testid="empty-state"
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-md border border-dashed border-border bg-bg-elev-1 px-6 py-10 text-center",
        className,
      )}
    >
      <span className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-bg-elev-2 text-fg-4">
        <Icon className="h-5 w-5" aria-hidden="true" />
      </span>
      <div className="flex flex-col gap-1">
        <div className="text-[13px] font-medium text-fg-1">{title}</div>
        {subtitle ? <div className="text-[12.5px] text-fg-3">{subtitle}</div> : null}
      </div>
      {actions.length > 0 ? (
        <div className="mt-1 flex flex-wrap items-center justify-center gap-2" data-testid="empty-state-actions">
          {actions.map((a, idx) =>
            a.href ? (
              <a
                key={`${a.label}-${idx.toString()}`}
                href={a.href}
                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-bg-elev-1 px-3 text-[12.5px] font-medium text-fg-1 hover:bg-bg-elev-2"
              >
                {a.label}
              </a>
            ) : (
              <Button
                key={`${a.label}-${idx.toString()}`}
                type="button"
                size="sm"
                variant={a.variant ?? "outline"}
                onClick={a.onClick}
              >
                {a.label}
              </Button>
            ),
          )}
        </div>
      ) : null}
    </div>
  );
}
