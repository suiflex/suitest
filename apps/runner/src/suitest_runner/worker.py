"""ARQ worker entrypoint. M0 has no jobs registered — real jobs ship in M1."""

from __future__ import annotations

import os

from arq.connections import RedisSettings


async def heartbeat(ctx: dict[str, object]) -> str:
    """Dummy job so ARQ has at least one registered function in M0."""
    _ = ctx
    return "ok"


class WorkerSettings:
    """ARQ worker settings consumed by `arq` CLI."""

    functions = [heartbeat]  # noqa: RUF012  # ARQ reads this as a class attribute
    redis_settings = RedisSettings.from_dsn(os.getenv("SUITEST_REDIS_URL", "redis://redis:6379/0"))
    max_jobs = 8
    job_timeout = 60
    keep_result = 60
