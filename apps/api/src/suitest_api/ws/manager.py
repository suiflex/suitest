"""WebSocket connection manager + Redis pub/sub bridge.

One ``WsConnectionManager`` per FastAPI app (stashed on ``app.state.ws_manager``).
It owns:

* The set of live :class:`WsConnection` objects, keyed by an opaque ``int`` id.
* A ``channel -> {connection_id}`` index so a Redis message on ``run:abc`` can
  be fanned out to every client that subscribed to ``run:abc``.
* A single :class:`redis.asyncio.client.PubSub` consumed by one background task
  — the task picks up messages and dispatches them to every interested
  ``WsConnection``.

Concurrency: the bookkeeping (``_connections`` / ``_channel_listeners``) is
guarded by ``_lock`` so subscribe / unsubscribe / disconnect cannot race the
pub/sub listener.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import defaultdict
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from fastapi import WebSocket
    from redis.asyncio.client import PubSub, Redis

log = structlog.get_logger(__name__)


class WsConnection:
    """One authenticated WebSocket client + the channels it subscribed to."""

    __slots__ = ("channels", "user_id", "ws")

    def __init__(self, ws: WebSocket, user_id: str) -> None:
        self.ws = ws
        self.user_id = user_id
        self.channels: set[str] = set()


class WsConnectionManager:
    """Tracks live WebSocket connections + bridges Redis pub/sub to them."""

    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client
        self._connections: dict[int, WsConnection] = {}
        self._channel_listeners: dict[str, set[int]] = defaultdict(set)
        self._listener_task: asyncio.Task[None] | None = None
        self._pubsub: PubSub | None = None
        self._lock = asyncio.Lock()
        self._started = False
        # ``redis.asyncio`` raises if ``get_message`` is called before any
        # subscribe — the listener uses this event to idle until the first
        # subscription lands.
        self._has_subscription = asyncio.Event()

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Open the shared :class:`PubSub` and spawn the background dispatcher."""
        if self._started:
            return
        self._pubsub = self.redis.pubsub()
        self._listener_task = asyncio.create_task(self._listen(), name="ws-pubsub-listener")
        self._started = True

    async def stop(self) -> None:
        """Cancel the dispatcher and close the shared :class:`PubSub`."""
        if not self._started:
            return
        if self._listener_task is not None:
            self._listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._listener_task
            self._listener_task = None
        if self._pubsub is not None:
            with contextlib.suppress(Exception):
                await self._pubsub.aclose()  # type: ignore[no-untyped-call]
            self._pubsub = None
        self._started = False
        self._connections.clear()
        self._channel_listeners.clear()
        self._has_subscription.clear()

    # -- connection bookkeeping -------------------------------------------

    async def add(self, conn: WsConnection) -> int:
        """Register ``conn``; returns its opaque manager-local id."""
        cid = id(conn)
        async with self._lock:
            self._connections[cid] = conn
        return cid

    async def remove(self, conn: WsConnection) -> None:
        """Unregister ``conn`` and unsubscribe it from every channel it joined.

        Also unsubscribes the shared :class:`PubSub` from any channel that has
        no remaining listeners — otherwise dead channels leak forever.
        """
        cid = id(conn)
        async with self._lock:
            self._connections.pop(cid, None)
            for channel in list(conn.channels):
                listeners = self._channel_listeners.get(channel)
                if listeners is None:
                    continue
                listeners.discard(cid)
                if not listeners:
                    self._channel_listeners.pop(channel, None)
                    if self._pubsub is not None:
                        with contextlib.suppress(Exception):
                            await self._pubsub.unsubscribe(channel)
            conn.channels.clear()
            if not self._channel_listeners:
                self._has_subscription.clear()

    # -- subscription management ------------------------------------------

    async def subscribe(self, conn: WsConnection, channel: str) -> None:
        """Subscribe ``conn`` to ``channel`` (idempotent)."""
        async with self._lock:
            already_subscribed = bool(self._channel_listeners.get(channel))
            self._channel_listeners[channel].add(id(conn))
            conn.channels.add(channel)
            if not already_subscribed and self._pubsub is not None:
                await self._pubsub.subscribe(channel)
            # Wake the listener loop once at least one channel is live; before
            # this point ``redis.asyncio`` PubSub raises on ``get_message``.
            self._has_subscription.set()

    async def unsubscribe(self, conn: WsConnection, channel: str) -> None:
        """Unsubscribe ``conn`` from ``channel`` (no-op if not subscribed)."""
        async with self._lock:
            listeners = self._channel_listeners.get(channel)
            if listeners is None:
                conn.channels.discard(channel)
                return
            listeners.discard(id(conn))
            conn.channels.discard(channel)
            if not listeners:
                self._channel_listeners.pop(channel, None)
                if self._pubsub is not None:
                    with contextlib.suppress(Exception):
                        await self._pubsub.unsubscribe(channel)
            if not self._channel_listeners:
                self._has_subscription.clear()

    # -- listener ----------------------------------------------------------

    async def _listen(self) -> None:
        """Pump messages from the shared :class:`PubSub` to interested connections.

        ``get_message`` with a small ``timeout`` lets the task notice cancellation
        between polls; a longer timeout would block ``stop()`` from returning.
        We gate the polling on :attr:`_has_subscription` because
        :meth:`PubSub.get_message` raises ``RuntimeError("pubsub connection not
        set")`` when called before any subscribe — so the listener idles cheaply
        until the first ``subscribe`` lands.
        """
        assert self._pubsub is not None  # set by start()
        while True:
            try:
                await self._has_subscription.wait()
            except asyncio.CancelledError:
                return
            try:
                msg = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            except asyncio.CancelledError:
                return
            except Exception:  # pragma: no cover - logged, never raised
                log.exception("ws.pubsub.read_failed")
                await asyncio.sleep(0.1)
                continue
            if msg is None:
                continue
            channel_raw = msg.get("channel")
            data_raw = msg.get("data")
            if channel_raw is None or data_raw is None:
                continue
            channel = channel_raw.decode() if isinstance(channel_raw, bytes) else str(channel_raw)
            data = data_raw.decode() if isinstance(data_raw, bytes) else str(data_raw)
            await self._dispatch(channel, data)

    async def _dispatch(self, channel: str, data: str) -> None:
        """Send ``data`` to every connection subscribed to ``channel``.

        Parses ``data`` as JSON when possible and wraps it in the envelope
        ``{"type": "event", "topic": ..., "event": ..., "payload": ...}``. If the
        payload is not a JSON object (raw string, malformed JSON), it is forwarded
        verbatim as the ``payload`` so producers retain full freedom.
        """
        async with self._lock:
            listener_ids = list(self._channel_listeners.get(channel, set()))
            connections = [
                self._connections[cid] for cid in listener_ids if cid in self._connections
            ]

        if not connections:
            return

        envelope = _build_envelope(channel, data)
        text = json.dumps(envelope, separators=(",", ":"))

        for conn in connections:
            try:
                await conn.ws.send_text(text)
            except Exception:  # pragma: no cover - logged, removed on next disconnect
                log.warning("ws.send.failed", channel=channel, user_id=conn.user_id)


def _build_envelope(channel: str, data: str) -> dict[str, object]:
    """Wrap a raw Redis payload into the ``ServerEvent`` shape.

    The dispatcher does not import :class:`ServerEvent` directly because it
    would double the per-message Pydantic validation cost. The shape is asserted
    in tests so the two stay in sync.
    """
    try:
        parsed = json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return {"type": "event", "topic": channel, "event": "raw", "payload": {"data": data}}
    if not isinstance(parsed, dict):
        return {"type": "event", "topic": channel, "event": "raw", "payload": {"data": parsed}}
    event_name = parsed.get("event")
    payload = parsed.get("data", parsed.get("payload", {}))
    if not isinstance(payload, dict):
        payload = {"data": payload}
    return {
        "type": "event",
        "topic": channel,
        "event": str(event_name) if isinstance(event_name, str) else "message",
        "payload": payload,
    }
