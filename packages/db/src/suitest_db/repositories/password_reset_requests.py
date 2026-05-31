"""Password reset request repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from suitest_db.models.password_reset_request import PasswordResetRequest

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class PasswordResetRequestRepository:
    """Read/write helper for reset requests."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        email: str,
        token_hash: str,
        reset_link_encrypted: str | None,
        expires_at: datetime,
    ) -> PasswordResetRequest:
        row = PasswordResetRequest(
            email=email.lower(),
            token_hash=token_hash,
            reset_link_encrypted=reset_link_encrypted,
            expires_at=expires_at,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def list_recent(self, *, limit: int = 50) -> list[PasswordResetRequest]:
        rows = await self.session.scalars(
            select(PasswordResetRequest)
            .order_by(PasswordResetRequest.created_at.desc())
            .limit(limit)
        )
        return list(rows.all())

    async def mark_used_by_hash(self, token_hash: str) -> None:
        row = await self.session.scalar(
            select(PasswordResetRequest).where(
                PasswordResetRequest.token_hash == token_hash,
                PasswordResetRequest.used_at.is_(None),
            )
        )
        if row is not None:
            row.used_at = datetime.now(tz=UTC)
            await self.session.flush()
