// Wired into screens in M1c (run logs + MCP health) + M3 (agent streaming) +
// capability.changed events.
//
// Provides:
//   1. `WsClient` — low-level reconnecting/dispatching client (used by the
//      singleton `wsClient` + Vitest unit tests).
//   2. `useRunStream(runId, onEvent)` — typed subscription to the per-run
//      Redis channel (`run:<id>`). Used by `routes/_app/runs/$runId.tsx`.
//   3. `useWorkspaceStream(onEvent)` — typed subscription to the active
//      workspace channel (`workspace:<id>`). Used by the MCP browser +
//      capability change refetches.
//
// Both hooks intentionally re-subscribe whenever their target changes
// (runId, active workspace id) and unsubscribe on unmount so we never leak
// open subscriptions across navigations.

import { useEffect, useRef } from "react";

import { useActiveWorkspace } from "@/stores/use-active-workspace";

type Listener = (payload: { event: string; payload: unknown }) => void;
type Topic = string;

interface ServerMessage {
  topic: string;
  event: string;
  payload: unknown;
}

export class WsClient {
  private socket: WebSocket | null = null;
  private listeners = new Map<Topic, Set<Listener>>();
  private subscribed = new Set<Topic>();
  private reconnectAttempts = 0;
  private url: string;

  constructor(url: string) {
    this.url = url;
  }

  connect(): void {
    this.socket = new WebSocket(this.url);
    this.socket.onopen = () => {
      this.reconnectAttempts = 0;
      for (const t of this.subscribed) {
        this.socket?.send(JSON.stringify({ type: "subscribe", topic: t }));
      }
    };
    this.socket.onmessage = (ev: MessageEvent<string>) => {
      try {
        const msg = JSON.parse(ev.data) as ServerMessage;
        const set = this.listeners.get(msg.topic);
        set?.forEach((cb) => {
          cb({ event: msg.event, payload: msg.payload });
        });
      } catch {
        /* ignore malformed */
      }
    };
    this.socket.onclose = () => {
      this.scheduleReconnect();
    };
    this.socket.onerror = () => {
      this.socket?.close();
    };
  }

  private scheduleReconnect(): void {
    const backoff = Math.min(30_000, 500 * 2 ** this.reconnectAttempts);
    this.reconnectAttempts += 1;
    setTimeout(() => {
      this.connect();
    }, backoff);
  }

  subscribe(topic: Topic, cb: Listener): () => void {
    this.subscribed.add(topic);
    let set = this.listeners.get(topic);
    if (!set) {
      set = new Set();
      this.listeners.set(topic, set);
    }
    set.add(cb);
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: "subscribe", topic }));
    }
    return () => {
      const current = this.listeners.get(topic);
      if (current) {
        current.delete(cb);
        if (current.size === 0) {
          this.subscribed.delete(topic);
          this.listeners.delete(topic);
          if (this.socket?.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify({ type: "unsubscribe", topic }));
          }
        }
      }
    };
  }

  close(): void {
    this.socket?.close();
  }
}

function defaultUrl(): string {
  if (typeof window === "undefined") {
    return "ws://localhost/ws";
  }
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws`;
}

export const wsClient = new WsClient(defaultUrl());

// ---------------------------------------------------------------------------
// Typed event unions (single source of truth for screens that subscribe).
// ---------------------------------------------------------------------------

export type RunEvent =
  | { event: "run.started"; data: { runId: string; tier: string } }
  | {
      event: "run.step.started";
      data: {
        runId: string;
        stepIndex: number;
        action: string;
        mcpProvider: string;
        targetKind: string;
      };
    }
  | {
      event: "run.step.log";
      data: {
        runId: string;
        stepIndex: number;
        level: string;
        message: string;
        time: string;
      };
    }
  | {
      event: "run.step.completed";
      data: {
        runId: string;
        stepIndex: number;
        outcome: string;
        durationMs: number;
      };
    }
  | {
      event: "run.completed";
      data: {
        runId: string;
        status: string;
        totalSteps: number;
        passedSteps: number;
        failedSteps: number;
        durationMs: number;
      };
    };

export type WorkspaceEvent =
  | {
      event: "mcp.provider.health";
      data: { providerId: string; status: "ok" | "degraded" | "down" | "unknown" };
    }
  | {
      event: "capability.changed";
      data: { tier: string };
    }
  | {
      // M3-13: the agent requested a tool call in conversation mode; the UI
      // surfaces a confirm card (mutations always require explicit confirm).
      event: "agent.tool.call";
      data: { tool: string; arguments: Record<string, unknown>; agent_session_id: string };
    };

/**
 * One live browser-recorder interaction, fanned out on the `recorder:<id>`
 * channel as the user demos a flow. Mirrors the backend `RecorderEvent`
 * schema. The gateway wraps each in a `generator.recorder.step` envelope.
 */
export interface RecorderLiveEvent {
  kind: "navigate" | "click" | "type" | "assert" | "network";
  timestamp?: string;
  url?: string | null;
  selector?: string | null;
  text?: string | null;
  masked?: boolean;
  assertion?: Record<string, unknown> | null;
  network?: Record<string, unknown> | null;
}

// ---------------------------------------------------------------------------
// React hook helpers. They accept either the singleton client or, in tests,
// any object implementing the `subscribe(topic, cb)` contract via the
// `WsTransportLike` interface below. The tests inject a `MockWs` instance.
// ---------------------------------------------------------------------------

export interface WsTransportLike {
  subscribe(topic: Topic, cb: Listener): () => void;
}

let activeTransport: WsTransportLike = wsClient;

/**
 * Test seam. Swap the singleton transport for a `MockWs` in unit tests
 * (`apps/web/src/test/mock-ws.ts`). Always restore via the returned
 * cleanup function or by calling `setWsTransport(wsClient)`.
 */
export function setWsTransport(t: WsTransportLike): () => void {
  const prev = activeTransport;
  activeTransport = t;
  return () => {
    activeTransport = prev;
  };
}

/** Read-only accessor used by the hook implementations + tests. */
export function getWsTransport(): WsTransportLike {
  return activeTransport;
}

function isRunEvent(raw: { event: string; payload: unknown }): raw is {
  event: RunEvent["event"];
  payload: unknown;
} {
  return (
    raw.event === "run.started" ||
    raw.event === "run.step.started" ||
    raw.event === "run.step.log" ||
    raw.event === "run.step.completed" ||
    raw.event === "run.completed"
  );
}

function isWorkspaceEvent(raw: { event: string; payload: unknown }): raw is {
  event: WorkspaceEvent["event"];
  payload: unknown;
} {
  return (
    raw.event === "mcp.provider.health" ||
    raw.event === "capability.changed" ||
    raw.event === "agent.tool.call"
  );
}

/**
 * Subscribe to the `run:<runId>` Redis channel via the WS gateway. The
 * `onEvent` callback is invoked for every typed event in the
 * `RunEvent` union. Unsubscribes on unmount **and** whenever `runId`
 * changes so navigating between two runs cleanly tears down the old
 * subscription.
 *
 * The latest `onEvent` reference is stored in a ref so the subscription
 * does not churn on every re-render of the parent component.
 */
export function useRunStream(runId: string, onEvent: (e: RunEvent) => void): void {
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  useEffect(() => {
    const transport = getWsTransport();
    const unsubscribe = transport.subscribe(`run:${runId}`, (msg) => {
      if (!isRunEvent(msg)) return;
      // The gateway emits `{ event, payload }`; the typed callback expects
      // `{ event, data }`. Narrowing on `event` makes the cast safe — the
      // gateway is the single source of truth for the payload shape.
      cbRef.current({
        event: msg.event,
        data: msg.payload,
      } as RunEvent);
    });
    return unsubscribe;
  }, [runId]);
}

/**
 * Subscribe to the active workspace's gateway channel. Re-subscribes when
 * the workspace switches, so health / capability events always reflect the
 * currently-active tenant.
 */
export function useWorkspaceStream(onEvent: (e: WorkspaceEvent) => void): void {
  const workspaceId = useActiveWorkspace((s) => s.workspaceId);
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  useEffect(() => {
    if (!workspaceId) return;
    const transport = getWsTransport();
    const unsubscribe = transport.subscribe(`workspace:${workspaceId}`, (msg) => {
      if (!isWorkspaceEvent(msg)) return;
      cbRef.current({
        event: msg.event,
        data: msg.payload,
      } as WorkspaceEvent);
    });
    return unsubscribe;
  }, [workspaceId]);
}
