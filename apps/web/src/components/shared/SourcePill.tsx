import { cn } from "@/lib/utils";

export type SourceKind = "MANUAL" | "AI" | "MCP" | "IMPORT";

export interface SourcePillProps {
  source: SourceKind;
  className?: string;
}

const SOURCE_CLASSES: Record<SourceKind, string> = {
  MANUAL: "bg-bg-elev-2 text-fg-3 border-border",
  AI: "bg-violet/10 text-violet border-violet/20",
  MCP: "bg-blue/10 text-blue border-blue/20",
  IMPORT: "bg-amber/10 text-amber border-amber/20",
};

/**
 * Source label pill (UI_SPEC § 4.4). Used in case tree rows + run detail to
 * indicate the origin of a test case or step.
 */
export function SourcePill({
  source,
  className,
}: SourcePillProps): React.ReactElement {
  return (
    <span
      data-testid="source-pill"
      data-source={source}
      className={cn(
        "inline-flex items-center rounded-full border px-1.5 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wide",
        SOURCE_CLASSES[source],
        className,
      )}
    >
      {source}
    </span>
  );
}
