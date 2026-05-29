import { useEffect, useRef, type MutableRefObject } from "react";

import { cn } from "@/lib/utils";

export interface LogLine {
  stepIndex: number;
  level: string;
  message: string;
  time: string;
}

interface LogPaneProps {
  logs: LogLine[];
  /**
   * Mutable flag shared with the parent. The parent reads it to decide whether
   * to refocus the pane on user-driven actions. The pane itself flips the
   * value to `false` when the user scrolls up away from the bottom and back to
   * `true` when they scroll all the way down.
   */
  autoScrollRef: MutableRefObject<boolean>;
}

function levelColor(level: string): string {
  switch (level.toUpperCase()) {
    case "ERROR":
      return "text-red";
    case "WARN":
    case "WARNING":
      return "text-amber";
    case "PASS":
    case "OK":
      return "text-accent";
    case "DEBUG":
      return "text-fg-5";
    default:
      return "text-fg-1";
  }
}

/**
 * Append-only log stream. The view tracks user-driven scroll: scrolling up
 * disables auto-scroll so we don't yank the viewport away from the user;
 * scrolling back to the bottom re-enables it. This matches the behavior
 * described in the M1c plan §19.2.
 */
export function LogPane({ logs, autoScrollRef }: LogPaneProps): React.ReactElement {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    if (!autoScrollRef.current) return;
    // Scroll to the bottom on every new log line. Using `scrollTop` instead
    // of `scrollIntoView` so it works inside jsdom + the radix ScrollArea
    // viewport without focus stealing.
    el.scrollTop = el.scrollHeight;
  }, [logs, autoScrollRef]);

  function handleScroll(): void {
    const el = containerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 4;
    autoScrollRef.current = atBottom;
  }

  return (
    <div
      data-testid="log-pane"
      className="flex h-[280px] flex-col rounded-md border border-border bg-[#060606]"
    >
      <div
        ref={containerRef}
        onScroll={handleScroll}
        data-testid="log-pane-scroller"
        className="flex-1 overflow-auto p-[14px] font-mono text-[11.5px] leading-relaxed"
      >
        {logs.length === 0 ? (
          <div className="text-fg-5">No log lines yet.</div>
        ) : (
          logs.map((l, i) => (
            <div
              key={`${l.time}-${i.toString()}`}
              data-testid="log-line"
              className="flex gap-2"
            >
              <span className="text-fg-5">{l.time}</span>
              <span className={cn("font-semibold", levelColor(l.level))}>
                [{l.level.toUpperCase()}]
              </span>
              <span className="text-fg-3">step {l.stepIndex.toString()}</span>
              <span className="text-fg-1">{l.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
