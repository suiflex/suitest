import { Loader2, Send, ShieldAlert, Sparkles, Zap } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Gated } from "@/components/gating/Gated";
import { Button } from "@/components/ui/button";
import { fetchLlmModels } from "@/lib/api-client";
import {
  fetchChatHistory,
  streamChat,
  stripToolEnvelopes,
  type ChatMessageInput,
  type ChatToolEvent,
} from "@/lib/chat-client";
import { providerLabel } from "@/lib/llm-vendors";
import { useActiveWorkspace } from "@/stores/use-active-workspace";
import { useCapabilities } from "@/stores/use-capabilities";

/**
 * Right-rail agent panel (380px). Wrapped in `<Gated feature="ai_conversation">`
 * so it renders `null` in ZERO tier and the layout grid collapses (handled
 * upstream in `_app.tsx`). In LOCAL/CLOUD it streams a conversation-mode reply
 * over SSE (`POST /agent/chat`, M3-12 / M3-13).
 *
 * The thread is stored server-side keyed by `agent_session_id` and restored on
 * mount, so a reload keeps the conversation. Pending mutation tool cards offer
 * Approve / Reject: approving re-sends the tool envelope with the user's
 * confirmation; rejecting tells the agent to drop it. The "auto-approve" toggle
 * next to Send applies proposed edits without the per-card click — the toggle
 * itself is the explicit human decision (AUTONOMY.md), surfaced with a warning.
 */

const SESSION_KEY = "suitest.agentSessionId";
const AUTO_APPROVE_KEY = "suitest.agentAutoApprove";
/** Panel-local model pick. Deliberately not the workspace config: switching
 *  models here must not move the runner and the generators with it. */
const MODEL_KEY = "suitest.agentModel";
/** Tools that mutate a case — only these need (or can be auto-) approved. */
const MUTATION_TOOLS = new Set(["case.set_steps", "case.update_meta"]);
/** Stop an auto-approve chain from running away across model rounds. */
const AUTO_CHAIN_LIMIT = 6;

function readAutoApprove(): boolean {
  try {
    return localStorage.getItem(AUTO_APPROVE_KEY) === "1";
  } catch {
    return false;
  }
}

function readModel(): string | null {
  try {
    return localStorage.getItem(MODEL_KEY);
  } catch {
    return null;
  }
}

interface ChatTurn {
  role: "user" | "assistant";
  content: string;
  /** Pending tool-call request surfaced as a confirm card (autonomy hard rail). */
  tool?: ChatToolEvent;
}

export function AiPanel(): React.ReactElement {
  return (
    <Gated feature="ai_conversation" fallback={null}>
      <AiPanelInner />
    </Gated>
  );
}

function ThinkingDots(): React.ReactElement {
  return (
    <span className="inline-flex items-center gap-1 py-1" aria-label="Agent is working">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1.5 w-1.5 animate-pulse rounded-full bg-fg-4"
          style={{ animationDelay: `${i * 150}ms` }}
        />
      ))}
    </span>
  );
}

function AiPanelInner(): React.ReactElement {
  const capabilities = useCapabilities((s) => s.capabilities);
  const provider = capabilities?.llm?.provider
    ? providerLabel(capabilities.llm.provider)
    : "unknown";
  const configuredModel = capabilities?.llm?.model ?? null;
  const providerKey = capabilities?.llm?.provider ?? null;
  const workspaceId = useActiveWorkspace((s) => s.workspaceId);
  const autonomy = capabilities?.autonomy?.default ?? "manual";

  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState<string | null>(readModel);
  // Membership is asked on every render and in the effects below, and the list
  // is whatever the provider offers — so index it once per change rather than
  // scanning it each time.
  const offered = useMemo(() => new Set(models), [models]);
  // The configured model may predate the catalog; it still belongs in the list.
  const options = useMemo(
    () =>
      configuredModel !== null && !offered.has(configuredModel)
        ? [configuredModel, ...models]
        : models,
    [configuredModel, offered, models],
  );

  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [autoApprove, setAutoApprove] = useState(readAutoApprove);
  const abortRef = useRef<AbortController | null>(null);
  const sessionRef = useRef<string | null>(localStorage.getItem(SESSION_KEY));
  const threadEndRef = useRef<HTMLDivElement>(null);
  // Mirrors for the async stream callbacks, which capture stale state otherwise.
  const autoApproveRef = useRef(autoApprove);
  // Mirrors the *effective* pick for the async stream callbacks, which capture
  // stale state. Null unless the provider actually offers it: a pick remembered
  // from a workspace on another vendor would otherwise be sent and refused.
  const modelRef = useRef<string | null>(null);
  const pendingToolRef = useRef<ChatToolEvent | null>(null);
  const autoChainRef = useRef(0);

  useEffect(() => {
    autoApproveRef.current = autoApprove;
  }, [autoApprove]);

  useEffect(() => {
    modelRef.current = model !== null && offered.has(model) ? model : null;
  }, [model, offered]);

  // The models this provider offers, for the picker. A provider with no
  // catalog (or a failed read) leaves the list empty and the header falls back
  // to naming the configured model, as it did before there was a picker.
  useEffect(() => {
    if (!workspaceId || !providerKey) return;
    let live = true;
    void fetchLlmModels(workspaceId, providerKey)
      .then((found) => {
        if (live) setModels(found.map((m) => m.id));
      })
      .catch(() => {
        if (live) setModels([]);
      });
    return () => {
      live = false;
    };
  }, [workspaceId, providerKey]);

  // Drop a remembered pick this provider does not offer — the workspace may
  // have been re-pointed at a different vendor since it was stored.
  useEffect(() => {
    if (models.length === 0 || model === null || offered.has(model)) return;
    setModel(null);
    try {
      localStorage.removeItem(MODEL_KEY);
    } catch {
      /* private mode — in-memory only */
    }
  }, [models, model, offered]);

  // Keep the newest turn / streamed token in view.
  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ block: "end" });
  }, [turns, streaming]);

  // Restore the last conversation on mount so a reload keeps the thread.
  useEffect(() => {
    const saved = sessionRef.current;
    if (!saved) {
      setLoading(false);
      return;
    }
    void fetchChatHistory(saved).then((history) => {
      setTurns(history.map((m) => ({ role: m.role as ChatTurn["role"], content: m.content })));
      setLoading(false);
    });
  }, []);

  const pickModel = (next: string): void => {
    setModel(next);
    try {
      localStorage.setItem(MODEL_KEY, next);
    } catch {
      /* private mode — in-memory only */
    }
  };

  const toggleAutoApprove = (): void => {
    setAutoApprove((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(AUTO_APPROVE_KEY, next ? "1" : "0");
      } catch {
        /* private mode — in-memory only */
      }
      return next;
    });
  };

  const send = async (): Promise<void> => {
    const text = input.trim();
    if (!text || streaming) return;
    autoChainRef.current = 0; // fresh user turn — reset the auto-approve budget
    setInput("");
    await runTurn(text);
  };

  /** Approve a pending mutation: send only the server-issued call id. */
  const approveTool = (tool: ChatToolEvent): void => {
    if (streaming || !tool.call_id) return;
    clearPendingTool(tool);
    void runTurn("Approved — apply it.", { approvedTool: tool });
  };

  /** Reject a pending mutation: tell the agent to drop the request. */
  const rejectTool = (tool: ChatToolEvent): void => {
    clearPendingTool(tool);
    void runTurn(`Rejected the ${tool.tool} request — do not apply it.`);
  };
  const clearPendingTool = (tool: ChatToolEvent): void => {
    setTurns((prev) =>
      prev.map((t) => {
        if (t.tool !== tool) return t;
        const rest: ChatTurn = { ...t };
        delete rest.tool;
        return rest;
      }),
    );
  };

  const runTurn = async (
    text: string,
    options?: { approvedTool?: ChatToolEvent },
  ): Promise<void> => {
    setError(null);
    pendingToolRef.current = null;
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
          onProgress: (sessionId) => {
            sessionRef.current = sessionId;
            localStorage.setItem(SESSION_KEY, sessionId);
          },
          onToken: appendDelta,
          onTool: (tool) => {
            pendingToolRef.current = tool;
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
        {
          approvedTool: options?.approvedTool ?? null,
          sessionId: sessionRef.current,
          model: modelRef.current,
        },
      );
    } catch {
      setError("The chat stream was interrupted.");
    } finally {
      setStreaming(false);
      abortRef.current = null;
      maybeAutoApprove();
    }
  };

  /** After a stream settles: apply the proposed edit if auto-approve is on. */
  const maybeAutoApprove = (): void => {
    const pending = pendingToolRef.current;
    pendingToolRef.current = null;
    if (
      !autoApproveRef.current ||
      pending === null ||
      !pending.call_id ||
      !MUTATION_TOOLS.has(pending.tool) ||
      autoChainRef.current >= AUTO_CHAIN_LIMIT
    ) {
      return;
    }
    autoChainRef.current += 1;
    // Defer so the streaming=false state flush lands before the next run.
    setTimeout(() => {
      clearPendingTool(pending);
      void runTurn("Approved — apply it.", { approvedTool: pending });
    }, 0);
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
          {models.length > 0 ? (
            <span className="flex min-w-0 items-center gap-1 font-mono text-[10.5px] text-fg-4">
              <select
                value={model ?? configuredModel ?? ""}
                onChange={(e) => pickModel(e.target.value)}
                aria-label="Model"
                title={`${provider} · ${autonomy}`}
                data-testid="ai-panel-model"
                className="min-w-0 max-w-[150px] truncate rounded border border-transparent bg-transparent font-mono text-[10.5px] text-fg-4 outline-none hover:border-border focus:border-accent"
              >
                {options.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
              <span className="shrink-0">· {autonomy}</span>
            </span>
          ) : (
            <span
              className="truncate font-mono text-[10.5px] text-fg-4"
              data-testid="ai-panel-subtitle"
            >
              {provider}:{configuredModel ?? "—"} · {autonomy}
            </span>
          )}
        </div>
        {turns.length > 0 ? (
          <button
            type="button"
            aria-label="Clear conversation"
            data-testid="ai-panel-clear"
            onClick={() => {
              sessionRef.current = null;
              localStorage.removeItem(SESSION_KEY);
              setTurns([]);
            }}
            className="ml-auto rounded-md px-2 py-1 text-[11px] text-fg-4 hover:bg-bg-elev-2 hover:text-fg-1"
          >
            New chat
          </button>
        ) : null}
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto px-4 py-4" data-testid="ai-panel-thread">
        {loading ? (
          <div className="rounded-md border border-border bg-bg-elev-2 px-3 py-2.5 text-[12px] text-fg-4">
            Restoring conversation…
          </div>
        ) : null}
        {!loading && turns.length === 0 ? (
          <div className="rounded-md border border-border bg-bg-elev-2 px-3 py-2.5">
            <div className="mb-1 text-[10px] font-medium uppercase tracking-[0.07em] text-fg-5">
              Agent
            </div>
            <p className="text-[12.5px] text-fg-3">
              Ask about cases, runs, defects, or coverage — or ask me to edit a test case and
              I&apos;ll propose the change for your approval.
            </p>
          </div>
        ) : null}

        {turns.map((turn, i) => {
          const body = turn.role === "assistant" ? stripToolEnvelopes(turn.content) : turn.content;
          const isLast = i === turns.length - 1;
          return (
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
              {body ? (
                <p className="whitespace-pre-wrap text-[12.5px] text-fg-2">{body}</p>
              ) : turn.role === "assistant" && streaming && isLast ? (
                <ThinkingDots />
              ) : null}
              {turn.tool ? (
                <div
                  className="mt-2 rounded border border-amber/30 bg-amber/10 px-2 py-1.5 text-[11.5px] text-amber"
                  data-testid="ai-tool-confirm"
                >
                  <p className="mb-1.5">
                    Agent wants to run{" "}
                    <span className="font-mono font-semibold">{turn.tool.tool}</span>
                    {turn.tool.tool === "case.set_steps" || turn.tool.tool === "case.update_meta"
                      ? " — review the arguments above before approving."
                      : "."}
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      data-testid="ai-tool-approve"
                      disabled={streaming}
                      onClick={() => {
                        const t = turn.tool;
                        if (t) void approveTool(t);
                      }}
                      className="rounded-md bg-accent px-2.5 py-1 text-[11.5px] font-medium text-accent-fg hover:opacity-90 disabled:opacity-50"
                    >
                      Approve &amp; run
                    </button>
                    <button
                      type="button"
                      data-testid="ai-tool-reject"
                      disabled={streaming}
                      onClick={() => {
                        const t = turn.tool;
                        if (t) rejectTool(t);
                      }}
                      className="rounded-md border border-border bg-bg-elev-1 px-2.5 py-1 text-[11.5px] font-medium text-fg-2 hover:bg-bg-elev-2 disabled:opacity-50"
                    >
                      Reject
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          );
        })}
        <div ref={threadEndRef} />
      </div>

      {streaming ? (
        <div
          className="flex items-center gap-2 border-t border-border-subtle px-3 py-1.5 text-[11px] text-fg-4"
          data-testid="ai-panel-working"
          aria-live="polite"
        >
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
          Agent is working…
        </div>
      ) : null}

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
            variant={autoApprove ? "default" : "outline"}
            aria-pressed={autoApprove}
            aria-label="Auto-approve agent edits"
            title={
              autoApprove
                ? "Auto-approve is ON — proposed edits apply without asking"
                : "Auto-approve agent edits"
            }
            onClick={toggleAutoApprove}
            className={autoApprove ? "" : "border-border bg-bg-elev-2 text-fg-1"}
            data-testid="ai-panel-autoapprove"
          >
            <Zap className="h-3.5 w-3.5" aria-hidden="true" />
          </Button>
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
        {autoApprove ? (
          <p
            className="mt-1.5 flex items-center gap-1 text-[10.5px] text-amber"
            data-testid="ai-panel-autoapprove-warning"
          >
            <ShieldAlert className="h-3 w-3 shrink-0" aria-hidden="true" />
            Auto-approving agent edits without confirmation
          </p>
        ) : null}
      </div>
    </aside>
  );
}
