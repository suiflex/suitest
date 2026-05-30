"""Tests for the ARQ worker scaffolding.

Three slices:
* ``WorkerSettings`` shape — ARQ reads it as a class, so the registered fields
  must be present, well-typed, and aligned with :class:`RunnerSettings`.
* ``run_test_case`` placeholder — returns the documented Task-10 shape so the
  Task 11 swap-in has a contract test to break against.
* Integration smoke — fakeredis-backed enqueue → arq.worker.Worker picks up the
  job → returns the placeholder result, proving the worker actually consumes
  the ``suitest:runs`` queue.
"""

from __future__ import annotations

import asyncio

import pytest
from arq.connections import RedisSettings
from arq.worker import Worker
from suitest_runner.jobs.run_test_case import run_test_case
from suitest_runner.jobs.send_slack_notification import send_slack_notification
from suitest_runner.settings import RunnerSettings
from suitest_runner.worker import WorkerSettings, shutdown, startup


def test_worker_settings_class_attributes() -> None:
    """Sanity-check the class-level attributes ARQ reads."""
    assert WorkerSettings.queue_name == "suitest:runs"
    assert WorkerSettings.max_jobs == RunnerSettings().max_jobs_concurrent
    assert WorkerSettings.job_timeout == RunnerSettings().job_timeout_seconds
    assert WorkerSettings.keep_result == RunnerSettings().keep_result_seconds


def test_worker_functions_registry() -> None:
    """ARQ-registered job list — ``run_test_case`` (M1c) + ``send_slack_notification`` (M1d-15)."""
    assert WorkerSettings.functions == [run_test_case, send_slack_notification]


def test_worker_redis_settings_dsn() -> None:
    """The wired RedisSettings should round-trip the default DSN."""
    expected = RedisSettings.from_dsn(RunnerSettings().redis_url)
    assert WorkerSettings.redis_settings.host == expected.host
    assert WorkerSettings.redis_settings.port == expected.port
    assert WorkerSettings.redis_settings.database == expected.database


@pytest.mark.asyncio
async def test_run_test_case_rejects_bare_ctx() -> None:
    """The real orchestrator (M1c Task 12) reports a structured error when ARQ
    hasn't populated the required ``session_factory`` / ``invoker`` / ``registry``
    keys — the worker still drains the message instead of crashing the loop."""
    ctx: dict[str, object] = {"job_id": "j-1"}
    result = await run_test_case(ctx, "r-123")
    assert isinstance(result, dict)
    assert result.get("error") == "RUNNER_CTX_INVALID"
    assert result.get("field") == "session_factory"


@pytest.mark.asyncio
async def test_startup_populates_ctx(monkeypatch: pytest.MonkeyPatch) -> None:
    """``startup`` must populate the documented ``ctx`` keys.

    We point the engine at a harmless sqlite-async URL so the test never opens
    a Postgres connection — the engine is lazy, so ``create_async_engine`` just
    builds the URL/dialect without dialing out.
    """
    monkeypatch.setenv("SUITEST_RUNNER_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("SUITEST_RUNNER_REDIS_URL", "redis://localhost:6379/15")
    ctx: dict[str, object] = {}
    await startup(ctx)
    try:
        assert "settings" in ctx
        assert "engine" in ctx
        assert "session_factory" in ctx
        assert "redis" in ctx
        assert "registry" in ctx
        assert "pool" in ctx
        assert "invoker" in ctx
        settings = ctx["settings"]
        assert isinstance(settings, RunnerSettings)
        assert settings.database_url == "sqlite+aiosqlite:///:memory:"
    finally:
        await shutdown(ctx)


@pytest.mark.asyncio
async def test_enqueue_and_run_smoke(monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end: enqueue ``run_test_case`` against fakeredis and let an ARQ
    :class:`Worker` drain it. Proves the wiring (queue name + function name +
    result shape) is consistent — the real broker swap is identical from ARQ's
    perspective.

    We back ARQ's ``ArqRedis`` with a fakeredis async connection pool so the
    enqueue path AND the worker share the same in-memory broker.
    """
    pytest.importorskip("fakeredis")
    from arq.connections import ArqRedis
    from fakeredis import FakeAsyncRedisConnection, FakeServer
    from redis.asyncio.connection import ConnectionPool

    # Single shared backing server — both the enqueue ArqRedis and the Worker's
    # pool MUST hit the same Redis state, otherwise the job would be enqueued
    # into a different "broker" than the worker drains. ``FakeServer`` is the
    # in-memory storage; the redis-py-shaped ``ConnectionPool`` wires it into
    # the same pool type ArqRedis already expects.
    server = FakeServer(version=(7,))
    pool = ConnectionPool(connection_class=FakeAsyncRedisConnection, server=server)
    arq_pool = ArqRedis(pool_or_conn=pool)

    # ``arq.worker.Worker.main`` calls ``log_redis_info`` (a ``pipeline().INFO``
    # round-trip) before draining the queue. fakeredis doesn't implement the
    # INFO command, so we replace it with a no-op for the smoke test. The
    # patch needs to hit the symbol imported into ``arq.worker`` (Python
    # binds at import time), not the source in ``arq.connections``.
    async def _noop_log_redis_info(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("arq.worker.log_redis_info", _noop_log_redis_info)

    job = await arq_pool.enqueue_job(
        "run_test_case", "r-smoke", _queue_name=WorkerSettings.queue_name
    )
    assert job is not None

    # Build a worker bound to the same ArqRedis so enqueue + drain share state.
    worker = Worker(
        # ARQ types ``functions`` as ``Sequence[Function | WorkerCoroutine]``
        # — bare ``async def`` callables satisfy the runtime contract but
        # mypy can't narrow the class-level attribute that way without an
        # ARQ-side stub fix.
        functions=WorkerSettings.functions,  # type: ignore[arg-type]
        redis_pool=arq_pool,
        queue_name=WorkerSettings.queue_name,
        max_jobs=1,
        burst=True,
        poll_delay=0.0,
        handle_signals=False,
        health_check_interval=3600,
    )
    try:
        # ``burst=True`` makes Worker.main() exit as soon as the queue drains.
        await asyncio.wait_for(worker.main(), timeout=5.0)
    finally:
        await worker.close()

    result = await job.result(timeout=2.0)
    # With the Task 12 orchestrator the worker's ``ctx`` here is empty (the
    # Worker.__init__ in this smoke test bypasses ``WorkerSettings.on_startup``)
    # so the job reports the structured RUNNER_CTX_INVALID error rather than
    # crashing. The shape proves enqueue → drain → result still wires through.
    assert isinstance(result, dict)
    assert result.get("error") == "RUNNER_CTX_INVALID"
    assert result.get("field") == "session_factory"

    await arq_pool.aclose()
