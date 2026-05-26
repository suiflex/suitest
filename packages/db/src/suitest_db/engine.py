"""Async engine + session factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from suitest_db.settings import DbSettings


def make_engine(settings: DbSettings | None = None) -> AsyncEngine:
    """Construct an async engine. Caller owns the lifecycle (dispose())."""
    cfg = settings or DbSettings()
    return create_async_engine(
        cfg.database_url,
        echo=cfg.echo_sql,
        pool_size=cfg.pool_size,
        max_overflow=cfg.max_overflow,
        pool_pre_ping=True,
        future=True,
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Bind a session factory to the provided engine."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def lifespan_engine(
    settings: DbSettings | None = None,
) -> AsyncIterator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]]]:
    """Async context manager that yields (engine, session_factory) and disposes."""
    engine = make_engine(settings)
    try:
        yield engine, make_session_factory(engine)
    finally:
        await engine.dispose()
