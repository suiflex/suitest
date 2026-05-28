import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { useCapabilities, type Tier } from "@/stores/use-capabilities";

const TIER_TONE: Record<Tier, string> = {
  ZERO: "bg-bg-elev-2 text-fg-3 border-border",
  LOCAL: "bg-blue/10 text-blue border-blue/20",
  CLOUD: "bg-violet/10 text-violet border-violet/20",
};

/**
 * Topbar capability chip (UI_SPEC § 1.6, § 4.11). Reads `useCapabilities()`
 * and renders a colored pill per tier. Clicking the chip opens a Popover with
 * provider/model details + a "Configure" link to `/settings/llm`.
 *
 * Consolidated from the M0 `apps/web/src/components/tier-badge.tsx` into the
 * canonical `shared/` location per M1b Task 6.10.
 */
export function TierBadge(): React.ReactElement {
  const capabilities = useCapabilities((s) => s.capabilities);
  const tier: Tier = capabilities?.tier ?? "ZERO";
  // Defense-in-depth: use deep optional chaining so malformed/partial responses
  // (e.g. HTML when Vite proxy is misconfigured, mock fixtures missing fields)
  // don't crash the topbar. Falls back to "ZERO" via the tier default above.
  const provider = capabilities?.llm?.provider ?? null;
  const model = capabilities?.llm?.model ?? null;
  const providerModel = provider && model ? `${provider}:${model}` : provider;
  const label = tier === "ZERO" || !providerModel ? tier : `${tier} · ${providerModel}`;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="tier-badge"
          data-tier={tier}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[11px] font-medium",
            TIER_TONE[tier],
          )}
        >
          {label}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-72 border-border bg-bg-elev-1 p-3"
        data-testid="tier-badge-popover"
      >
        <div className="flex flex-col gap-2">
          <div className="text-[11px] uppercase tracking-wide text-fg-5">Capability tier</div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-[13px] font-semibold text-fg-1">{tier}</span>
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12.5px]">
            <dt className="text-fg-4">Provider</dt>
            <dd className="font-mono text-fg-1">{provider ?? "—"}</dd>
            <dt className="text-fg-4">Model</dt>
            <dd className="font-mono text-fg-1">{model ?? "—"}</dd>
          </dl>
          <a
            href="/settings/llm"
            className="mt-1 inline-flex w-fit text-[12.5px] text-accent hover:underline"
            data-testid="tier-badge-configure"
          >
            Configure →
          </a>
        </div>
      </PopoverContent>
    </Popover>
  );
}
