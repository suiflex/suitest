"""Cost tracking service (M3-14, docs/CAPABILITY_TIERS.md §12).

Aggregates ``AgentSession.cost_usd`` + token counts (stamped by every LLM
generator / diagnosis run via LiteLLM's ``completion_cost``) into per-workspace,
per-provider, and per-kind rollups, plus a **soft** daily budget guard: when the
day's spend crosses the workspace cap (``LLMConfig.config_json.daily_cap_usd``,
default $50) the response flags ``over_budget`` + an ``alert`` string. The guard
is advisory in M3 — it never blocks a request (hard stop is v1.x / M7).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from suitest_db.models.agent import AgentSession
from suitest_db.repositories.llm_configs import LLMConfigRepo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_DEFAULT_DAILY_CAP_USD = 50.0


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

    async def _daily_cap(self) -> float:
        """Resolve the daily cap from the active LLMConfig (default $50)."""
        config = await LLMConfigRepo(self._session).get_active(self._workspace_id)
        if config is None:
            return _DEFAULT_DAILY_CAP_USD
        raw = config.config_json.get("daily_cap_usd")
        if isinstance(raw, (int, float)) and raw > 0:
            return float(raw)
        return _DEFAULT_DAILY_CAP_USD
