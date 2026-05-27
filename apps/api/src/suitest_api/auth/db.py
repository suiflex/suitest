"""Database wiring for FastAPI-Users.

Provides a session factory bound to the configured database URL and a
``get_user_db`` dependency that yields a SQLAlchemyUserDatabase for the
auth manager.
"""

import uuid
from collections.abc import AsyncIterator

from fastapi import Depends
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from suitest_db.models.user import OAuthAccount, User

from suitest_api.settings import get_settings

_settings = get_settings()

engine = create_async_engine(_settings.database_url, future=True, pool_pre_ping=True)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """Yield an async SQLAlchemy session scoped to the request."""
    async with async_session_maker() as session:
        yield session


async def get_user_db(
    session: AsyncSession = Depends(get_async_session),  # noqa: B008  -- FastAPI DI idiom
) -> AsyncIterator[SQLAlchemyUserDatabase[User, uuid.UUID]]:
    """Yield the FastAPI-Users SQLAlchemy adapter bound to User + OAuthAccount."""
    yield SQLAlchemyUserDatabase(session, User, OAuthAccount)
