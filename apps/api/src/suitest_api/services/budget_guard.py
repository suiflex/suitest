"""Budget guard dependency — M7-3 hard-stop when user exceeds their LLM spend cap.

Usage in any route that makes LLM calls::

    @router.post("/agent/generate")
    async def generate(
        ...,
        _tier: None = Depends(require_tier(TierFlag.CLOUD | TierFlag.LOCAL)),
        _budget: None = Depends(require_budget_available),
    ):
        ...

``require_budget_available`` reads the :class:`~suitest_db.models.user_budget.UserBudget`
row for the authenticated user + current workspace and raises ``HTTP 429`` with a
structured ``BUDGET_EXCEEDED`` body if either the daily or monthly cap is breached.
When no budget row exists (or all caps are 0 = unlimited) the check passes silently.
"""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from suitest_api.auth.db import get_async_session
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.services.cost_service import CostService


class BudgetExceededError(Exception):
    """Raised by ``check_budget`` when a hard spend limit has been crossed.

    Carries the structured details needed for the HTTP 429 response body.
    """

    def __init__(
        self,
        limit_type: str,
        cap_usd: float,
        current_usd: float,
        user_id: uuid.UUID,
    ) -> None:
        self.limit_type = limit_type
        self.cap_usd = cap_usd
        self.current_usd = current_usd
        self.user_id = user_id
        super().__init__(
            f"Budget exceeded: {limit_type} cap ${cap_usd:.4f}, "
            f"current ${current_usd:.4f} for user {user_id}"
        )


async def check_budget(
    session: AsyncSession,
    workspace_id: str,
    user_id: str,
) -> None:
    """Raise :class:`BudgetExceededError` if the user has exceeded their daily/monthly cap.

    Args:
        session: Async SQLAlchemy session (transaction-scoped).
        workspace_id: The resolved workspace ID from the tenant context.
        user_id: The authenticated user's ID (as a string UUID).

    Raises:
        BudgetExceededError: When a configured cap (daily or monthly) has been
            reached or exceeded.  Does nothing when no cap row exists or all
            caps are 0 (unlimited).
    """
    uid = uuid.UUID(user_id)
    svc = CostService(session, workspace_id)
    exceeded, limit_type, cap_usd, current_usd = await svc.check_user_hard_stop(uid)
    if exceeded:
        raise BudgetExceededError(
            limit_type=limit_type,
            cap_usd=cap_usd,
            current_usd=current_usd,
            user_id=uid,
        )


async def require_budget_available(
    ctx: TenantContext = Depends(require_workspace_membership),  # noqa: B008
    session: AsyncSession = Depends(get_async_session),  # noqa: B008
) -> None:
    """FastAPI dependency: block the request with HTTP 429 when over budget.

    Raises:
        HTTPException(429): Structured ``BUDGET_EXCEEDED`` error when the
            authenticated user has reached their configured spend cap.
    """
    try:
        await check_budget(session, ctx.workspace_id, ctx.user_id)
    except BudgetExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": {
                    "code": "BUDGET_EXCEEDED",
                    "message": (
                        f"Your {exc.limit_type} LLM spend limit of "
                        f"${exc.cap_usd:.2f} has been reached "
                        f"(current: ${exc.current_usd:.2f}). "
                        "Contact your workspace admin to increase the cap."
                    ),
                    "details": {
                        "limit_type": exc.limit_type,
                        "cap_usd": exc.cap_usd,
                        "current_usd": exc.current_usd,
                    },
                }
            },
        ) from exc
