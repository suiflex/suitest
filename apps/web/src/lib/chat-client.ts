import { useActiveWorkspace } from "@/stores/use-active-workspace";

// ---------------------------------------------------------------------------
// Agent conversation (chat) client (M3-12 / M3-13).
//
// `POST /agent/chat` streams the assistant reply as SSE token frames; axios
// buffers the whole response, so we drive it with `fetch` + a manual SSE frame
// parser (same approach as the deterministic generator client). Tool-call
// requests arrive as a `tool` frame (also mirrored on the WS gateway).
// ---------------------------------------------------------------------------

export interface ChatMessageInput {
  role: "user" | "assistant" | "system" | "tool";
  content: string;
}

/** A line that is entirely (or starts as) a `{"tool": …}` request envelope. */
const TOOL_ENVELOPE_LINE = /^\s*[[{]?\s*\{\s*"tool"\s*:/;

/**
 * Strip inline tool-call syntax from an assistant turn before display: the model
 * sometimes narrates its calls as bare `{"tool": …}` JSON (or `<tool_call>` /
 * ```json fences). The structured `tool` SSE frame is what drives the confirm
 * card, so the raw JSON is just noise in the bubble.
 *
 * Line-based: the model emits each envelope on its own line, so dropping lines
 * that begin a tool object clears the noise without a brace-matching scan.
 */
export function stripToolEnvelopes(raw: string): string {
  return raw
    .replaceAll("<tool_call>", "")
    .replaceAll("</tool_call>", "")
    .replaceAll("```json", "")
    .replaceAll("```", "")
    .split("\n")
    .filter((line) => !TOOL_ENVELOPE_LINE.test(line))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export interface ChatToolEvent {
  tool: string;
  arguments: Record<string, unknown>;
  agent_session_id: string;
  /**
   * Opaque id of the server-recorded pending call for a mutating tool; `null`
   * for a read-only tool that already executed. Approval sends only this id —
   * the server reads the tool name + arguments back from its own row.
   */
  call_id?: string | null;
  requires_approval?: boolean;
}

export interface ChatDoneEvent {
  agent_session_id: string;
  content: string;
  tokens_out: number;
}

export interface ChatStreamHandlers {
  onProgress?: (sessionId: string) => void;
  onToken?: (delta: string) => void;
  onTool?: (event: ChatToolEvent) => void;
  onDone?: (event: ChatDoneEvent) => void;
  onError?: (message: string) => void;
}

const isTestEnv = typeof process !== "undefined" && process.env["NODE_ENV"] === "test";
const SSE_BASE = isTestEnv ? "http://localhost/api/v1" : "/api/v1";

/** Replay a stored conversation: [{role, content}, ...] in order. */
export async function fetchChatHistory(sessionId: string): Promise<ChatMessageInput[]> {
  const wsId = useActiveWorkspace.getState().workspaceId;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (wsId) headers["X-Workspace-Id"] = wsId;
  const res = await fetch(`${SSE_BASE}/agent/chat/${sessionId}/history`, { headers });
  if (!res.ok) return [];
  const body = (await res.json()) as { role: string; content: string }[];
  return body.map((m) => ({ role: m.role as ChatMessageInput["role"], content: m.content }));
}

function streamHeaders(): HeadersInit {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const wsId = useActiveWorkspace.getState().workspaceId;
  if (wsId) headers["X-Workspace-Id"] = wsId;
  return headers;
}

function dispatchFrame(block: string, handlers: ChatStreamHandlers): void {
  let eventName = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return;
  const data = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
  switch (eventName) {
    case "progress":
      handlers.onProgress?.(String(data["agent_session_id"] ?? ""));
      break;
    case "token":
      handlers.onToken?.(String(data["delta"] ?? ""));
      break;
    case "tool":
      handlers.onTool?.(data as unknown as ChatToolEvent);
      break;
    case "done":
      handlers.onDone?.(data as unknown as ChatDoneEvent);
      break;
    case "error":
      handlers.onError?.(String(data["message"] ?? "Chat failed."));
      break;
    default:
      break;
  }
}

/** Stream a conversation-mode reply over SSE. */
export async function streamChat(
  messages: ChatMessageInput[],
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
  options?: {
    approvedTool?: ChatToolEvent | null;
    sessionId?: string | null;
    model?: string | null;
  },
): Promise<void> {
  const body: Record<string, unknown> = { messages };
  if (options?.sessionId) body["session_id"] = options.sessionId;
  // Panel-local pick. Absent means "whatever the workspace is configured with".
  if (options?.model) body["model"] = options.model;
  if (options?.approvedTool?.call_id) {
    // Only the opaque call id crosses the wire — the server owns the arguments.
    body["approved_tool"] = { call_id: options.approvedTool.call_id };
  }
  const res = await fetch(`${SSE_BASE}/agent/chat`, {
    method: "POST",
    headers: streamHeaders(),
    credentials: "include",
    body: JSON.stringify(body),
    signal: signal ?? null,
  });

  if (!res.ok || res.body === null) {
    let message = `Chat request failed (${res.status})`;
    if (res.status === 409) message = "Configure an LLM in Settings → LLM to chat with the agent.";
    try {
      const parsed = (await res.json()) as { detail?: string; message?: string };
      message = parsed.detail ?? parsed.message ?? message;
    } catch {
      /* non-JSON body — keep the generic message */
    }
    handlers.onError?.(message);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep = buffer.indexOf("\n\n");
    while (sep !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      if (frame.trim().length > 0) dispatchFrame(frame, handlers);
      sep = buffer.indexOf("\n\n");
    }
  }
  if (buffer.trim().length > 0) dispatchFrame(buffer, handlers);
}
