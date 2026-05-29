"""Typed Pydantic models for client/server WebSocket messages.

Client → server:
  * ``ClientSubscribe`` (``{"action": "subscribe", "topic": "run:abc"}``)
  * ``ClientUnsubscribe`` (``{"action": "unsubscribe", "topic": "run:abc"}``)
  * ``ClientPing`` (``{"action": "ping"}``)

Server → client:
  * ``ServerAck`` — confirms a subscribe / unsubscribe was accepted.
  * ``ServerError`` — soft error (e.g. invalid topic, not a member of workspace).
  * ``ServerEvent`` — envelope around a Redis pub/sub payload forwarded to subscribers.
  * ``ServerPong`` — heartbeat pong.

The envelope carries the originating ``topic`` so a single connection can multiplex
multiple subscriptions over one socket without the client having to maintain its
own channel routing table.

Event kinds (``ServerEvent.event``) emitted by other components:
  * ``run.queued`` / ``run.started`` / ``run.step.started`` / ``run.step.log`` /
    ``run.step.completed`` / ``run.completed`` — runner (Task 13 / 15).
  * ``mcp.provider.health`` — MCP health monitor (packages/mcp/health.py).
  * ``capability.changed`` — workspace capability mutations (Task 11).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Client -> server
# ---------------------------------------------------------------------------


class ClientSubscribe(BaseModel):
    """Client asks to subscribe to ``topic`` (e.g. ``run:cuid``)."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["subscribe"]
    topic: str = Field(min_length=1, max_length=256)


class ClientUnsubscribe(BaseModel):
    """Client asks to stop receiving messages on ``topic``."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["unsubscribe"]
    topic: str = Field(min_length=1, max_length=256)


class ClientPing(BaseModel):
    """Application-level ping; server replies with :class:`ServerPong`."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["ping"]


ClientMessage = Annotated[
    ClientSubscribe | ClientUnsubscribe | ClientPing,
    Field(discriminator="action"),
]


# ---------------------------------------------------------------------------
# Server -> client
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    """``datetime.now(UTC)`` factory so Pydantic emits aware UTC timestamps."""
    return datetime.now(tz=UTC)


class ServerAck(BaseModel):
    """Confirms a client subscribe/unsubscribe landed."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["ack"] = "ack"
    action: Literal["subscribe", "unsubscribe"]
    topic: str
    timestamp: datetime = Field(default_factory=_utcnow)


class ServerError(BaseModel):
    """Soft error response (does NOT close the connection)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["error"] = "error"
    code: str
    message: str
    timestamp: datetime = Field(default_factory=_utcnow)


class ServerPong(BaseModel):
    """Pong reply to an application-level ping."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["pong"] = "pong"
    timestamp: datetime = Field(default_factory=_utcnow)


class ServerEvent(BaseModel):
    """Envelope forwarding a Redis pub/sub payload to subscribed clients.

    ``payload`` is opaque ``dict`` — the gateway does not interpret event-specific
    schemas; the producer (runner, mcp health monitor, capability service) owns the
    payload shape. ``event`` matches the canonical kind list documented in the
    module docstring.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["event"] = "event"
    topic: str
    event: str
    payload: dict[str, object] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utcnow)


class ServerHeartbeat(BaseModel):
    """Server-initiated 30-second heartbeat (lets the client notice a half-open socket)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["heartbeat"] = "heartbeat"
    timestamp: datetime = Field(default_factory=_utcnow)
