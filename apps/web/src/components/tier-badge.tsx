import { cn } from "@/lib/utils";
import { useCapabilities } from "@/stores/use-capabilities";

export function TierBadge(): React.ReactElement {
  const capabilities = useCapabilities((s) => s.capabilities);
  const tier = capabilities?.tier ?? "ZERO";
  const provider = capabilities?.llm?.provider ?? null;

  const tone = {
    ZERO: "bg-elev-2 text-fg-3 border-border",
    LOCAL: "bg-elev-2 text-accent border-accent/40",
    CLOUD: "bg-elev-2 text-violet border-violet/40",
  }[tier];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-md border px-2 py-1 font-mono text-xs",
        tone,
      )}
      data-testid="tier-badge"
    >
      <span className="font-semibold">{tier}</span>
      {provider ? <span className="text-fg-4">· {provider}</span> : null}
    </span>
  );
}
