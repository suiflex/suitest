"""Per-audience rate-limit tests (Task 12, docs/API.md §5).

The middleware applies slowapi's ``default_limits`` to every request keyed by
``_audience_key`` (Bearer / cookie session / client IP). These tests exercise:

1. Under-threshold burst passes (no spurious 429s).
2. Over-threshold returns 429 with a ``Retry-After`` header (slowapi default).
3. Different audiences hash to different buckets — exhausting user A leaves
   user B unaffected.
4. Switching the *same* connection from cookie to Bearer flips the bucket and
   keeps headroom available.

The production default (600/min) would be slow to exhaust in a unit test, so
every test patches :func:`suitest_api.middleware.ratelimit.build_limiter` BEFORE
``create_app`` runs so the FastAPI factory installs a tight-budget limiter.
``memory://`` storage is used throughout — fakeredis is available for future
Redis-specific tests but slowapi treats both backends identically through the
``limits`` library, so the in-process memory store is the natural fit here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from suitest_api.main import create_app
from suitest_api.middleware import ratelimit as ratelimit_module


def _install_tight_limiter(monkeypatch: pytest.MonkeyPatch, *, limit: str) -> None:
    """Patch :func:`build_limiter` so a subsequent ``create_app`` gets a tight cap.

    Patches BOTH the source module and ``suitest_api.main`` (which imported the
    symbol into its own namespace). Must be called BEFORE ``create_app``.
    """
    real_build = ratelimit_module.build_limiter

    def _build_tight() -> object:
        return real_build(storage_uri="memory://", default_limits=[limit])

    monkeypatch.setattr(ratelimit_module, "build_limiter", _build_tight)
    import suitest_api.main as main_module

    monkeypatch.setattr(main_module, "build_limiter", _build_tight)


@pytest_asyncio.fixture
async def make_app() -> AsyncIterator[Callable[[], Awaitable[ASGITransport]]]:
    """Yield a factory that builds + boots a fresh app on demand.

    The caller patches ``build_limiter`` first, then calls the factory; this
    guarantees each test's limiter is built AFTER its monkeypatch is in place.
    The fixture tracks lifespan managers and clients so they are all closed at
    teardown regardless of how the test exits.
    """
    managers: list[LifespanManager] = []
    clients: list[AsyncClient] = []

    async def _factory() -> ASGITransport:
        app = create_app()
        manager = LifespanManager(app)
        await manager.__aenter__()
        managers.append(manager)
        return ASGITransport(app=app)

    try:
        yield _factory
    finally:
        for c in clients:
            await c.aclose()
        for m in reversed(managers):
            await m.__aexit__(None, None, None)


def _new_client(
    transport: ASGITransport,
    *,
    cookies: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> AsyncClient:
    """Construct an ``AsyncClient`` pointed at the in-process ASGI transport."""
    return AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies=cookies,
        headers=headers,
    )


@pytest.mark.asyncio
async def test_ratelimit_under_threshold_passes(
    monkeypatch: pytest.MonkeyPatch,
    make_app: Callable[[], Awaitable[ASGITransport]],
) -> None:
    """A burst of 100 requests under a 200/min cap all return 200."""
    _install_tight_limiter(monkeypatch, limit="200/minute")
    transport = await make_app()
    async with _new_client(transport) as client:
        for _ in range(100):
            response = await client.get("/health")
            assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_ratelimit_over_threshold_429(
    monkeypatch: pytest.MonkeyPatch,
    make_app: Callable[[], Awaitable[ASGITransport]],
) -> None:
    """The (limit+1)th request returns 429 with a Retry-After header."""
    _install_tight_limiter(monkeypatch, limit="5/minute")
    transport = await make_app()
    async with _new_client(transport) as client:
        # First 5 requests fit inside the bucket.
        for _ in range(5):
            ok = await client.get("/health")
            assert ok.status_code == 200, ok.text

        # 6th request trips the limit.
        blocked = await client.get("/health")
        assert blocked.status_code == 429, blocked.text
        header_keys = {h.lower() for h in blocked.headers}
        assert "retry-after" in header_keys, dict(blocked.headers)


@pytest.mark.asyncio
async def test_ratelimit_different_users_separate_buckets(
    monkeypatch: pytest.MonkeyPatch,
    make_app: Callable[[], Awaitable[ASGITransport]],
) -> None:
    """Exhausting user A's bucket must NOT leak into user B's bucket."""
    _install_tight_limiter(monkeypatch, limit="3/minute")
    transport = await make_app()

    cookies_a = {"suitest_session": "session-token-for-maya"}
    cookies_b = {"suitest_session": "session-token-for-budi"}

    async with _new_client(transport, cookies=cookies_a) as client_a:
        for _ in range(3):
            ok = await client_a.get("/health")
            assert ok.status_code == 200, ok.text
        blocked = await client_a.get("/health")
        assert blocked.status_code == 429, blocked.text

    # User B starts from a clean bucket — different cookie hashes to a different
    # ``_audience_key`` ("user:<sha256(cookie)[:16]>") so the limit is independent.
    async with _new_client(transport, cookies=cookies_b) as client_b:
        for _ in range(3):
            ok = await client_b.get("/health")
            assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_ratelimit_bearer_higher_threshold(
    monkeypatch: pytest.MonkeyPatch,
    make_app: Callable[[], Awaitable[ASGITransport]],
) -> None:
    """A Bearer-token client and a cookie client hash to different buckets.

    Today the default cap is the same for both audiences (single
    ``default_limits``). The audience-tiered cap (1000/min for Bearer) lands as a
    per-route override in M4 when SDK endpoints arrive. This test pins the
    foundation: the keying scheme already separates Bearer from cookie buckets,
    so an exhausted cookie audience does not block a Bearer-authenticated SDK
    caller on the same connection.
    """
    _install_tight_limiter(monkeypatch, limit="2/minute")
    transport = await make_app()

    # Cookie audience: burn the budget.
    async with _new_client(transport, cookies={"suitest_session": "browser-x"}) as cookie_client:
        for _ in range(2):
            ok = await cookie_client.get("/health")
            assert ok.status_code == 200, ok.text
        blocked = await cookie_client.get("/health")
        assert blocked.status_code == 429, blocked.text

    # Bearer audience: ``token:<hash>`` bucket is independent of the user bucket.
    bearer_headers = {"Authorization": "Bearer suit_carlos_sdk_token"}
    async with _new_client(transport, headers=bearer_headers) as bearer_client:
        for _ in range(2):
            ok = await bearer_client.get("/health")
            assert ok.status_code == 200, ok.text
