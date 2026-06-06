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

export interface ChatToolEvent {
  tool: string;
  arguments: Record<string, unknown>;
  agent_session_id: string;
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
): Promise<void> {
  const res = await fetch(`${SSE_BASE}/agent/chat`, {
    method: "POST",
    headers: streamHeaders(),
    credentials: "include",
    body: JSON.stringify({ messages }),
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
