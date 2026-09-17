import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { providerLabel } from "@/lib/llm-vendors";
import { cn } from "@/lib/utils";
import { useCapabilities, type LlmStatus } from "@/stores/use-capabilities";

const STATUS_TONE: Record<LlmStatus, string> = {
  not_configured: "bg-bg-elev-2 text-fg-3 border-border",
  validation_required: "bg-amber/10 text-amber border-amber/20",
  ready: "bg-accent/10 text-accent border-accent/20",
};

const STATUS_LABEL: Record<LlmStatus, string> = {
  not_configured: "LLM not connected",
  validation_required: "LLM validation required",
  ready: "LLM ready",
};

export function LlmStatusBadge(): React.ReactElement {
  const capabilities = useCapabilities((state) => state.capabilities);
  const status = capabilities?.llm?.status ?? "not_configured";
  const provider = capabilities?.llm?.provider ?? null;
  const model = capabilities?.llm?.model ?? null;
  const providerName = provider ? providerLabel(provider) : null;
  const providerModel = providerName && model ? `${providerName}:${model}` : providerName;
  const label = status === "ready" && providerModel ? providerModel : STATUS_LABEL[status];

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="llm-status-badge"
          data-llm-status={status}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[11px] font-medium",
            STATUS_TONE[status],
          )}
        >
          {label}
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-72 border-border bg-bg-elev-1 p-3"
        data-testid="llm-status-badge-popover"
      >
        <div className="flex flex-col gap-2">
          <div className="text-[11px] uppercase tracking-wide text-fg-5">LLM status</div>
          <div className="text-[13px] font-semibold text-fg-1">{STATUS_LABEL[status]}</div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12.5px]">
            <dt className="text-fg-4">Provider</dt>
            <dd className="font-mono text-fg-1">{providerLabel(provider)}</dd>
            <dt className="text-fg-4">Model</dt>
            <dd className="font-mono text-fg-1">{model ?? "—"}</dd>
          </dl>
          <a href="/settings" className="mt-1 w-fit text-[12.5px] text-accent hover:underline">
            Configure →
          </a>
        </div>
      </PopoverContent>
    </Popover>
  );
}
