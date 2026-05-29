# mypy: warn_unused_ignores=False
"""Task 14 — WebSocket gateway tests.

Uses Starlette's :class:`TestClient` (sync) — its WebSocket helper drives the
ASGI app via an ``anyio.from_thread`` portal which works fine for our async
handler. A ``fakeredis.aioredis.FakeRedis`` is injected on
``app.state.ws_redis`` BEFORE the lifespan runs so the connection manager spins
up against an in-process pub/sub broker (no real Redis required).

Auth is exercised end-to-end: we mint a real FastAPI-Users JWT via the same
:class:`JWTStrategy` the WS handler verifies against, plus seed a User row in
the api-db harness so the token resolves to a live user.

Publishing notes: ``fakeredis.aioredis.FakeRedis`` pins its internal asyncio
queue to whatever event loop first uses it, so we can NOT reuse the fixture's
client from a worker thread (it would crash with "bound to a different event
loop"). The :class:`_RedisBundle` helper spins up a fresh client per publish
that talks to the SAME backing :class:`FakeServer` — the WS bridge running on
the app loop still receives the message via the shared in-memory server.

The file-level ``warn_unused_ignores=False`` lets the few ``# type: ignore``
suppressions on fakeredis call-sites work under both the local mypy run (where
fakeredis ships stubs) and the pre-commit hook (where fakeredis is not in
``additional_dependencies`` and the ignores ARE needed).
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

import fakeredis
import fakeredis.aioredis
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect
from suitest_api.auth.db import get_async_session
from suitest_api.auth.manager import get_jwt_strategy
from suitest_api.main import create_app
from suitest_api.routers.ws import WS_CLOSE_AUTH

if TYPE_CHECKING:
    from api_harness import ApiDb
    from fastapi import FastAPI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _mint_token(user_id: str) -> str:
    """Build a JWT with the same audience the WS handler decodes against."""
    strategy = get_jwt_strategy()
    return await strategy.write_token(_TokenSubject(user_id))  # type: ignore[arg-type]


class _TokenSubject:
    """Minimal duck-type for ``JWTStrategy.write_token`` (only ``.id`` is read)."""

    def __init__(self, user_id: str) -> None:
        self.id = user_id


class _RedisBundle:
    """Per-test fakeredis client + its backing server.

    Tests publish via :meth:`publish_on_thread` so the publish runs on a worker
    thread with its own event loop — fakeredis pins async clients to the loop
    on first use. A fresh client per publish (sharing the same in-memory
    :class:`FakeServer`) routes the message into the app loop's PubSub without
    crossing loops.

    Not a dataclass + no field annotations because the ``fakeredis`` stubs
    aren't visible to the pre-commit mypy hook (it doesn't pull fakeredis into
    ``additional_dependencies``), which would otherwise raise
    ``no-any-unimported`` on every reference. The runtime types are
    :class:`fakeredis.aioredis.FakeRedis` and :class:`fakeredis.FakeServer`.
    """

    def __init__(self, client: object, server: object) -> None:
        self.client = client
        self.server = server

    def publish_on_thread(self, channel: str, payload: str) -> None:
        """Publish ``payload`` to ``channel`` from a worker thread."""
        server = self.server

        def _run_publish() -> None:
            async def _publish() -> None:
                pub = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)  # type: ignore[arg-type, no-any-unimported]
                try:
                    await pub.publish(channel, payload)
                finally:
                    await pub.aclose()

            asyncio.run(_publish())

        t = threading.Thread(target=_run_publish, daemon=True)
        t.start()
        t.join(timeout=5.0)


def _build_test_app(api_db: ApiDb, bundle: _RedisBundle) -> FastAPI:
    """Wire create_app() with a session override + pre-injected fakeredis."""
    app = create_app()
    app.state.ws_redis = bundle.client

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with api_db.maker() as session:
            yield session

    app.dependency_overrides[get_async_session] = _override_session
    return app


@contextmanager
def _ws_test_client(app: FastAPI) -> Iterator[TestClient]:
    """Lifespan-wired TestClient (so the WsConnectionManager actually starts)."""
    with TestClient(app) as client:
        yield client


def _wait_for_event(
    ws: WebSocketTestSession, deadline_sec: float = 5.0
) -> dict[str, object] | None:
    """Read frames off ``ws`` until a ``type=event`` frame arrives or the deadline."""
    deadline = time.monotonic() + deadline_sec
    while time.monotonic() < deadline:
        frame = ws.receive_json()
        if isinstance(frame, dict) and frame.get("type") == "event":
            return cast("dict[str, object]", frame)
    return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def redis_bundle() -> AsyncIterator[_RedisBundle]:
    """Per-test in-process Redis backed by its own :class:`FakeServer`."""
    server = fakeredis.FakeServer()
    client = fakeredis.aioredis.FakeRedis(server=server, decode_responses=False)
    try:
        yield _RedisBundle(client=client, server=server)
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_token_closes_with_4401(api_db: ApiDb, redis_bundle: _RedisBundle) -> None:
    """Bad JWT → WS upgrade is denied with the custom 4401 close code."""
    app = _build_test_app(api_db, redis_bundle)
    with (
        _ws_test_client(app) as client,
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/ws?token=not-a-real-jwt") as ws,
    ):
        ws.receive_text()
    assert exc.value.code == WS_CLOSE_AUTH


@pytest.mark.asyncio
async def test_missing_token_closes_with_4401(api_db: ApiDb, redis_bundle: _RedisBundle) -> None:
    """Missing ``?token=`` query param → same 4401 close (no anonymous WS)."""
    app = _build_test_app(api_db, redis_bundle)
    with (
        _ws_test_client(app) as client,
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/ws") as ws,
    ):
        ws.receive_text()
    assert exc.value.code == WS_CLOSE_AUTH


@pytest.mark.asyncio
async def test_valid_token_subscribe_ack(api_db: ApiDb, redis_bundle: _RedisBundle) -> None:
    """Valid JWT → 101 upgrade; ``subscribe`` action returns a structured ack."""
    user = await api_db.seed_user(email="ws-sub@example.com")
    token = await _mint_token(str(user.id))
    app = _build_test_app(api_db, redis_bundle)

    with _ws_test_client(app) as client, client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_text(json.dumps({"action": "subscribe", "topic": "run:42"}))
        ack = ws.receive_json()
    assert ack["type"] == "ack"
    assert ack["action"] == "subscribe"
    assert ack["topic"] == "run:42"


@pytest.mark.asyncio
async def test_ping_pong(api_db: ApiDb, redis_bundle: _RedisBundle) -> None:
    """Application-level ping returns a typed pong."""
    user = await api_db.seed_user(email="ws-ping@example.com")
    token = await _mint_token(str(user.id))
    app = _build_test_app(api_db, redis_bundle)

    with _ws_test_client(app) as client, client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_text(json.dumps({"action": "ping"}))
        pong = ws.receive_json()
    assert pong["type"] == "pong"


@pytest.mark.asyncio
async def test_two_clients_receive_published_event(
    api_db: ApiDb, redis_bundle: _RedisBundle
) -> None:
    """Two clients subscribed to the same topic both receive a Redis publish."""
    user = await api_db.seed_user(email="ws-fanout@example.com")
    token = await _mint_token(str(user.id))
    app = _build_test_app(api_db, redis_bundle)

    payload = json.dumps({"event": "run.step.log", "data": {"line": "hello"}})

    with (
        _ws_test_client(app) as client,
        client.websocket_connect(f"/ws?token={token}") as a,
        client.websocket_connect(f"/ws?token={token}") as b,
    ):
        for sock in (a, b):
            sock.send_text(json.dumps({"action": "subscribe", "topic": "run:99"}))
            assert sock.receive_json()["type"] == "ack"

        redis_bundle.publish_on_thread("run:99", payload)

        for sock in (a, b):
            event = _wait_for_event(sock)
            assert event is not None, "client did not receive published event"
            assert event["topic"] == "run:99"
            assert event["event"] == "run.step.log"
            assert event["payload"] == {"line": "hello"}


@pytest.mark.asyncio
async def test_unsubscribe_stops_events(api_db: ApiDb, redis_bundle: _RedisBundle) -> None:
    """After unsubscribe, subsequent publishes do not reach the client."""
    user = await api_db.seed_user(email="ws-unsub@example.com")
    token = await _mint_token(str(user.id))
    app = _build_test_app(api_db, redis_bundle)

    def _payload(line: str) -> str:
        return json.dumps({"event": "run.step.log", "data": {"line": line}})

    with _ws_test_client(app) as client, client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_text(json.dumps({"action": "subscribe", "topic": "run:55"}))
        assert ws.receive_json()["type"] == "ack"

        redis_bundle.publish_on_thread("run:55", _payload("first"))
        first = _wait_for_event(ws)
        assert first is not None
        assert first["payload"] == {"line": "first"}

        ws.send_text(json.dumps({"action": "unsubscribe", "topic": "run:55"}))
        ack = ws.receive_json()
        assert ack["type"] == "ack"
        assert ack["action"] == "unsubscribe"

        # Second publish: should NOT arrive. Verify by sending a ping AFTER
        # the publish — if the publish were delivered, it would arrive
        # before the pong (in-order WS send).
        redis_bundle.publish_on_thread("run:55", _payload("second"))
        # Give the bridge a chance to (not) deliver, without blocking the loop.
        await asyncio.sleep(1.5)
        ws.send_text(json.dumps({"action": "ping"}))

        frames: list[dict[str, object]] = []
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            frame = ws.receive_json()
            frames.append(frame)
            if frame.get("type") == "pong":
                break
        assert any(f.get("type") == "pong" for f in frames)
        assert not any(f.get("type") == "event" for f in frames), (
            f"no event should arrive after unsubscribe; got {frames!r}"
        )


@pytest.mark.asyncio
async def test_disconnect_cleans_up_listeners(api_db: ApiDb, redis_bundle: _RedisBundle) -> None:
    """Closing the WS removes the connection from the manager and frees its channels."""
    user = await api_db.seed_user(email="ws-cleanup@example.com")
    token = await _mint_token(str(user.id))
    app = _build_test_app(api_db, redis_bundle)

    with _ws_test_client(app) as client:
        with client.websocket_connect(f"/ws?token={token}") as ws:
            ws.send_text(json.dumps({"action": "subscribe", "topic": "run:cleanup"}))
            assert ws.receive_json()["type"] == "ack"

            manager = app.state.ws_manager
            assert "run:cleanup" in manager._channel_listeners

        # Allow the cleanup coroutine to run after the context manager closes.
        await asyncio.sleep(0.5)
        manager = app.state.ws_manager
        assert "run:cleanup" not in manager._channel_listeners
        assert manager._connections == {}


@pytest.mark.asyncio
async def test_workspace_topic_requires_membership(
    api_db: ApiDb, redis_bundle: _RedisBundle
) -> None:
    """``workspace:<id>`` subscribe rejected when the user has no membership."""
    user = await api_db.seed_user(email="ws-gate@example.com")
    other_ws = await api_db.seed_workspace(slug="other-ws", name="other")
    # NOTE: no membership inserted; user must NOT be allowed to subscribe.
    token = await _mint_token(str(user.id))
    app = _build_test_app(api_db, redis_bundle)

    with _ws_test_client(app) as client, client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_text(json.dumps({"action": "subscribe", "topic": f"workspace:{other_ws.id}"}))
        err = ws.receive_json()
    assert err["type"] == "error"
    assert err["code"] == "workspace_forbidden"


@pytest.mark.asyncio
async def test_workspace_topic_allowed_when_member(
    api_db: ApiDb, redis_bundle: _RedisBundle
) -> None:
    """Membership in workspace → ``workspace:<id>`` subscribe accepted."""
    user = await api_db.seed_user(email="ws-member@example.com")
    ws_row = await api_db.member_workspace(user, slug="member-ws")
    token = await _mint_token(str(user.id))
    app = _build_test_app(api_db, redis_bundle)

    with _ws_test_client(app) as client, client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_text(json.dumps({"action": "subscribe", "topic": f"workspace:{ws_row.id}"}))
        ack = ws.receive_json()
    assert ack["type"] == "ack"
    assert ack["topic"] == f"workspace:{ws_row.id}"


@pytest.mark.asyncio
async def test_unknown_topic_rejected(api_db: ApiDb, redis_bundle: _RedisBundle) -> None:
    """Topics outside the documented namespaces get ``unknown_topic`` error."""
    user = await api_db.seed_user(email="ws-unknown@example.com")
    token = await _mint_token(str(user.id))
    app = _build_test_app(api_db, redis_bundle)

    with _ws_test_client(app) as client, client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_text(json.dumps({"action": "subscribe", "topic": "evil:7"}))
        err = ws.receive_json()
    assert err["type"] == "error"
    assert err["code"] == "unknown_topic"


@pytest.mark.asyncio
async def test_invalid_frame_returns_soft_error(api_db: ApiDb, redis_bundle: _RedisBundle) -> None:
    """Malformed JSON → soft ``invalid_message`` error, connection stays open."""
    user = await api_db.seed_user(email="ws-malformed@example.com")
    token = await _mint_token(str(user.id))
    app = _build_test_app(api_db, redis_bundle)

    with _ws_test_client(app) as client, client.websocket_connect(f"/ws?token={token}") as ws:
        ws.send_text("not json")
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["code"] == "invalid_message"
        # Connection still open — ping/pong continues to work.
        ws.send_text(json.dumps({"action": "ping"}))
        pong = ws.receive_json()
        assert pong["type"] == "pong"
