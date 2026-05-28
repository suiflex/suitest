import { Send, Sparkles } from "lucide-react";

import { Gated } from "@/components/gating/Gated";
import { Button } from "@/components/ui/button";
import { useCapabilities } from "@/stores/use-capabilities";

/**
 * Right-rail agent panel (380px). Wrapped in `<Gated feature="ai_conversation">`
 * so it renders `null` in ZERO tier and the layout grid collapses (handled
 * upstream in `_app.tsx`). In LOCAL/CLOUD it renders a static placeholder —
 * real streaming, threads, and composer ship in M3.
 */
export function AiPanel(): React.ReactElement {
  return (
    <Gated feature="ai_conversation" fallback={null}>
      <AiPanelInner />
    </Gated>
  );
}

function AiPanelInner(): React.ReactElement {
  const capabilities = useCapabilities((s) => s.capabilities);
  const provider = capabilities?.llm?.provider ?? "unknown";
  const model = capabilities?.llm?.model ?? "—";
  const autonomy = capabilities?.autonomy.default ?? "manual";

  return (
    <aside
      className="flex h-screen w-[380px] flex-col border-l border-border-subtle bg-bg-elev-1"
      data-testid="ai-panel"
    >
      {/* Header (47px) */}
      <div className="flex h-[47px] items-center gap-2 border-b border-border-subtle px-4">
        <span
          className="flex h-7 w-7 items-center justify-center rounded-full bg-accent/15 text-accent"
          aria-hidden="true"
        >
          <Sparkles className="h-4 w-4" />
        </span>
        <div className="flex min-w-0 flex-col">
          <span className="truncate text-[12.5px] font-semibold text-fg-1">Suitest Agent</span>
          <span
            className="truncate font-mono text-[10.5px] text-fg-4"
            data-testid="ai-panel-subtitle"
          >
            {provider}:{model} · {autonomy}
          </span>
        </div>
      </div>

      {/* Thread (scrollable) */}
      <div className="flex-1 overflow-y-auto px-4 py-4" data-testid="ai-panel-thread">
        <div className="rounded-md border border-border bg-bg-elev-2 px-3 py-2.5">
          <div className="mb-1 text-[10px] font-medium uppercase tracking-[0.07em] text-fg-5">
            Agent
          </div>
          <p className="text-[12.5px] text-fg-3">
            Hi — I&rsquo;m offline in M1b. Wire-up arrives in M3.
          </p>
        </div>
      </div>

      {/* Composer (disabled placeholder) */}
      <div className="border-t border-border-subtle p-3" data-testid="ai-panel-composer">
        <div className="flex items-end gap-2">
          <textarea
            disabled
            rows={2}
            placeholder="Composer enabled in M3"
            className="flex-1 resize-none rounded-md border border-border bg-bg-elev-2 px-2 py-1.5 text-[12.5px] text-fg-3 placeholder:text-fg-5 disabled:cursor-not-allowed"
            data-testid="ai-panel-composer-input"
          />
          <Button
            type="button"
            size="icon-sm"
            variant="outline"
            disabled
            aria-label="Send"
            className="border-border bg-bg-elev-2 text-fg-4"
            data-testid="ai-panel-send"
          >
            <Send className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        </div>
      </div>
    </aside>
  );
}
