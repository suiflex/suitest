"""Autonomy service (M3-15 / M3-16, docs/AUTONOMY.md §6).

Owns the per-workspace autonomy dial: the level (``manual`` / ``assist`` /
``semi_auto`` / ``auto``) plus per-feature overrides. Level persists on
``WorkspaceCapability.autonomy_level``; overrides live under
``features_json['autonomy_overrides']`` (preserved alongside the M2-9
``routing_overrides``). Every write is audit-logged and recomputes the effective
flag map the gating layer consumes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from suitest_core.autonomy import (
    AutonomyConfig,
    UnknownOverrideKeyError,
    compute_effective,
    validate_overrides,
)
from suitest_core.capabilities import AutonomyLevel as CoreAutonomy
from suitest_core.capabilities import resolve_capabilities
from suitest_db.audit import write_audit
from suitest_db.repositories.workspace_capabilities import WorkspaceCapabilityRepo
from suitest_shared.domain.enums import AutonomyLevel, Tier

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from suitest_api.deps.scope import TenantContext

_OVERRIDES_KEY = "autonomy_overrides"
_UPDATED_BY_KEY = "autonomy_updated_by"


class AutonomyError(Exception):
    """Validation failure on an autonomy write. ``code`` is the API error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AutonomyView:
    """Resolved autonomy state returned to the router (mapped to the API shape)."""

    def __init__(
        self,
        *,
        level: AutonomyLevel,
        overrides: dict[str, bool],
        effective: dict[str, bool],
        tier: Tier,
        updated_at: datetime | None,
        updated_by: str | None,
    ) -> None:
        self.level = level
        self.overrides = overrides
        self.effective = effective
        self.tier = tier
        self.updated_at = updated_at
        self.updated_by = updated_by


class AutonomyService:
    def __init__(self, session: AsyncSession, ctx: TenantContext) -> None:
        self._session = session
        self._ctx = ctx
        self._caps = WorkspaceCapabilityRepo(session)

    async def _resolved_tier(self) -> Tier:
        row = await self._caps.get(self._ctx.workspace_id)
        if row is not None:
            return Tier(row.tier)
        return Tier(resolve_capabilities().tier.value)

    async def get(self) -> AutonomyView:
        """Return the current level + overrides + computed effective map."""
        row = await self._caps.get(self._ctx.workspace_id)
        if row is None:
            tier = Tier(resolve_capabilities().tier.value)
            level = AutonomyLevel.MANUAL
            overrides: dict[str, bool] = {}
            updated_at = None
            updated_by = None
        else:
            tier = Tier(row.tier)
            level = row.autonomy_level
            raw = row.features_json.get(_OVERRIDES_KEY, {})
            overrides = {k: bool(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
            updated_at = row.updated_at
            updated_by_raw = row.features_json.get(_UPDATED_BY_KEY)
            updated_by = updated_by_raw if isinstance(updated_by_raw, str) else None
        effective = compute_effective(
            AutonomyConfig(level=CoreAutonomy(level.value), overrides=overrides)
        )
        return AutonomyView(
            level=level,
            overrides=overrides,
            effective=effective,
            tier=tier,
            updated_at=updated_at,
            updated_by=updated_by,
        )

    async def set(
        self, *, level: AutonomyLevel, overrides: dict[str, bool], reason: str | None
    ) -> AutonomyView:
        """Persist a new autonomy config (validated + audited). ADMIN+ only."""
        tier = await self._resolved_tier()
        if tier is Tier.ZERO and level is not AutonomyLevel.MANUAL:
            raise AutonomyError(
                "AUTONOMY_REQUIRES_LLM",
                "ZERO tier only supports manual autonomy; configure an LLM first",
            )
        try:
            validate_overrides(overrides)
        except UnknownOverrideKeyError as exc:
            raise AutonomyError("UNKNOWN_OVERRIDE_KEY", str(exc)) from exc

        before = await self.get()

        current = await self._caps.get(self._ctx.workspace_id)
        features: dict[str, object] = dict(current.features_json) if current else {}
        features[_OVERRIDES_KEY] = overrides
        if self._ctx.user_id:
            features[_UPDATED_BY_KEY] = self._ctx.user_id

        await self._caps.upsert(
            self._ctx.workspace_id,
            tier=tier,
            autonomy=level,
            features=features,
        )
        await write_audit(
            self._session,
            workspace_id=self._ctx.workspace_id,
            user_id=self._ctx.user_id,
            action="autonomy.update",
            resource_type="workspace",
            resource_id=self._ctx.workspace_id,
            metadata={
                "actor_type": "user",
                "before": {"level": before.level.value, "overrides": before.overrides},
                "after": {"level": level.value, "overrides": overrides},
                "reason": reason,
            },
        )
        await self._session.commit()
        return await self.get()


__all__ = ["AutonomyError", "AutonomyService", "AutonomyView"]
