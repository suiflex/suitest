"""Tiny helper that publishes ``{event, data}`` envelopes to a Redis pub/sub channel.

Wraps :data:`Request.app.state.ws_redis` (the same in-process / fakeredis /
real :class:`redis.asyncio.Redis` the WS gateway consumes). Service-layer code
calls :func:`publish_event` to fan an arbitrary ``{event, data}`` payload to
every subscriber on ``workspace:<wsId>`` (or any other topic) — the connection
manager (``WsConnectionManager._listen``) already builds the
``{type:"event", topic, event, payload}`` envelope on the client side.

The helper is intentionally a no-op when ``ws_redis`` is not configured (dev
sessions without Redis, unit tests that don't care about side-channel emit).
It also swallows transient publish errors so a flaky pub/sub does not break a
user-facing write — the persistent state is already committed by the time
this fires.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Protocol

import structlog

if TYPE_CHECKING:
    from fastapi import Request

log = structlog.get_logger(__name__)


class _PublishCapable(Protocol):
    """Minimum surface ``WsConnectionManager``'s redis client must satisfy.

    Both :class:`redis.asyncio.Redis` and :class:`fakeredis.aioredis.FakeRedis`
    expose ``async def publish(channel, message)``; declaring the Protocol
    keeps the helper duck-typed without dragging the optional redis dep into
    the import graph of every consumer.
    """

    async def publish(self, channel: str, message: str | bytes) -> int: ...


async def publish_event(
    request: Request,
    *,
    topic: str,
    event: str,
    data: dict[str, object],
) -> None:
    """Publish ``{"event": ..., "data": ...}`` JSON to ``topic`` via app Redis.

    Looks up ``request.app.state.ws_redis``; if it is absent or does not expose
    an async ``publish`` (CI without Redis, dev with ``SUITEST_REDIS_URL=memory://``),
    silently returns. The handler does NOT swallow programmer errors — it
    catches only the runtime publish failure so a flaky redis cannot 500 the
    user-facing write.
    """
    redis = getattr(request.app.state, "ws_redis", None)
    if redis is None or not hasattr(redis, "publish"):
        return
    payload = json.dumps({"event": event, "data": data}, separators=(",", ":"))
    try:
        await redis.publish(topic, payload)
    except Exception:  # pragma: no cover — logged, never raised
        log.warning("ws.publish.failed", topic=topic, event=event)
