import type { ReactElement } from "react";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export interface DisabledTooltipProps {
  reason: string;
  children: ReactElement;
}

/**
 * Wrap a disabled control so a tooltip explains why it's disabled (UI_SPEC
 * § 4.14). The inner element is rendered inside a focusable `<span>` so the
 * tooltip can fire on hover/focus even when the underlying button has
 * `pointer-events: none` (the default for `disabled`).
 *
 * The wrapper also stamps `aria-disabled="true"` for AT and uses
 * `pointer-events-none` to forward pointer state to the wrapper element.
 */
export function DisabledTooltip({
  reason,
  children,
}: DisabledTooltipProps): React.ReactElement {
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            tabIndex={0}
            aria-disabled="true"
            data-testid="disabled-tooltip-wrapper"
            className="inline-flex [&>*]:pointer-events-none"
          >
            {children}
          </span>
        </TooltipTrigger>
        <TooltipContent data-testid="disabled-tooltip-content">{reason}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
