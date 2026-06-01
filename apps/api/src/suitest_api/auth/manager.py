"""FastAPI-Users user manager, auth backend, and OAuth client wiring."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    CookieTransport,
    JWTStrategy,
)
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from suitest_core import crypto
from suitest_db.models.user import User
from suitest_db.repositories.password_reset_requests import PasswordResetRequestRepository

from suitest_api.auth.db import get_user_db
from suitest_api.services.invitation_service import hash_token
from suitest_api.settings import get_settings

_settings = get_settings()


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """Suitest user manager. Stub on_after_* hooks for M0."""

    reset_password_token_secret = _settings.auth_secret
    verification_token_secret = _settings.auth_secret

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        """Hook fired after a new user is registered. No-op for M0."""
        return None

    async def on_after_forgot_password(
        self, user: User, token: str, request: Request | None = None
    ) -> None:
        """Persist reset-token metadata for super-admin review until SMTP exists.

        The reset link is a bearer credential: it is stored encrypted at rest via
        ``packages/core`` AES-GCM (the ``EncryptedBytes`` column encrypts on write).
        When no encryption key is configured we persist ONLY the token hash and
        leave ``reset_link_encrypted`` NULL — the review endpoint then returns 503.
        The token and link are never logged.
        """
        session = getattr(self.user_db, "session", None)
        if session is None:
            return None
        # Only persist the link when it can be encrypted at rest. Without a key,
        # store the token hash alone (link stays NULL). Never plaintext.
        reset_link_encrypted: str | None = None
        if crypto.is_configured():
            reset_link_encrypted = f"{_settings.web_url}/reset-password?token={token}"
        await PasswordResetRequestRepository(session).create(
            email=user.email,
            token_hash=hash_token(token),
            reset_link_encrypted=reset_link_encrypted,
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        )
        await session.commit()
        return None


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase[User, uuid.UUID] = Depends(get_user_db),  # noqa: B008  -- FastAPI DI idiom
) -> AsyncIterator[UserManager]:
    """Yield the UserManager dependency for routes."""
    yield UserManager(user_db)


cookie_transport = CookieTransport(
    cookie_name="suitest_session",
    cookie_max_age=60 * 60 * 24 * 14,  # 14 days
    # Env-driven (``SUITEST_COOKIE_SECURE``): default False for dev over plain
    # HTTP; production behind HTTPS MUST flip this to True so the session cookie
    # is never sent in cleartext. See settings.cookie_secure for the contract.
    cookie_secure=_settings.cookie_secure,
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


# Bearer transport over the SAME JWT strategy so CI integrations / SDK clients
# (docs/API.md §3.1) can authenticate via ``Authorization: Bearer <jwt>`` instead
# of the browser session cookie. ``tokenUrl`` points at the cookie-login route
# purely for OpenAPI's auth flow docs; tokens are minted by ``get_jwt_strategy``.
bearer_transport = BearerTransport(tokenUrl="api/v1/auth/cookie/login")
bearer_backend = AuthenticationBackend(
    name="jwt-bearer",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)


fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend, bearer_backend])

# Convenience dependency: yields the current authenticated + active User, or 401.
current_active_user = fastapi_users.current_user(active=True)
