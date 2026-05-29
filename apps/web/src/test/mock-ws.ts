/**
 * In-memory WebSocket transport used by component tests that consume
 * `useRunStream` / `useWorkspaceStream`. The hooks pull their transport from
 * `getWsTransport()`; tests install a fresh `MockWs` via `setWsTransport(...)`
 * and then call `mock.emit({ event, data, topic? })` to drive the screen.
 *
 * The shape mirrors the gateway protocol: each callback receives
 * `{ event, payload }` and the hooks narrow / re-shape that into the typed
 * `{ event, data }` discriminated unions before forwarding to the screen.
 */

import { setWsTransport, type WsTransportLike } from "@/lib/ws-client";

type Listener = (payload: { event: string; payload: unknown }) => void;

export interface MockWsEmit {
  /** Topic the message belongs to. Defaults to the only active subscription. */
  topic?: string;
  event: string;
  /** Sent as the WS gateway `payload`; surfaced to hooks as `data`. */
  data: unknown;
}

export class MockWs implements WsTransportLike {
  private listeners = new Map<string, Set<Listener>>();

  subscribe(topic: string, cb: Listener): () => void {
    let set = this.listeners.get(topic);
    if (!set) {
      set = new Set();
      this.listeners.set(topic, set);
    }
    set.add(cb);
    return () => {
      const current = this.listeners.get(topic);
      if (!current) return;
      current.delete(cb);
      if (current.size === 0) {
        this.listeners.delete(topic);
      }
    };
  }

  /**
   * Dispatch a synthetic event. If `topic` is omitted and exactly one topic
   * is currently subscribed, that topic is used — keeps tests terse for the
   * common single-subscription case.
   */
  emit(msg: MockWsEmit): void {
    const topic = msg.topic ?? this.singleTopic();
    if (!topic) {
      throw new Error("MockWs.emit: no subscription active and no `topic` provided");
    }
    const set = this.listeners.get(topic);
    if (!set) return;
    set.forEach((cb) => {
      cb({ event: msg.event, payload: msg.data });
    });
  }

  /** Active topics — useful for assertions. */
  topics(): string[] {
    return Array.from(this.listeners.keys());
  }

  private singleTopic(): string | null {
    const keys = Array.from(this.listeners.keys());
    return keys.length === 1 ? (keys[0] ?? null) : null;
  }
}

/**
 * Install a fresh `MockWs` as the active transport for the duration of a
 * single test. Returns both the mock + the restore function so tests can
 * deterministically tear down in `afterEach`.
 */
export function installMockWs(): { ws: MockWs; restore: () => void } {
  const ws = new MockWs();
  const restore = setWsTransport(ws);
  return { ws, restore };
}
