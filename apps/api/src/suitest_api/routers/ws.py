"""``GET /ws?token=<jwt>`` — authenticated WebSocket gateway.

Cookies do not survive the cross-origin WebSocket upgrade reliably (different
``SameSite`` semantics across browsers, no preflight), so the client passes the
same FastAPI-Users JWT as a query parameter. We validate it via the same
:class:`JWTStrategy` that backs the HTTP auth (``suitest_api.auth.manager``) so
there is exactly one auth code path.

On invalid / missing token we close with custom code ``4401`` (RFC 6455 reserves
``4000-4999`` for application-defined codes; ``4401`` mirrors HTTP 401). The
default ``1008 Policy Violation`` would be ambiguous with rate-limit / topic
rejection.

The handler keeps a tight loop:

  1. accept,
  2. register on ``app.state.ws_manager``,
  3. spawn a 30s heartbeat task,
  4. read JSON frames → dispatch ``subscribe`` / ``unsubscribe`` / ``ping``,
  5. on disconnect: cancel heartbeat + cleanup manager state.

Cleanup runs from ``finally`` so a crash inside the loop still frees the
connection's channels.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from suitest_api.auth.db import async_session_maker, get_async_session
from suitest_api.auth.manager import get_jwt_strategy
from suitest_api.ws.manager import WsConnection, WsConnectionManager
from suitest_api.ws.messages import (
    ClientMessage,
    ClientPing,
    ClientSubscribe,
    ClientUnsubscribe,
    ServerAck,
    ServerError,
    ServerHeartbeat,
    ServerPong,
)

if TYPE_CHECKING:
    from suitest_db.models.user import User

log = structlog.get_logger(__name__)

router = APIRouter(tags=["ws"])

WS_CLOSE_AUTH = 4401
"""Custom WS close code for auth failure. RFC 6455 reserves 4000-4999 for apps."""

HEARTBEAT_INTERVAL_SECONDS = 30.0


@asynccontextmanager
async def _resolve_session(websocket: WebSocket) -> AsyncIterator[AsyncSession]:
    """Yield an :class:`AsyncSession` honouring test-time DI overrides.

    The WS handler runs OUTSIDE the FastAPI Depends graph (we can't ``Depends``
    before ``websocket.accept()``), so the standard
    ``app.dependency_overrides[get_async_session]`` pattern would be bypassed
    for any session opened directly via :data:`async_session_maker`. We honour
    the override manually here — tests inject a session bound to the
    pgvector testcontainer and the WS auth path picks it up the same way the
    HTTP routers do.
    """
    override = websocket.app.dependency_overrides.get(get_async_session)
    if override is not None:
        gen = override()
        # FastAPI dependency overrides may be async generators OR plain
        # callables returning a session; only the async-generator shape is in
        # use today (see :func:`get_async_session`) so we drive it directly.
        session = await gen.__anext__()
        try:
            yield session
        finally:
            with contextlib.suppress(StopAsyncIteration):
                await gen.__anext__()
        return
    async with async_session_maker() as session:
        yield session


async def _resolve_user_from_token(websocket: WebSocket, token: str | None) -> User | None:
    """Decode ``token`` via the FastAPI-Users JWT strategy + load the User row.

    Mirrors what :class:`fastapi_users.authentication.JWTStrategy.read_token`
    does for HTTP requests but without going through the full FastAPI DI graph
    (which we cannot use inside a WS handler before ``accept()``). Returns the
    :class:`User` on success, ``None`` on any failure (bad JWT, missing user,
    DB error).
    """
    if not token:
        return None

    # Late import keeps the cold-start cost off ws.py import.
    from fastapi_users.exceptions import InvalidID, UserNotExists
    from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
    from suitest_db.models.user import OAuthAccount
    from suitest_db.models.user import User as UserModel

    from suitest_api.auth.manager import UserManager

    strategy = get_jwt_strategy()

    async with _resolve_session(websocket) as session:
        user_db: SQLAlchemyUserDatabase[UserModel, uuid.UUID] = SQLAlchemyUserDatabase(
            session, UserModel, OAuthAccount
        )
        manager = UserManager(user_db)
        try:
            user = await strategy.read_token(token, manager)
        except (InvalidID, UserNotExists):
            return None
        except Exception:  # pragma: no cover — defensive, never raised by JWTStrategy
            log.warning("ws.auth.token_read_failed")
            return None
        if user is None:
            return None
        if not user.is_active:
            return None
        return user


async def _user_workspace_ids(websocket: WebSocket, user_id: uuid.UUID) -> set[str]:
    """Return the set of workspace ids the user is a member of.

    Used to gate ``workspace:<id>`` subscriptions so a token holder cannot listen
    in on workspaces they don't belong to.
    """
    from suitest_db.models.tenancy import Membership

    async with _resolve_session(websocket) as session:
        rows = await session.execute(
            select(Membership.workspace_id).where(Membership.user_id == user_id)
        )
        return {row[0] for row in rows.all()}


def _is_allowed_topic(topic: str, workspace_ids: set[str]) -> tuple[bool, str | None]:
    """Validate a topic against the user's allowed namespaces.

    Returns ``(allowed, error_code)`` — the error code matches a short literal
    documented in ``docs/API.md`` once the gateway is wired (``unknown_topic``,
    ``workspace_forbidden``).
    """
    if topic.startswith("workspace:"):
        ws_id = topic.split(":", 1)[1]
        if ws_id and ws_id in workspace_ids:
            return True, None
        return False, "workspace_forbidden"
    if topic.startswith(("run:", "mcp.provider.health", "capability.changed")):
        # Run-level events fanned out by the runner; mcp/capability are global
        # event streams scoped per-workspace upstream (publisher chooses the
        # channel). Authenticated users see them.
        return True, None
    return False, "unknown_topic"


async def _heartbeat(websocket: WebSocket) -> None:
    """Send a ``{"type": "heartbeat"}`` frame every 30s until cancelled."""
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            try:
                await websocket.send_text(ServerHeartbeat().model_dump_json())
            except Exception:
                return
    except asyncio.CancelledError:
        return


def _parse_client_message(raw: str) -> ClientMessage | None:
    """Parse + validate one incoming JSON frame, or return ``None`` on garbage."""
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    try:
        action = decoded.get("action")
        if action == "subscribe":
            return ClientSubscribe.model_validate(decoded)
        if action == "unsubscribe":
            return ClientUnsubscribe.model_validate(decoded)
        if action == "ping":
            return ClientPing.model_validate(decoded)
    except ValidationError:
        return None
    return None


@router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str | None = Query(default=None)) -> None:
    """JWT-authenticated WebSocket entrypoint."""
    user = await _resolve_user_from_token(websocket, token)
    if user is None:
        await websocket.close(code=WS_CLOSE_AUTH, reason="auth")
        return

    manager_obj = getattr(websocket.app.state, "ws_manager", None)
    if not isinstance(manager_obj, WsConnectionManager):
        # Lifespan failed to wire the manager; refuse rather than crash on subscribe.
        await websocket.close(code=WS_CLOSE_AUTH, reason="unavailable")
        return
    manager: WsConnectionManager = manager_obj

    await websocket.accept()

    workspace_ids = await _user_workspace_ids(websocket, user.id)
    conn = WsConnection(ws=websocket, user_id=str(user.id))
    await manager.add(conn)
    heartbeat_task = asyncio.create_task(_heartbeat(websocket), name="ws-heartbeat")

    try:
        while True:
            raw = await websocket.receive_text()
            msg = _parse_client_message(raw)
            if msg is None:
                await websocket.send_text(
                    ServerError(code="invalid_message", message="malformed frame").model_dump_json()
                )
                continue

            if isinstance(msg, ClientPing):
                await websocket.send_text(ServerPong().model_dump_json())
                continue

            allowed, err = _is_allowed_topic(msg.topic, workspace_ids)
            if not allowed:
                await websocket.send_text(
                    ServerError(
                        code=err or "forbidden",
                        message=f"topic '{msg.topic}' rejected",
                    ).model_dump_json()
                )
                continue

            if isinstance(msg, ClientSubscribe):
                await manager.subscribe(conn, msg.topic)
                await websocket.send_text(
                    ServerAck(action="subscribe", topic=msg.topic).model_dump_json()
                )
            elif isinstance(msg, ClientUnsubscribe):
                await manager.unsubscribe(conn, msg.topic)
                await websocket.send_text(
                    ServerAck(action="unsubscribe", topic=msg.topic).model_dump_json()
                )
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await heartbeat_task
        await manager.remove(conn)
