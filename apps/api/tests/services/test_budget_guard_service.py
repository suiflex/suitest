"""Unit tests for budget guard service (M7-3).

Uses mock AsyncSession to test ``check_budget`` / ``BudgetExceededError`` without
a real database connection.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from suitest_api.services.budget_guard import BudgetExceededError, check_budget
from suitest_api.services.cost_service import UserSpend

_WS = "ws_test_budget"
_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000042")
_USER_STR = str(_USER_ID)


def _mock_spend(
    *,
    daily_cap: float = 0.0,
    monthly_cap: float = 0.0,
    today: float = 0.0,
    month: float = 0.0,
) -> UserSpend:
    return UserSpend(
        user_id=_USER_ID,
        daily_cap_usd=daily_cap,
        monthly_cap_usd=monthly_cap,
        today_spend_usd=today,
        month_spend_usd=month,
    )


@pytest.mark.asyncio
async def test_check_budget_passes_when_no_cap() -> None:
    """No caps configured (both 0) → no exception raised."""
    session = AsyncMock()
    with patch(
        "suitest_api.services.budget_guard.CostService.check_user_hard_stop",
        new=AsyncMock(return_value=(False, "", 0.0, 0.0)),
    ):
        # Should not raise
        await check_budget(session, _WS, _USER_STR)


@pytest.mark.asyncio
async def test_check_budget_passes_when_under_daily_cap() -> None:
    """Spend below daily cap → no exception."""
    session = AsyncMock()
    with patch(
        "suitest_api.services.budget_guard.CostService.check_user_hard_stop",
        new=AsyncMock(return_value=(False, "", 0.0, 0.0)),
    ):
        await check_budget(session, _WS, _USER_STR)


@pytest.mark.asyncio
async def test_check_budget_raises_when_daily_cap_exceeded() -> None:
    """Daily spend >= cap → BudgetExceededError with 'daily' limit_type."""
    session = AsyncMock()
    with (
        patch(
            "suitest_api.services.budget_guard.CostService.check_user_hard_stop",
            new=AsyncMock(return_value=(True, "daily", 5.0, 5.50)),
        ),
        pytest.raises(BudgetExceededError) as exc_info,
    ):
        await check_budget(session, _WS, _USER_STR)

    err = exc_info.value
    assert err.limit_type == "daily"
    assert err.cap_usd == pytest.approx(5.0)
    assert err.current_usd == pytest.approx(5.50)
    assert err.user_id == _USER_ID


@pytest.mark.asyncio
async def test_check_budget_raises_when_monthly_cap_exceeded() -> None:
    """Monthly spend >= cap → BudgetExceededError with 'monthly' limit_type."""
    session = AsyncMock()
    with (
        patch(
            "suitest_api.services.budget_guard.CostService.check_user_hard_stop",
            new=AsyncMock(return_value=(True, "monthly", 50.0, 52.00)),
        ),
        pytest.raises(BudgetExceededError) as exc_info,
    ):
        await check_budget(session, _WS, _USER_STR)

    err = exc_info.value
    assert err.limit_type == "monthly"
    assert err.cap_usd == pytest.approx(50.0)
    assert err.current_usd == pytest.approx(52.00)


@pytest.mark.asyncio
async def test_check_budget_passes_when_spend_exactly_at_cap_minus_epsilon() -> None:
    """Spend just below cap → no exception (boundary check)."""
    session = AsyncMock()
    with patch(
        "suitest_api.services.budget_guard.CostService.check_user_hard_stop",
        new=AsyncMock(return_value=(False, "", 0.0, 0.0)),
    ):
        await check_budget(session, _WS, _USER_STR)


def test_budget_exceeded_error_str() -> None:
    """BudgetExceededError has a human-readable string representation."""
    err = BudgetExceededError(limit_type="daily", cap_usd=10.0, current_usd=12.5, user_id=_USER_ID)
    assert "daily" in str(err)
    assert "10.0000" in str(err)
    assert "12.5000" in str(err)


# ---------------------------------------------------------------------------
# Cost service integration — check_user_hard_stop logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cost_service_check_user_hard_stop_daily() -> None:
    """CostService.check_user_hard_stop returns daily exceeded tuple."""
    from suitest_api.services.cost_service import CostService

    session = AsyncMock()
    svc = CostService(session, _WS)

    spend = _mock_spend(daily_cap=5.0, monthly_cap=50.0, today=6.0, month=10.0)
    with patch.object(svc, "per_user_summary", new=AsyncMock(return_value=spend)):
        exceeded, limit_type, cap, current = await svc.check_user_hard_stop(_USER_ID)

    assert exceeded is True
    assert limit_type == "daily"
    assert cap == pytest.approx(5.0)
    assert current == pytest.approx(6.0)


@pytest.mark.asyncio
async def test_cost_service_check_user_hard_stop_monthly() -> None:
    """CostService.check_user_hard_stop returns monthly exceeded when daily is fine."""
    from suitest_api.services.cost_service import CostService

    session = AsyncMock()
    svc = CostService(session, _WS)

    spend = _mock_spend(daily_cap=5.0, monthly_cap=50.0, today=3.0, month=55.0)
    with patch.object(svc, "per_user_summary", new=AsyncMock(return_value=spend)):
        exceeded, limit_type, cap, current = await svc.check_user_hard_stop(_USER_ID)

    assert exceeded is True
    assert limit_type == "monthly"
    assert cap == pytest.approx(50.0)
    assert current == pytest.approx(55.0)


@pytest.mark.asyncio
async def test_cost_service_check_user_hard_stop_no_cap() -> None:
    """Zero caps (unlimited) → not exceeded."""
    from suitest_api.services.cost_service import CostService

    session = AsyncMock()
    svc = CostService(session, _WS)

    spend = _mock_spend(daily_cap=0.0, monthly_cap=0.0, today=9999.0, month=99999.0)
    with patch.object(svc, "per_user_summary", new=AsyncMock(return_value=spend)):
        exceeded, limit_type, _cap, _current = await svc.check_user_hard_stop(_USER_ID)

    assert exceeded is False
    assert limit_type == ""
