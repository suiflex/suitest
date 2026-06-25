"""Cost tracking service (M3-14 + M7, docs/CAPABILITY_TIERS.md §12).

Aggregates ``AgentSession.cost_usd`` + token counts (stamped by every LLM
generator / diagnosis run via LiteLLM's ``completion_cost``) into per-workspace,
per-provider, and per-kind rollups, plus budget enforcement.

M3: soft daily budget guard (advisory only — flags ``over_budget``).
M7: hard-stop via ``check_user_hard_stop()``, per-user caps via ``UserBudget``,
    auto-downgrade model selection via ``get_cheaper_model()``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from suitest_db.models.agent import AgentSession
from suitest_db.repositories.llm_configs import LLMConfigRepo
from suitest_db.repositories.user_budgets import UserBudgetRepo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_log = logging.getLogger(__name__)
_DEFAULT_DAILY_CAP_USD = 50.0

# ---------------------------------------------------------------------------
# Auto-downgrade model map (M7-2)
# ---------------------------------------------------------------------------
_DOWNGRADE_MAP: dict[str, str] = {
    # Anthropic
    "claude-opus-4-5": "claude-sonnet-4-5",
    "claude-opus-4": "claude-sonnet-4",
    "claude-opus-3-5": "claude-sonnet-3-5",
    "claude-opus-3": "claude-sonnet-3",
    "claude-sonnet-4-5": "claude-haiku-3-5",
    "claude-sonnet-4": "claude-haiku-3",
    "claude-sonnet-3-5": "claude-haiku-3",
    "claude-sonnet-3": "claude-haiku-3",
    # OpenAI
    "gpt-4o": "gpt-3.5-turbo",
    "gpt-4-turbo": "gpt-3.5-turbo",
    "gpt-4": "gpt-3.5-turbo",
    "gpt-4-32k": "gpt-3.5-turbo",
    # Google
    "gemini-pro": "gemini-flash",
    "gemini-1.5-pro": "gemini-1.5-flash",
    "gemini-2.0-pro": "gemini-2.0-flash",
}


def get_cheaper_model(current_model: str, spend_usd: float, threshold_usd: float) -> str | None:
    """Return a cheaper model alias if ``spend_usd > threshold_usd``, else ``None``.

    The downgrade map covers common Anthropic, OpenAI and Google models.  If the
    current model has no known cheaper alternative, or spend has not yet crossed
    the threshold, ``None`` is returned and the caller should use the original
    model unchanged.

    Args:
        current_model: The bare model id (e.g. ``"claude-opus-4-5"``).
        spend_usd: Current workspace spend for the relevant window (today).
        threshold_usd: The ``auto_downgrade_threshold_usd`` from LLMConfig.
            Pass ``0`` or a negative value to always treat as "below threshold".

    Returns:
        Cheaper model string, or ``None`` when no downgrade is needed/known.
    """
    if threshold_usd <= 0 or spend_usd <= threshold_usd:
        return None
    # Normalise: strip provider prefix if present (e.g. "anthropic/claude-opus-4-5")
    bare = current_model.split("/")[-1].lower()
    cheaper = _DOWNGRADE_MAP.get(bare)
    if cheaper:
        _log.warning(
            "auto_downgrade: spend=$%.4f > threshold=$%.4f, switching %s → %s",
            spend_usd,
            threshold_usd,
            current_model,
            cheaper,
        )
    return cheaper


# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------


class ProviderCost:
    def __init__(
        self, provider: str, cost_usd: float, tokens_in: int, tokens_out: int, sessions: int
    ) -> None:
        self.provider = provider
        self.cost_usd = cost_usd
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.sessions = sessions


class KindCost:
    def __init__(self, kind: str, cost_usd: float, sessions: int) -> None:
        self.kind = kind
        self.cost_usd = cost_usd
        self.sessions = sessions


class Budget:
    def __init__(self, daily_cap_usd: float, today_spend_usd: float) -> None:
        self.daily_cap_usd = daily_cap_usd
        self.today_spend_usd = today_spend_usd
        self.over_budget = today_spend_usd >= daily_cap_usd
        self.alert: str | None = (
            f"Daily LLM spend ${today_spend_usd:.2f} has reached the ${daily_cap_usd:.2f} cap."
            if self.over_budget
            else None
        )


class UserSpend:
    """Per-user spend summary for M7 user-budget endpoints."""

    def __init__(
        self,
        user_id: uuid.UUID,
        daily_cap_usd: float,
        monthly_cap_usd: float,
        today_spend_usd: float,
        month_spend_usd: float,
    ) -> None:
        self.user_id = user_id
        self.daily_cap_usd = daily_cap_usd
        self.monthly_cap_usd = monthly_cap_usd
        self.today_spend_usd = today_spend_usd
        self.month_spend_usd = month_spend_usd
        self.daily_over = daily_cap_usd > 0 and today_spend_usd >= daily_cap_usd
        self.monthly_over = monthly_cap_usd > 0 and month_spend_usd >= monthly_cap_usd


class CostSummary:
    def __init__(
        self,
        *,
        total_cost_usd: float,
        total_tokens_in: int,
        total_tokens_out: int,
        session_count: int,
        window_days: int,
        by_provider: list[ProviderCost],
        by_kind: list[KindCost],
        budget: Budget,
    ) -> None:
        self.total_cost_usd = total_cost_usd
        self.total_tokens_in = total_tokens_in
        self.total_tokens_out = total_tokens_out
        self.session_count = session_count
        self.window_days = window_days
        self.by_provider = by_provider
        self.by_kind = by_kind
        self.budget = budget


def _f(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class CostService:
    def __init__(self, session: AsyncSession, workspace_id: str) -> None:
        self._session = session
        self._workspace_id = workspace_id

    async def summary(self, *, window_days: int = 30, now: datetime | None = None) -> CostSummary:
        """Aggregate spend over the trailing ``window_days`` + today's budget."""
        current = now or datetime.now(tz=UTC)
        window_start = current - timedelta(days=window_days)
        ws = self._workspace_id

        totals_stmt = select(
            func.coalesce(func.sum(AgentSession.cost_usd), 0),
            func.coalesce(func.sum(AgentSession.tokens_in), 0),
            func.coalesce(func.sum(AgentSession.tokens_out), 0),
            func.count(AgentSession.id),
        ).where(AgentSession.workspace_id == ws, AgentSession.started_at >= window_start)
        total_cost, tokens_in, tokens_out, count = (await self._session.execute(totals_stmt)).one()

        provider_stmt = (
            select(
                AgentSession.provider,
                func.coalesce(func.sum(AgentSession.cost_usd), 0),
                func.coalesce(func.sum(AgentSession.tokens_in), 0),
                func.coalesce(func.sum(AgentSession.tokens_out), 0),
                func.count(AgentSession.id),
            )
            .where(AgentSession.workspace_id == ws, AgentSession.started_at >= window_start)
            .group_by(AgentSession.provider)
            .order_by(func.coalesce(func.sum(AgentSession.cost_usd), 0).desc())
        )
        by_provider = [
            ProviderCost(p, _f(c), int(ti), int(to), int(s))
            for p, c, ti, to, s in (await self._session.execute(provider_stmt)).all()
        ]

        kind_stmt = (
            select(
                AgentSession.kind,
                func.coalesce(func.sum(AgentSession.cost_usd), 0),
                func.count(AgentSession.id),
            )
            .where(AgentSession.workspace_id == ws, AgentSession.started_at >= window_start)
            .group_by(AgentSession.kind)
        )
        by_kind = [
            KindCost(k.value if hasattr(k, "value") else str(k), _f(c), int(s))
            for k, c, s in (await self._session.execute(kind_stmt)).all()
        ]

        day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        today_stmt = select(func.coalesce(func.sum(AgentSession.cost_usd), 0)).where(
            AgentSession.workspace_id == ws, AgentSession.started_at >= day_start
        )
        today_spend = _f((await self._session.execute(today_stmt)).scalar_one())

        budget = Budget(daily_cap_usd=await self._daily_cap(), today_spend_usd=today_spend)
        return CostSummary(
            total_cost_usd=_f(total_cost),
            total_tokens_in=int(tokens_in),
            total_tokens_out=int(tokens_out),
            session_count=int(count),
            window_days=window_days,
            by_provider=by_provider,
            by_kind=by_kind,
            budget=budget,
        )

    async def per_user_summary(
        self,
        user_id: uuid.UUID,
        *,
        now: datetime | None = None,
    ) -> UserSpend:
        """Return today/month spend + caps for a single user in this workspace.

        Caps are read from ``user_budgets``; spend is aggregated from
        ``agent_sessions`` filtered by ``(workspace_id, user_id)``.
        """
        current = now or datetime.now(tz=UTC)
        day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ws = self._workspace_id

        today_stmt = select(func.coalesce(func.sum(AgentSession.cost_usd), 0)).where(
            AgentSession.workspace_id == ws,
            AgentSession.user_id == user_id,
            AgentSession.started_at >= day_start,
        )
        today_spend = _f((await self._session.execute(today_stmt)).scalar_one())

        month_stmt = select(func.coalesce(func.sum(AgentSession.cost_usd), 0)).where(
            AgentSession.workspace_id == ws,
            AgentSession.user_id == user_id,
            AgentSession.started_at >= month_start,
        )
        month_spend = _f((await self._session.execute(month_stmt)).scalar_one())

        budget_row = await UserBudgetRepo(self._session).get_by_workspace_user(ws, user_id)
        daily_cap = _f(budget_row.daily_cap_usd) if budget_row else 0.0
        monthly_cap = _f(budget_row.monthly_cap_usd) if budget_row else 0.0

        return UserSpend(
            user_id=user_id,
            daily_cap_usd=daily_cap,
            monthly_cap_usd=monthly_cap,
            today_spend_usd=today_spend,
            month_spend_usd=month_spend,
        )

    async def check_user_hard_stop(
        self,
        user_id: uuid.UUID,
        *,
        now: datetime | None = None,
    ) -> tuple[bool, str, float, float]:
        """Check whether the user has exceeded their daily or monthly cap.

        Returns:
            ``(exceeded, limit_type, cap_usd, current_usd)`` where ``exceeded``
            is ``True`` when a hard stop should be applied. ``limit_type`` is
            ``"daily"`` or ``"monthly"``; ``cap_usd`` is the configured cap;
            ``current_usd`` is the accumulated spend in that window.

            When no cap is configured (cap == 0) or spend is within limits,
            ``exceeded`` is ``False`` and the other values are zero/empty strings.
        """
        spend = await self.per_user_summary(user_id, now=now)

        if spend.daily_cap_usd > 0 and spend.today_spend_usd >= spend.daily_cap_usd:
            return True, "daily", spend.daily_cap_usd, spend.today_spend_usd

        if spend.monthly_cap_usd > 0 and spend.month_spend_usd >= spend.monthly_cap_usd:
            return True, "monthly", spend.monthly_cap_usd, spend.month_spend_usd

        return False, "", 0.0, 0.0

    async def workspace_today_spend(self, *, now: datetime | None = None) -> float:
        """Return total workspace spend today (used by LiteLLM auto-downgrade check)."""
        current = now or datetime.now(tz=UTC)
        day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = select(func.coalesce(func.sum(AgentSession.cost_usd), 0)).where(
            AgentSession.workspace_id == self._workspace_id,
            AgentSession.started_at >= day_start,
        )
        return _f((await self._session.execute(stmt)).scalar_one())

    async def auto_downgrade_threshold(self) -> float | None:
        """Read ``auto_downgrade_threshold_usd`` from the active LLMConfig.

        Returns ``None`` if the workspace has no active config or the field is
        unset — meaning auto-downgrade is disabled.
        """
        config = await LLMConfigRepo(self._session).get_active(self._workspace_id)
        if config is None:
            return None
        raw = config.config_json.get("auto_downgrade_threshold_usd")
        if isinstance(raw, (int, float)) and raw > 0:
            return float(raw)
        return None

    async def _daily_cap(self) -> float:
        """Resolve the daily cap from the active LLMConfig (default $50)."""
        config = await LLMConfigRepo(self._session).get_active(self._workspace_id)
        if config is None:
            return _DEFAULT_DAILY_CAP_USD
        raw = config.config_json.get("daily_cap_usd")
        if isinstance(raw, (int, float)) and raw > 0:
            return float(raw)
        return _DEFAULT_DAILY_CAP_USD
