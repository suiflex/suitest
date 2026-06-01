import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";
import { useActiveWorkspace } from "@/stores/use-active-workspace";

// ---------------------------------------------------------------------------
// Deterministic generator client (M2-5).
//
// The OpenAPI + crawler generators stream their lifecycle over Server-Sent
// Events; axios buffers the whole response so we drive those two with `fetch`
// + a manual SSE frame parser instead. The recorder endpoints are plain
// request/response, so they reuse the shared axios `api` instance (which also
// injects the `X-Workspace-Id` header via its request interceptor).
//
// Generated DRAFT cases are persisted server-side *as each `case` event is
// emitted* — the modal's review list is a live mirror, not a staging buffer.
// There is no separate "commit" step: a `complete` event means the cases are
// already in the target suite.
// ---------------------------------------------------------------------------

export type OpenApiGenerateRequest = components["schemas"]["OpenApiGenerateRequest"];
export type CrawlerGenerateRequest = components["schemas"]["CrawlerGenerateRequest"];
export type RecorderSessionStartRequest = components["schemas"]["RecorderSessionStartRequest"];
export type RecorderSessionStartResponse = components["schemas"]["RecorderSessionStartResponse"];
export type RecorderFinalizeRequest = components["schemas"]["RecorderFinalizeRequest"];
export type TestCaseDetail = components["schemas"]["TestCaseDetail"];

/** One generated case as surfaced by a `case` SSE frame. */
export interface GeneratorCaseEvent {
  public_id: string;
  name: string;
  case_kind: string | null;
  tags: string[];
}

/** Lifecycle marker (`parsed` / `crawling` / …). */
export interface GeneratorProgressEvent {
  phase: string;
  generator_run_id?: string;
}

/** Terminal success frame — cases already persisted in `target_suite_id`. */
export interface GeneratorCompleteEvent {
  generator_run_id: string;
  target_suite_id: string;
  cases_created: number;
  public_ids: string[];
  duration_ms: number;
}

/** In-band failure frame (e.g. an invalid OpenAPI spec). */
export interface GeneratorErrorEvent {
  code: string;
  message: string;
}

export interface GeneratorStreamHandlers {
  onProgress?: (event: GeneratorProgressEvent) => void;
  onCase?: (event: GeneratorCaseEvent) => void;
  onComplete?: (event: GeneratorCompleteEvent) => void;
  onError?: (event: GeneratorErrorEvent) => void;
}

// Mirror the api-client base-URL seam so MSW can intercept under jsdom.
const isTestEnv = typeof process !== "undefined" && process.env["NODE_ENV"] === "test";
const SSE_BASE = isTestEnv ? "http://localhost/api/v1" : "/api/v1";

function streamHeaders(): HeadersInit {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const wsId = useActiveWorkspace.getState().workspaceId;
  if (wsId) headers["X-Workspace-Id"] = wsId;
  return headers;
}

/** Parse a single SSE frame block (`event: …\ndata: …`) into a typed dispatch. */
function dispatchFrame(block: string, handlers: GeneratorStreamHandlers): void {
  let eventName = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return;
  const data = JSON.parse(dataLines.join("\n")) as unknown;
  switch (eventName) {
    case "progress":
      handlers.onProgress?.(data as GeneratorProgressEvent);
      break;
    case "case":
      handlers.onCase?.(data as GeneratorCaseEvent);
      break;
    case "complete":
      handlers.onComplete?.(data as GeneratorCompleteEvent);
      break;
    case "error":
      handlers.onError?.(data as GeneratorErrorEvent);
      break;
    default:
      break;
  }
}

async function streamGenerator(
  path: string,
  body: unknown,
  handlers: GeneratorStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${SSE_BASE}${path}`, {
    method: "POST",
    headers: streamHeaders(),
    credentials: "include",
    body: JSON.stringify(body),
    signal: signal ?? null,
  });

  if (!res.ok || res.body === null) {
    // A pre-stream failure (e.g. 404 suite-not-found) arrives as a JSON error
    // body, not an SSE frame. Surface it through the same error channel.
    let code = "REQUEST_FAILED";
    let message = `Generator request failed (${res.status})`;
    try {
      const parsed = (await res.json()) as { code?: string; detail?: string; message?: string };
      code = parsed.code ?? code;
      message = parsed.detail ?? parsed.message ?? message;
    } catch {
      /* non-JSON body — keep the generic message */
    }
    handlers.onError?.({ code, message });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE frames are delimited by a blank line.
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

/** `POST /generators/openapi` — stream a contract suite from an OpenAPI spec. */
export function generateOpenApi(
  body: OpenApiGenerateRequest,
  handlers: GeneratorStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  return streamGenerator("/generators/openapi", body, handlers, signal);
}

/** `POST /generators/crawler` — stream a smoke/form suite by crawling a URL. */
export function generateCrawler(
  body: CrawlerGenerateRequest,
  handlers: GeneratorStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  return streamGenerator("/generators/crawler", body, handlers, signal);
}

/** `POST /generators/recorder/sessions` — open a live browser-recording session. */
export async function startRecorderSession(
  body: RecorderSessionStartRequest,
): Promise<RecorderSessionStartResponse> {
  const res = await api.post<RecorderSessionStartResponse>("/generators/recorder/sessions", body);
  return res.data;
}

/** `POST /generators/recorder/sessions/:id/finalize` — captured events → DRAFT case. */
export async function finalizeRecorderSession(
  sessionId: string,
  body: RecorderFinalizeRequest,
): Promise<TestCaseDetail> {
  const res = await api.post<TestCaseDetail>(
    `/generators/recorder/sessions/${sessionId}/finalize`,
    body,
  );
  return res.data;
}

/** `DELETE /generators/recorder/sessions/:id` — cancel an active session. */
export async function cancelRecorderSession(sessionId: string): Promise<void> {
  await api.delete(`/generators/recorder/sessions/${sessionId}`);
}
