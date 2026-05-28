import { cn } from "@/lib/utils";
import { useCapabilities, type AutonomyLevel } from "@/stores/use-capabilities";

const LEVEL_LABEL: Record<AutonomyLevel, string> = {
  manual: "manual",
  assist: "assist",
  semi_auto: "semi-auto",
  auto: "auto",
};

const LEVEL_TONE: Record<AutonomyLevel, string> = {
  manual: "bg-bg-elev-2 text-fg-3 border-border",
  assist: "bg-blue/10 text-blue border-blue/20",
  semi_auto: "bg-violet/10 text-violet border-violet/20",
  auto: "bg-accent/10 text-accent border-accent/20",
};

/**
 * Autonomy mode chip (UI_SPEC § 4.12). Reads the default autonomy level from
 * `useCapabilities()` and renders e.g. "Mode: assist". Click navigates to
 * `/settings/automation`.
 */
export function AutonomyIndicator(): React.ReactElement {
  const level: AutonomyLevel =
    useCapabilities((s) => s.capabilities?.autonomy.default) ?? "manual";

  return (
    <a
      href="/settings/automation"
      data-testid="autonomy-indicator"
      data-level={level}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[11px] font-medium hover:opacity-90",
        LEVEL_TONE[level],
      )}
    >
      <span className="text-fg-4">Mode:</span>
      <span>{LEVEL_LABEL[level]}</span>
    </a>
  );
}
