/**
 * Checkbox — dep-free styled native <input type="checkbox">.
 *
 * Supports:
 *   - `checked` / `onCheckedChange` (shadcn-compat) OR standard `onChange`
 *   - `indeterminate` prop (sets HTMLInputElement.indeterminate via ref)
 *   - `forwardRef` for external access
 *
 * Design tokens: bg-bg-elev-2, border-border, accent. No new dependencies.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

export interface CheckboxProps extends Omit<React.ComponentProps<"input">, "type" | "onChange"> {
  /** Shadcn-compat callback; called with the new boolean checked state. */
  onCheckedChange?: (checked: boolean) => void;
  /** Standard input onChange (optional; prefer onCheckedChange). */
  onChange?: React.ChangeEventHandler<HTMLInputElement>;
  /** Sets the indeterminate visual state (three-state checkbox). */
  indeterminate?: boolean;
}

const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ className, onCheckedChange, onChange, indeterminate, ...props }, ref) => {
    const innerRef = React.useRef<HTMLInputElement>(null);

    // Merge the forwarded ref with our inner ref so we can set indeterminate.
    React.useImperativeHandle(ref, () => innerRef.current as HTMLInputElement);

    // Sync indeterminate state imperatively (not supported as HTML attribute).
    React.useEffect(() => {
      if (innerRef.current) {
        innerRef.current.indeterminate = indeterminate ?? false;
      }
    }, [indeterminate]);

    const handleChange: React.ChangeEventHandler<HTMLInputElement> = (e) => {
      onCheckedChange?.(e.target.checked);
      onChange?.(e);
    };

    return (
      <input
        type="checkbox"
        ref={innerRef}
        data-slot="checkbox"
        className={cn(
          // Size + shape
          "h-4 w-4 shrink-0 cursor-pointer rounded-sm",
          // Colors using design tokens
          "border border-border bg-bg-elev-2",
          "accent-accent",
          // Focus ring
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
          // Disabled state
          "disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
        onChange={handleChange}
        {...props}
      />
    );
  },
);

Checkbox.displayName = "Checkbox";

export { Checkbox };
