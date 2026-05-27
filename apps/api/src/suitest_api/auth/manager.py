"""FastAPI-Users user manager, auth backend, and OAuth client wiring."""

import uuid
from collections.abc import AsyncIterator

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import (
    AuthenticationBackend,
    CookieTransport,
    JWTStrategy,
)
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from suitest_db.models.user import User

from suitest_api.auth.db import get_user_db
from suitest_api.settings import get_settings

_settings = get_settings()


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """Suitest user manager. Stub on_after_* hooks for M0."""

    reset_password_token_secret = _settings.auth_secret
    verification_token_secret = _settings.auth_secret

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        """Hook fired after a new user is registered. No-op for M0."""
        return None


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase[User, uuid.UUID] = Depends(get_user_db),  # noqa: B008  -- FastAPI DI idiom
) -> AsyncIterator[UserManager]:
    """Yield the UserManager dependency for routes."""
    yield UserManager(user_db)


cookie_transport = CookieTransport(
    cookie_name="suitest_session",
    cookie_max_age=60 * 60 * 24 * 14,  # 14 days
    cookie_secure=False,  # set True behind HTTPS in production
    cookie_httponly=True,
    cookie_samesite="lax",
)


def get_jwt_strategy() -> JWTStrategy[User, uuid.UUID]:
    """JWT strategy keyed off SUITEST_AUTH_SECRET."""
    return JWTStrategy(secret=get_settings().auth_secret, lifetime_seconds=60 * 60 * 24 * 14)


auth_backend = AuthenticationBackend(
    name="cookie-jwt",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)


fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

# Convenience dependency: yields the current authenticated + active User, or 401.
current_active_user = fastapi_users.current_user(active=True)
