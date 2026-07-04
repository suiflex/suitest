import { Send, Sparkles } from "lucide-react";
import { useRef, useState } from "react";

import { Gated } from "@/components/gating/Gated";
import { Button } from "@/components/ui/button";
import { type ChatMessageInput, type ChatToolEvent, streamChat } from "@/lib/chat-client";
import { useCapabilities } from "@/stores/use-capabilities";

/**
 * Right-rail agent panel (380px). Wrapped in `<Gated feature="ai_conversation">`
 * so it renders `null` in ZERO tier and the layout grid collapses (handled
 * upstream in `_app.tsx`). In LOCAL/CLOUD it streams a conversation-mode reply
 * over SSE (`POST /agent/chat`, M3-12 / M3-13).
 */
export function AiPanel(): React.ReactElement {
  return (
    <Gated feature="ai_conversation" fallback={null}>
      <AiPanelInner />
    </Gated>
  );
}

interface ChatTurn {
  role: "user" | "assistant";
  content: string;
  /** Pending tool-call request surfaced as a confirm card (autonomy hard rail). */
  tool?: ChatToolEvent;
}

function AiPanelInner(): React.ReactElement {
  const capabilities = useCapabilities((s) => s.capabilities);
  const provider = capabilities?.llm?.provider ?? "unknown";
  const model = capabilities?.llm?.model ?? "—";
  const autonomy = capabilities?.autonomy?.default ?? "manual";

  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const send = async (): Promise<void> => {
    const text = input.trim();
    if (!text || streaming) return;
    setError(null);
    setInput("");

    const history: ChatMessageInput[] = [
      ...turns.map((t) => ({ role: t.role, content: t.content }) satisfies ChatMessageInput),
      { role: "user", content: text },
    ];
    // Optimistically render the user turn + an empty assistant turn to fill.
    setTurns((prev) => [
      ...prev,
      { role: "user", content: text },
      { role: "assistant", content: "" },
    ]);
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    const appendDelta = (delta: string): void => {
      setTurns((prev) => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last && last.role === "assistant") {
          next[next.length - 1] = { ...last, content: last.content + delta };
        }
        return next;
      });
    };

    try {
      await streamChat(
        history,
        {
          onToken: appendDelta,
          onTool: (tool) => {
            setTurns((prev) => {
              const next = [...prev];
              const last = next[next.length - 1];
              if (last && last.role === "assistant") {
                next[next.length - 1] = { ...last, tool };
              }
              return next;
            });
          },
          onError: (message) => setError(message),
        },
        controller.signal,
      );
    } catch {
      setError("The chat stream was interrupted.");
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  };

  return (
    <aside
      className="hidden h-full w-[380px] shrink-0 flex-col border-l border-border-subtle bg-bg-elev-1 xl:flex"
      data-testid="ai-panel"
    >
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

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4" data-testid="ai-panel-thread">
        {turns.length === 0 ? (
          <div className="rounded-md border border-border bg-bg-elev-2 px-3 py-2.5">
            <div className="mb-1 text-[10px] font-medium uppercase tracking-[0.07em] text-fg-5">
              Agent
            </div>
            <p className="text-[12.5px] text-fg-3">
              Ask about cases, runs, defects, or coverage. I stream answers live.
            </p>
          </div>
        ) : null}

        {turns.map((turn, i) => (
          <div
            key={i}
            className={`rounded-md border px-3 py-2.5 ${
              turn.role === "user"
                ? "border-border-subtle bg-bg-elev-2"
                : "border-violet/30 bg-violet/5"
            }`}
          >
            <div className="mb-1 text-[10px] font-medium uppercase tracking-[0.07em] text-fg-5">
              {turn.role === "user" ? "You" : "Agent"}
            </div>
            <p className="whitespace-pre-wrap text-[12.5px] text-fg-2">
              {turn.content || (turn.role === "assistant" && streaming ? "…" : "")}
            </p>
            {turn.tool ? (
              <div className="mt-2 rounded border border-amber/30 bg-amber/10 px-2 py-1.5 text-[11.5px] text-amber">
                Agent wants to run <span className="font-mono">{turn.tool.tool}</span> — confirm
                required before any mutation.
              </div>
            ) : null}
          </div>
        ))}
      </div>

      {error ? (
        <div className="border-t border-border-subtle px-3 py-2 text-[11.5px] text-red">
          {error}
        </div>
      ) : null}

      <div className="border-t border-border-subtle p-3" data-testid="ai-panel-composer">
        <div className="flex items-end gap-2">
          <textarea
            rows={2}
            value={input}
            disabled={streaming}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            placeholder="Ask the agent…"
            className="flex-1 resize-none rounded-md border border-border bg-bg-elev-2 px-2 py-1.5 text-[12.5px] text-fg-1 placeholder:text-fg-5 outline-none focus:border-accent disabled:cursor-not-allowed disabled:opacity-60"
            data-testid="ai-panel-composer-input"
          />
          <Button
            type="button"
            size="icon-sm"
            variant="outline"
            disabled={streaming || input.trim().length === 0}
            aria-label="Send"
            onClick={() => void send()}
            className="border-border bg-bg-elev-2 text-fg-1"
            data-testid="ai-panel-send"
          >
            <Send className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
        </div>
      </div>
    </aside>
  );
}
