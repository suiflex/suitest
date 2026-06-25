"""UserBudget repository (M7-1)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select
from suitest_db.models.user_budget import UserBudget
from suitest_db.repositories.base import AsyncRepository


class UserBudgetCreate(BaseModel):
    workspace_id: str
    user_id: uuid.UUID
    daily_cap_usd: Decimal = Decimal("0")
    monthly_cap_usd: Decimal = Decimal("0")


class UserBudgetUpdate(BaseModel):
    daily_cap_usd: Decimal | None = None
    monthly_cap_usd: Decimal | None = None


class UserBudgetRepo(AsyncRepository[UserBudget, UserBudgetCreate, UserBudgetUpdate]):
    model = UserBudget

    async def get_by_workspace_user(
        self, workspace_id: str, user_id: uuid.UUID
    ) -> UserBudget | None:
        """Return the budget row for ``(workspace_id, user_id)``, or ``None``."""
        result: UserBudget | None = await self.session.scalar(
            select(UserBudget).where(
                UserBudget.workspace_id == workspace_id,
                UserBudget.user_id == user_id,
            )
        )
        return result

    async def list_for_workspace(self, workspace_id: str) -> list[UserBudget]:
        """Return all budget rows for a workspace, ordered by creation time."""
        rows = list(
            (
                await self.session.scalars(
                    select(UserBudget)
                    .where(UserBudget.workspace_id == workspace_id)
                    .order_by(UserBudget.created_at.asc())
                )
            ).all()
        )
        return rows

    async def upsert(
        self,
        workspace_id: str,
        user_id: uuid.UUID,
        daily_cap_usd: Decimal,
        monthly_cap_usd: Decimal,
    ) -> UserBudget:
        """Create or update the budget row for ``(workspace_id, user_id)``."""
        row = await self.get_by_workspace_user(workspace_id, user_id)
        if row is None:
            row = UserBudget(
                workspace_id=workspace_id,
                user_id=user_id,
                daily_cap_usd=daily_cap_usd,
                monthly_cap_usd=monthly_cap_usd,
            )
            self.session.add(row)
        else:
            row.daily_cap_usd = daily_cap_usd
            row.monthly_cap_usd = monthly_cap_usd
        await self.session.flush()
        return row

    async def delete_by_workspace_user(self, workspace_id: str, user_id: uuid.UUID) -> bool:
        """Delete the budget row; return True if it existed."""
        row = await self.get_by_workspace_user(workspace_id, user_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True
