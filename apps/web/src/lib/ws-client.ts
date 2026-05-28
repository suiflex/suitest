// Wired into screens in M1c (run logs) + M3 (agent streaming) + capability.changed events.
//
// Placeholder WS client with reconnect + subscribe API. M1b only validates the
// reconnect/subscribe contract via unit tests — no screen consumes this yet.

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
        set?.forEach((cb) => cb({ event: msg.event, payload: msg.payload }));
      } catch {
        /* ignore malformed */
      }
    };
    this.socket.onclose = () => this.scheduleReconnect();
    this.socket.onerror = () => this.socket?.close();
  }

  private scheduleReconnect(): void {
    const backoff = Math.min(30_000, 500 * 2 ** this.reconnectAttempts);
    this.reconnectAttempts += 1;
    setTimeout(() => this.connect(), backoff);
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
