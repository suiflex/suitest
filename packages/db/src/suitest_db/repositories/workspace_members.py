"""Workspace membership repository (M1d-28).

The Members tab of ``/settings/workspace`` mutates this table via:

* ``POST   /workspaces/:id/members``           — invite by email + role
* ``PATCH  /workspaces/:id/members/:user_id``  — change role
* ``DELETE /workspaces/:id/members/:user_id``  — remove member

All three operations share the same workspace-scoped queries below. The
sole-OWNER guard (``count_owners``) is consulted by the service layer before
demote/remove to surface ``SOLE_OWNER_PROTECTED`` (400) without ever leaving
the workspace ownerless.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from suitest_db.models.tenancy import Membership
from suitest_db.models.user import User
from suitest_shared.domain.enums import Role

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class WorkspaceMembershipRepo:
    """Workspace-scoped membership reads + writes used by M1d-28 settings."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, workspace_id: str, user_id: uuid.UUID) -> Membership | None:
        result: Membership | None = await self.session.scalar(
            select(Membership)
            .where(Membership.workspace_id == workspace_id, Membership.user_id == user_id)
            .options(selectinload(Membership.user))
        )
        return result

    async def find_user_by_email(self, email: str) -> User | None:
        """Case-insensitive email lookup — invite-by-email picks up existing users."""
        result: User | None = await self.session.scalar(
            select(User).where(func.lower(User.email) == email.lower())
        )
        return result

    async def add(self, *, workspace_id: str, user_id: uuid.UUID, role: Role) -> Membership:
        """Insert a fresh membership row and flush so PK + ``created_at`` resolve."""
        row = Membership(workspace_id=workspace_id, user_id=user_id, role=role)
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row, ["user"])
        return row

    async def change_role(self, membership: Membership, role: Role) -> Membership:
        membership.role = role
        await self.session.flush()
        return membership

    async def delete(self, membership: Membership) -> None:
        await self.session.delete(membership)
        await self.session.flush()

    async def count_owners(self, workspace_id: str) -> int:
        """Return the number of ``OWNER``-role memberships for a workspace.

        Powers the sole-OWNER guard — demoting / removing the last OWNER must
        fail with ``SOLE_OWNER_PROTECTED`` so the workspace stays administrable.
        """
        result = await self.session.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.workspace_id == workspace_id, Membership.role == Role.OWNER)
        )
        return int(result or 0)


async def create_placeholder_user(
    session: AsyncSession, *, email: str, name: str | None = None
) -> User:
    """Insert a User row for an invite-by-email that does not match an existing user.

    The full invitation-email flow (verification token, set-password screen) is
    out of scope for M1d-28 — we create a non-verified, non-active user with a
    random unusable password hash so the membership can attach. A follow-up
    invitation system (M2+) will activate the account on first login.

    ``hashed_password`` is filled with a per-row random base64 token so the row
    cannot collide on the (theoretical) password constraint and the user
    literally cannot log in via password until the invitation flow completes.
    """
    import base64
    import secrets

    row = User(
        id=uuid.uuid4(),
        email=email,
        # 32 bytes of randomness, base64'd → not a valid password hash, by design.
        hashed_password="!" + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        is_active=False,
        is_superuser=False,
        is_verified=False,
        name=name or email.split("@", 1)[0],
    )
    session.add(row)
    await session.flush()
    return row
