"""Invitation repository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from suitest_db.models.invitation import Invitation

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession
    from suitest_shared.domain.enums import Role


class InvitationRepository:
    """Stateful invitation reads/writes."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        workspace_id: str,
        email: str,
        role: Role,
        token_hash: str,
        ttl_hours: int,
        created_by: uuid.UUID | None,
    ) -> Invitation:
        row = Invitation(
            workspace_id=workspace_id,
            email=email.lower(),
            role=role,
            token_hash=token_hash,
            expires_at=datetime.now(tz=UTC) + timedelta(hours=ttl_hours),
            created_by=created_by,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_for_workspace(self, workspace_id: str) -> list[Invitation]:
        rows = await self.session.scalars(
            select(Invitation)
            .where(Invitation.workspace_id == workspace_id)
            .order_by(Invitation.created_at.desc())
        )
        return list(rows.all())

    async def get_by_id(self, invitation_id: str) -> Invitation | None:
        row: Invitation | None = await self.session.scalar(
            select(Invitation)
            .where(Invitation.id == invitation_id)
            .options(selectinload(Invitation.workspace))
        )
        return row

    async def get_active_by_token_hash(self, token_hash: str) -> Invitation | None:
        now = datetime.now(tz=UTC)
        row: Invitation | None = await self.session.scalar(
            select(Invitation)
            .where(
                Invitation.token_hash == token_hash,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > now,
            )
            .options(selectinload(Invitation.workspace))
        )
        return row

    async def revoke(self, invitation: Invitation) -> None:
        invitation.revoked_at = datetime.now(tz=UTC)
        await self.session.flush()

    async def resend(self, invitation: Invitation, *, token_hash: str, ttl_hours: int) -> None:
        invitation.token_hash = token_hash
        invitation.expires_at = datetime.now(tz=UTC) + timedelta(hours=ttl_hours)
        invitation.revoked_at = None
        await self.session.flush()

    async def mark_accepted(self, invitation: Invitation) -> None:
        invitation.accepted_at = datetime.now(tz=UTC)
        await self.session.flush()
