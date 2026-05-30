"""FastAPI dependency: Redis client used for webhook dedup SETNX (M1d-16..18).

The webhook receivers (GitLab push, GitHub push/PR, Jira issue_updated) all
de-duplicate event tuples inside a short TTL window via Redis ``SETNX``:
- GitHub/GitLab: ``(project_id, commit_sha, trigger)``
- Jira: ``(workspace_id, issue_key, changelog_id)``

We piggy-back on the existing ARQ pool (``app.state.arq``) — it's already a
``redis.asyncio.Redis`` subclass with a connection pool, so opening a second
pool just for SETNX would burn file descriptors without buying isolation we
need.

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
