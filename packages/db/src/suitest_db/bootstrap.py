"""Schema creation for local mode (SQLite) — straight from models, no Alembic.

ponytail: fresh local DBs only. There is no local-schema upgrade path between
releases yet — add versioning (e.g. PRAGMA user_version) once local mode first
needs a migration.
"""

from sqlalchemy.ext.asyncio import AsyncEngine

import suitest_db.models  # noqa: F401  # side-effect: register every model on Base.metadata
from suitest_db.base import Base


async def create_local_schema(engine: AsyncEngine) -> None:
    """Create all tables for a fresh local database."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _main() -> None:
    """CLI: create the local schema at ``SUITEST_DATABASE_URL``. Idempotent."""
    import asyncio
    import os

    from sqlalchemy.ext.asyncio import create_async_engine

    url = os.environ.get("SUITEST_DATABASE_URL")
    if not url:
        raise SystemExit("SUITEST_DATABASE_URL is not set")

    async def _run() -> None:
        engine = create_async_engine(url)
        try:
            await create_local_schema(engine)
        finally:
            await engine.dispose()

    asyncio.run(_run())


if __name__ == "__main__":
    _main()
