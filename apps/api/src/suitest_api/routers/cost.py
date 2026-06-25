"""Workspace cost tracking (M3-14 + M7) — Insights → Cost.

``GET /workspaces/:id/cost`` returns per-provider + per-kind spend rollups.
``POST /workspaces/:id/cost/user-limits`` sets per-user daily/monthly caps (M7-1).
``GET /workspaces/:id/cost/user-limits`` lists all user budget caps (M7-1).
``DELETE /workspaces/:id/cost/user-limits/:userId`` removes a user cap (M7-1).

Admin/Owner only for write operations; any workspace member may read the
aggregate cost endpoint.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.audit import write_audit
from suitest_db.repositories.user_budgets import UserBudgetRepo
from suitest_shared.domain.enums import Role

from suitest_api.auth.db import get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.services.cost_service import CostService, CostSummary

router = APIRouter(prefix="/api/v1", tags=["cost"])

_ADMIN_ROLES: set[Role] = {Role.ADMIN, Role.OWNER}


# ---------------------------------------------------------------------------
# Pydantic output models
# ---------------------------------------------------------------------------


class ProviderCostOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: str
    cost_usd: float = Field(alias="costUsd")
    tokens_in: int = Field(alias="tokensIn")
    tokens_out: int = Field(alias="tokensOut")
    sessions: int


class KindCostOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kind: str
    cost_usd: float = Field(alias="costUsd")
    sessions: int


class BudgetOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    daily_cap_usd: float = Field(alias="dailyCapUsd")
    today_spend_usd: float = Field(alias="todaySpendUsd")
    over_budget: bool = Field(alias="overBudget")
    alert: str | None = None


class CostSummaryOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    total_cost_usd: float = Field(alias="totalCostUsd")
    total_tokens_in: int = Field(alias="totalTokensIn")
    total_tokens_out: int = Field(alias="totalTokensOut")
    session_count: int = Field(alias="sessionCount")
    window_days: int = Field(alias="windowDays")
    by_provider: list[ProviderCostOut] = Field(alias="byProvider")
    by_kind: list[KindCostOut] = Field(alias="byKind")
    budget: BudgetOut


class UserLimitIn(BaseModel):
    """Request body for ``POST /cost/user-limits``."""

    model_config = ConfigDict(populate_by_name=True)

    user_id: uuid.UUID = Field(alias="userId")
    daily_cap_usd: Decimal = Field(default=Decimal("0"), alias="dailyCapUsd", ge=0)
    monthly_cap_usd: Decimal = Field(default=Decimal("0"), alias="monthlyCapUsd", ge=0)


class UserLimitOut(BaseModel):
    """Response body for user-budget endpoints."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    user_id: uuid.UUID = Field(alias="userId")
    workspace_id: str = Field(alias="workspaceId")
    daily_cap_usd: float = Field(alias="dailyCapUsd")
    monthly_cap_usd: float = Field(alias="monthlyCapUsd")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_out(summary: CostSummary) -> CostSummaryOut:
    return CostSummaryOut(
        total_cost_usd=round(summary.total_cost_usd, 6),
        total_tokens_in=summary.total_tokens_in,
        total_tokens_out=summary.total_tokens_out,
        session_count=summary.session_count,
        window_days=summary.window_days,
        by_provider=[
            ProviderCostOut(
                provider=p.provider,
                cost_usd=round(p.cost_usd, 6),
                tokens_in=p.tokens_in,
                tokens_out=p.tokens_out,
                sessions=p.sessions,
            )
            for p in summary.by_provider
        ],
        by_kind=[
            KindCostOut(kind=k.kind, cost_usd=round(k.cost_usd, 6), sessions=k.sessions)
            for k in summary.by_kind
        ],
        budget=BudgetOut(
            daily_cap_usd=summary.budget.daily_cap_usd,
            today_spend_usd=round(summary.budget.today_spend_usd, 6),
            over_budget=summary.budget.over_budget,
            alert=summary.budget.alert,
        ),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/workspaces/{workspaceId}/cost", response_model=CostSummaryOut)
async def get_workspace_cost(
    window_days: Annotated[int, Query(ge=1, le=365, alias="windowDays")] = 30,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> CostSummaryOut:
    """Return per-provider / per-kind spend + soft daily budget for the workspace."""
    summary = await CostService(session, ctx.workspace_id).summary(window_days=window_days)
    return _to_out(summary)


@router.post(
    "/workspaces/{workspaceId}/cost/user-limits",
    response_model=UserLimitOut,
    status_code=status.HTTP_200_OK,
)
async def upsert_user_limit(
    body: UserLimitIn,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> UserLimitOut:
    """Set (or replace) the per-user daily/monthly LLM spend cap.

    Admin or Owner only. Setting ``dailyCapUsd`` or ``monthlyCapUsd`` to 0
    means unlimited for that window.
    """
    repo = UserBudgetRepo(session)
    row = await repo.upsert(
        ctx.workspace_id,
        body.user_id,
        daily_cap_usd=body.daily_cap_usd,
        monthly_cap_usd=body.monthly_cap_usd,
    )
    await write_audit(
        session,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        action="upsert",
        resource_type="user_budget",
        resource_id=row.id,
        metadata={
            "target_user_id": str(body.user_id),
            "daily_cap_usd": str(body.daily_cap_usd),
            "monthly_cap_usd": str(body.monthly_cap_usd),
        },
    )
    await session.commit()
    return UserLimitOut(
        id=row.id,
        user_id=row.user_id,
        workspace_id=row.workspace_id,
        daily_cap_usd=float(row.daily_cap_usd),
        monthly_cap_usd=float(row.monthly_cap_usd),
    )


@router.get("/workspaces/{workspaceId}/cost/user-limits", response_model=list[UserLimitOut])
async def list_user_limits(
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> list[UserLimitOut]:
    """List all per-user spend caps for the workspace. Admin or Owner only."""
    rows = await UserBudgetRepo(session).list_for_workspace(ctx.workspace_id)
    return [
        UserLimitOut(
            id=r.id,
            user_id=r.user_id,
            workspace_id=r.workspace_id,
            daily_cap_usd=float(r.daily_cap_usd),
            monthly_cap_usd=float(r.monthly_cap_usd),
        )
        for r in rows
    ]


@router.delete(
    "/workspaces/{workspaceId}/cost/user-limits/{userId}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user_limit(
    userId: uuid.UUID,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Remove a per-user spend cap. Admin or Owner only."""
    deleted = await UserBudgetRepo(session).delete_by_workspace_user(ctx.workspace_id, userId)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No budget limit found for user {userId} in this workspace.",
        )
    await write_audit(
        session,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        action="delete",
        resource_type="user_budget",
        resource_id=str(userId),
        metadata={"target_user_id": str(userId)},
    )
    await session.commit()
