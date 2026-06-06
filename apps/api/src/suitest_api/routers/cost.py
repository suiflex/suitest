"""Workspace cost tracking (M3-14) — Insights → Cost.

``GET /workspaces/:id/cost`` returns per-provider + per-kind spend rollups over a
trailing window plus a **soft** daily budget guard (advisory only in M3). Any
workspace member may read it.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from suitest_api.auth.db import get_async_session
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.services.cost_service import CostService, CostSummary

router = APIRouter(prefix="/api/v1", tags=["cost"])


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


@router.get("/workspaces/{workspaceId}/cost", response_model=CostSummaryOut)
async def get_workspace_cost(
    window_days: Annotated[int, Query(ge=1, le=365, alias="windowDays")] = 30,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> CostSummaryOut:
    """Return per-provider / per-kind spend + soft daily budget for the workspace."""
    summary = await CostService(session, ctx.workspace_id).summary(window_days=window_days)
    return _to_out(summary)
