"""Password management services."""

from __future__ import annotations

import secrets
import uuid

from fastapi_users.password import PasswordHelper
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.user import User


class PasswordError(Exception):
    """Base password service error."""


class InvalidCurrentPasswordError(PasswordError):
    """Current password did not verify."""


class UserNotFoundError(PasswordError):
    """Target user does not exist."""


class PasswordService:
    """Own-password and super-admin password reset operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.password_helper = PasswordHelper()

    async def change_own_password(
        self, *, user: User, current_password: str, new_password: str
    ) -> None:
        # Load the authoritative row first and verify against ITS hash. The
        # injected ``user`` may carry a stale ``hashed_password`` (e.g. it was
        # rotated earlier in the request), and we are about to mutate the DB row,
        # so the check and the write must target the same authoritative state.
        db_user = await self.session.get(User, user.id)
        if db_user is None:
            raise UserNotFoundError
        ok, _ = self.password_helper.verify_and_update(current_password, db_user.hashed_password)
        if not ok:
            raise InvalidCurrentPasswordError
        db_user.hashed_password = self.password_helper.hash(new_password)
        db_user.must_change_password = False
        await self.session.flush()

    async def reset_user_password_as_superadmin(
        self, *, actor: User, target_user_id: uuid.UUID
    ) -> str:
        # Re-load the actor: a privilege check must read the authoritative DB
        # row, never a passed-in object whose ``is_superuser`` may be stale.
        db_actor = await self.session.get(User, actor.id)
        if db_actor is None or not db_actor.is_superuser:
            raise PermissionError
        target = await self.session.get(User, target_user_id)
        if target is None:
            raise UserNotFoundError
        temporary_password = secrets.token_urlsafe(18)
        target.hashed_password = self.password_helper.hash(temporary_password)
        target.must_change_password = True
        await self.session.flush()
        return temporary_password
