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
