import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

interface CopyButtonProps {
  /** Text written to the clipboard on click. */
  value: string;
  /** Accessible label; defaults to "Copy". */
  label?: string;
  className?: string;
}

/**
 * Small copy-to-clipboard button for one-time invite links, reset links, and
 * temporary passwords (M1e). Shows a transient check state for 1.5s after a
 * successful copy, and falls back silently when `navigator.clipboard` is
 * unavailable (the value stays visible for manual selection).
 */
export function CopyButton({
  value,
  label = "Copy",
  className,
}: CopyButtonProps): React.ReactElement {
  const [copied, setCopied] = useState(false);

  const onCopy = async (): Promise<void> => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard blocked (insecure context / permissions) — no-op.
    }
  };

  return (
    <button
      type="button"
      aria-label={label}
      onClick={() => {
        void onCopy();
      }}
      className={cn(
        "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-border bg-bg-elev-1 px-2.5 text-[12px] font-medium text-fg-1 hover:bg-bg-elev-2",
        className,
      )}
      data-testid="copy-button"
    >
      {copied ? (
        <Check className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
      ) : (
        <Copy className="h-3.5 w-3.5 text-fg-3" aria-hidden="true" />
      )}
      <span>{copied ? "Copied" : label}</span>
    </button>
  );
}
