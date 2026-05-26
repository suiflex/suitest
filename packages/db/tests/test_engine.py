"""Smoke tests for the async engine + session factory."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from suitest_db.engine import lifespan_engine, make_engine, make_session_factory
from suitest_db.settings import DbSettings


def test_make_engine_uses_settings() -> None:
    """make_engine() honours DbSettings (URL passed through to engine)."""
    settings = DbSettings()
    engine = make_engine(settings)
    try:
        # AsyncEngine wraps a sync URL object.
        assert str(engine.url) == settings.database_url.replace(
            "suitest:suitest", "suitest:***"
        ) or settings.database_url in str(engine.url)
        assert engine.pool is not None  # pool is constructed
    finally:
        # Synchronous dispose path — no event loop running.
        engine.sync_engine.dispose()


def test_make_session_factory_binds_engine() -> None:
    """Session factory binds back to the originating engine."""
    engine = make_engine()
    try:
        factory = make_session_factory(engine)
        session = factory()
        assert session.bind is engine
    finally:
        engine.sync_engine.dispose()


@pytest.mark.asyncio
async def test_lifespan_engine_executes_select_one() -> None:
    """Full lifecycle: open engine -> session -> SELECT 1 -> dispose."""
    async with lifespan_engine() as (engine, session_factory):
        async with session_factory() as session:
            result = await session.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
        # engine still alive inside the context
        assert engine is not None
    # post-context: engine disposed. We can't easily assert disposed state
    # publicly, but no exception means cleanup succeeded.
