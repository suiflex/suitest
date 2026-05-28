import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WsClient } from "./ws-client";

type SendArg = string;

class MockWebSocket {
  static OPEN = 1;
  static CLOSED = 3;
  static instances: MockWebSocket[] = [];

  url: string;
  readyState = 0;
  sent: SendArg[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  }

  // Test helpers
  triggerOpen(): void {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  triggerMessage(data: unknown): void {
    this.onmessage?.({ data: JSON.stringify(data) });
  }

  triggerClose(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  }
}

const WS_URL = "ws://test.local/ws";

beforeEach(() => {
  MockWebSocket.instances = [];
  vi.stubGlobal("WebSocket", MockWebSocket);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("WsClient", () => {
  it("sends subscribe frames for all subscribed topics on open", () => {
    const client = new WsClient(WS_URL);
    client.subscribe("runs.123", () => {});
    client.subscribe("capabilities", () => {});
    client.connect();

    const ws = MockWebSocket.instances[0];
    expect(ws).toBeDefined();
    if (!ws) return;

    // Before open, no frames have been flushed (subscribe was called pre-connect)
    expect(ws.sent).toEqual([]);

    ws.triggerOpen();

    const topics = ws.sent.map((s) => JSON.parse(s) as { type: string; topic: string });
    expect(topics).toHaveLength(2);
    expect(topics.map((t) => t.topic).sort()).toEqual(["capabilities", "runs.123"]);
    expect(topics.every((t) => t.type === "subscribe")).toBe(true);
  });

  it("dispatches incoming messages to the listener for the matching topic", () => {
    const client = new WsClient(WS_URL);
    const runsCb = vi.fn();
    const capsCb = vi.fn();
    client.subscribe("runs.123", runsCb);
    client.subscribe("capabilities", capsCb);
    client.connect();
    const ws = MockWebSocket.instances[0];
    if (!ws) throw new Error("no socket");
    ws.triggerOpen();

    ws.triggerMessage({ topic: "runs.123", event: "log", payload: { line: "hello" } });

    expect(runsCb).toHaveBeenCalledTimes(1);
    expect(runsCb).toHaveBeenCalledWith({ event: "log", payload: { line: "hello" } });
    expect(capsCb).not.toHaveBeenCalled();
  });

  it("ignores malformed messages without throwing", () => {
    const client = new WsClient(WS_URL);
    const cb = vi.fn();
    client.subscribe("x", cb);
    client.connect();
    const ws = MockWebSocket.instances[0];
    if (!ws) throw new Error("no socket");
    ws.triggerOpen();

    expect(() => ws.onmessage?.({ data: "not-json{" })).not.toThrow();
    expect(cb).not.toHaveBeenCalled();
  });

  it("reconnects after 500ms backoff on close", () => {
    const client = new WsClient(WS_URL);
    client.connect();
    const ws1 = MockWebSocket.instances[0];
    if (!ws1) throw new Error("no socket");
    ws1.triggerOpen();
    ws1.triggerClose();

    expect(MockWebSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(499);
    expect(MockWebSocket.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it("doubles backoff each attempt and caps at 30_000ms", () => {
    const client = new WsClient(WS_URL);
    client.connect();

    const expectedDelays = [500, 1_000, 2_000, 4_000, 8_000, 16_000, 30_000, 30_000];
    for (let i = 0; i < expectedDelays.length; i += 1) {
      const ws = MockWebSocket.instances[i];
      if (!ws) throw new Error(`no socket at attempt ${String(i)}`);
      ws.triggerClose();
      const delay = expectedDelays[i];
      if (delay === undefined) throw new Error("delay undefined");
      // Just before the scheduled time, no new socket yet
      vi.advanceTimersByTime(delay - 1);
      expect(MockWebSocket.instances).toHaveLength(i + 1);
      vi.advanceTimersByTime(1);
      expect(MockWebSocket.instances).toHaveLength(i + 2);
    }
  });

  it("resets backoff to 500ms after a successful reconnect (onopen)", () => {
    const client = new WsClient(WS_URL);
    client.connect();

    const ws1 = MockWebSocket.instances[0];
    if (!ws1) throw new Error("ws1");
    ws1.triggerClose();
    vi.advanceTimersByTime(500);

    const ws2 = MockWebSocket.instances[1];
    if (!ws2) throw new Error("ws2");
    ws2.triggerOpen();
    ws2.triggerClose();

    // After successful open, attempts reset → next backoff is 500ms again
    vi.advanceTimersByTime(499);
    expect(MockWebSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(MockWebSocket.instances).toHaveLength(3);
  });

  it("subscribe returns unsubscribe that removes listener and emits unsubscribe when last listener leaves", () => {
    const client = new WsClient(WS_URL);
    client.connect();
    const ws = MockWebSocket.instances[0];
    if (!ws) throw new Error("no socket");
    ws.triggerOpen();

    const cbA = vi.fn();
    const cbB = vi.fn();
    const unsubA = client.subscribe("runs.42", cbA);
    const unsubB = client.subscribe("runs.42", cbB);

    // Both subscribes should have emitted a subscribe frame each (live socket).
    const subFrames = ws.sent.filter((s) => s.includes('"subscribe"'));
    expect(subFrames).toHaveLength(2);

    // Remove first listener — still has cbB, so no unsubscribe frame yet.
    unsubA();
    ws.triggerMessage({ topic: "runs.42", event: "log", payload: 1 });
    expect(cbA).not.toHaveBeenCalled();
    expect(cbB).toHaveBeenCalledTimes(1);
    expect(ws.sent.filter((s) => s.includes('"unsubscribe"'))).toHaveLength(0);

    // Remove last listener — now an unsubscribe frame should be emitted.
    unsubB();
    const unsubFrames = ws.sent
      .map((s) => JSON.parse(s) as { type: string; topic: string })
      .filter((m) => m.type === "unsubscribe");
    expect(unsubFrames).toEqual([{ type: "unsubscribe", topic: "runs.42" }]);

    // Further messages on that topic should not invoke any callback.
    ws.triggerMessage({ topic: "runs.42", event: "log", payload: 2 });
    expect(cbB).toHaveBeenCalledTimes(1);
  });
});
