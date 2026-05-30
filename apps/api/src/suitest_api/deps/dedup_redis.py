"""FastAPI dependency: Redis client used for webhook receivers' dedup SETNX (M1d-18).

The Jira webhook receiver (and future GitHub/GitLab receivers on this branch
line) deduplicate ``(workspace_id, issue_key, changelog_id)`` tuples inside a
short TTL window via Redis ``SETNX``. We piggy-back on the existing ARQ pool
(``app.state.arq``) — it's already a ``redis.asyncio.Redis`` subclass with a
connection pool, so opening a second pool just for SETNX would burn file
descriptors without buying isolation we need.

Tests override this dependency with a ``fakeredis.aioredis.FakeRedis`` so the
receiver suite never opens a real broker. The override sidesteps :mod:`arq`
entirely — ``fakeredis`` is enough to satisfy the ``set(nx=True, ex=…)`` call
:mod:`suitest_api.services.webhook_receiver_service` makes.
"""

from __future__ import annotations

from fastapi import Depends

from suitest_api.deps.arq import get_arq


async def get_dedup_redis(arq: object = Depends(get_arq)) -> object:
    """Return a Redis-compatible client for the webhook dedup SETNX call.

    Returns ``object`` (not ``Redis``) because tests inject ``fakeredis`` —
    both satisfy the structural ``set(name, value, *, nx, ex)`` Protocol
    declared on the receiver service. Callers cast at the boundary.
    """
    return arq
