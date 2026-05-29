"""FastAPI dependency: shared :class:`arq.connections.ArqRedis` pool.

The pool is constructed once per app on first call and stashed on
``app.state.arq`` so subsequent requests reuse it (ARQ's ``ArqRedis`` is a
:class:`redis.asyncio.Redis` subclass with a connection pool — opening a fresh
client per request would burn a TCP connect on the hot path).

The redis URL is resolved from ``SUITEST_REDIS_URL`` (the same env var the WS
gateway + rate limiter consume). Tests inject a fakeredis-backed
:class:`ArqRedis` via ``app.dependency_overrides[get_arq]`` so the create-run
test never opens a real broker.
"""

from __future__ import annotations

import os

from arq.connections import ArqRedis, RedisSettings, create_pool
from fastapi import Request


async def get_arq(request: Request) -> ArqRedis:
    """Return a shared :class:`ArqRedis` for ``app.state.arq``, building it on first hit.

    Builds the pool from ``SUITEST_REDIS_URL`` (defaults to
    ``redis://localhost:6379/0`` when unset, matching docker-compose dev). The
    pool is cached on ``app.state.arq`` so the same instance is reused for the
    process lifetime; the lifespan in ``main.py`` does not own this slot, so
    tests can override the dependency without coordinating with lifespan
    startup.
    """
    existing = getattr(request.app.state, "arq", None)
    if isinstance(existing, ArqRedis):
        return existing
    url = os.environ.get("SUITEST_REDIS_URL", "redis://localhost:6379/0")
    pool = await create_pool(RedisSettings.from_dsn(url))
    request.app.state.arq = pool
    return pool
