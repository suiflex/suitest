"""Workspace autonomy — Settings → Automation (M3-15 / M3-16).

Surface (docs/AUTONOMY.md §6):

* ``GET /workspaces/:id/autonomy`` — level + overrides + computed ``effective``
* ``PUT /workspaces/:id/autonomy`` — set level + overrides (ADMIN+), audited

Level + overrides persist on ``workspace_capabilities`` (level column +
``features_json['autonomy_overrides']``). ``effective`` is server-computed from
level + overrides for the UI's convenience. Validation: ZERO tier accepts only
``manual`` (``400 AUTONOMY_REQUIRES_LLM``); unknown override keys are
``400 UNKNOWN_OVERRIDE_KEY``.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_core.autonomy import KNOWN_OVERRIDE_KEYS
from suitest_shared.domain.enums import AutonomyLevel, Role, Tier

from suitest_api.auth.db import get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.services.autonomy_service import AutonomyError, AutonomyService, AutonomyView

router = APIRouter(prefix="/api/v1", tags=["autonomy"])

_ADMIN_ROLES = {Role.ADMIN, Role.OWNER}


class AutonomyResponse(BaseModel):
    """``GET`` / ``PUT`` response — the resolved autonomy state."""

    model_config = ConfigDict(populate_by_name=True)

    level: AutonomyLevel
    overrides: dict[str, bool]
    effective: dict[str, bool]
    tier: Tier
    known_override_keys: list[str] = Field(alias="knownOverrideKeys")
    updated_at: datetime | None = Field(default=None, alias="updatedAt")
    updated_by: str | None = Field(default=None, alias="updatedBy")


class AutonomyUpdate(BaseModel):
    """``PUT`` body — the new level + overrides (+ optional audit reason)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    level: AutonomyLevel
    overrides: dict[str, bool] = Field(default_factory=dict)
    reason: str | None = None


def _to_response(view: AutonomyView) -> AutonomyResponse:
    return AutonomyResponse(
        level=view.level,
        overrides=view.overrides,
        effective=view.effective,
        tier=view.tier,
        known_override_keys=sorted(KNOWN_OVERRIDE_KEYS),
        updated_at=view.updated_at,
        updated_by=view.updated_by,
    )


@router.get("/workspaces/{workspaceId}/autonomy", response_model=AutonomyResponse)
async def get_autonomy(
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> AutonomyResponse:
    """Return the workspace's autonomy level + overrides + effective map."""
    view = await AutonomyService(session, ctx).get()
    return _to_response(view)


@router.put("/workspaces/{workspaceId}/autonomy", response_model=AutonomyResponse)
async def put_autonomy(
    payload: AutonomyUpdate,
    ctx: TenantContext = Depends(require_role(_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_async_session),
) -> AutonomyResponse:
    """Set the workspace's autonomy level + overrides (ADMIN+, audited)."""
    try:
        view = await AutonomyService(session, ctx).set(
            level=payload.level, overrides=payload.overrides, reason=payload.reason
        )
    except AutonomyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    return _to_response(view)
