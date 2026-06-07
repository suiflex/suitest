"""Workspace prompt-fork endpoints (M5-3).

A DB-backed override layer on top of the file-based default prompts. Reads
(list defaults, view a prompt + its forks) are available to any workspace
member; fork mutations require ADMIN+ and are tier-gated to LOCAL/CLOUD since a
prompt fork only matters when an LLM is configured. The file default is always
the fallback, so the ZERO/default path is never affected.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from suitest_agent.prompts.loader import PromptNotFoundError, list_prompts, prompt_hash, read_prompt
from suitest_core.capabilities import TierFlag
from suitest_db.audit import write_audit
from suitest_db.repositories.prompt_experiments import PromptExperimentCreate, PromptExperimentRepo
from suitest_db.repositories.workspace_prompt_overrides import WorkspacePromptOverrideRepo
from suitest_shared.domain.enums import Role

from suitest_api.auth.db import get_async_session
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.deps.tier import require_tier
from suitest_api.schemas.prompts import (
    ExperimentOutcomeBody,
    ExperimentVariantStats,
    PromptDefaultPublic,
    PromptDetailPublic,
    PromptExperimentCreateBody,
    PromptExperimentListEnvelope,
    PromptExperimentPublic,
    PromptForkCreate,
    PromptForkPublic,
    PromptListEnvelope,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from suitest_db.models.prompt_experiment import PromptExperiment
    from suitest_db.models.workspace_prompt_override import WorkspacePromptOverride

router = APIRouter(prefix="/api/v1", tags=["prompts"])

_FORK_ROLES: set[Role] = {Role.ADMIN, Role.OWNER}
_BASE_VERSION = "v1"


def _as_uuid(user_id: str | None) -> uuid.UUID | None:
    """Coerce the string ``ctx.user_id`` to a UUID for ``created_by`` (None-safe)."""
    try:
        return uuid.UUID(user_id) if user_id else None
    except (ValueError, AttributeError):
        return None


def _fork_public(row: WorkspacePromptOverride, *, with_content: bool) -> PromptForkPublic:
    return PromptForkPublic(
        id=row.id,
        prompt_name=row.prompt_name,
        base_version=row.base_version,
        fork_version=row.fork_version,
        label=row.label,
        is_active=row.is_active,
        hash=row.hash,
        content=row.content if with_content else None,
        created_at=row.created_at,
    )


@router.get("/prompts", response_model=PromptListEnvelope)
async def list_default_prompts(
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> PromptListEnvelope:
    """List every overridable default prompt + whether the workspace forks it."""
    active_by_name: dict[str, int] = {}
    for row in await WorkspacePromptOverrideRepo(session).list_for_workspace(ctx.workspace_id):
        if row.is_active:
            active_by_name[row.prompt_name] = row.fork_version
    items = [
        PromptDefaultPublic(
            name=name,
            base_version=_BASE_VERSION,
            has_active_fork=name in active_by_name,
            active_fork_version=active_by_name.get(name),
        )
        for name in list_prompts(_BASE_VERSION)
    ]
    return PromptListEnvelope(items=items)


@router.get("/prompts/{prompt_name}", response_model=PromptDetailPublic)
async def get_prompt_detail(
    prompt_name: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> PromptDetailPublic:
    """Return a prompt's file default content + the workspace's fork history."""
    try:
        default_content = read_prompt(prompt_name, _BASE_VERSION)
    except PromptNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="prompt not found"
        ) from exc
    forks = await WorkspacePromptOverrideRepo(session).list_for_workspace(
        ctx.workspace_id, prompt_name=prompt_name
    )
    return PromptDetailPublic(
        name=prompt_name,
        base_version=_BASE_VERSION,
        default_content=default_content,
        forks=[_fork_public(f, with_content=True) for f in forks],
    )


@router.post(
    "/prompts/{prompt_name}/forks",
    response_model=PromptForkPublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(_FORK_ROLES))],
)
@require_tier(TierFlag.CLOUD | TierFlag.LOCAL)
async def create_prompt_fork(
    prompt_name: str,
    body: PromptForkCreate,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> PromptForkPublic:
    """Create a new versioned fork of ``prompt_name`` for the workspace."""
    # The prompt must exist as a file default to be forkable.
    try:
        read_prompt(prompt_name, body.base_version)
    except PromptNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="prompt not found"
        ) from exc
    row = await WorkspacePromptOverrideRepo(session).create_fork(
        workspace_id=ctx.workspace_id,
        prompt_name=prompt_name,
        base_version=body.base_version,
        content=body.content,
        content_hash=prompt_hash(body.content),
        label=body.label,
        created_by=_as_uuid(ctx.user_id),
        activate=body.activate,
    )
    await write_audit(
        session,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        action="prompt.fork.create",
        resource_type="workspace_prompt_override",
        resource_id=row.id,
        metadata={"prompt_name": prompt_name, "fork_version": row.fork_version},
    )
    await session.commit()
    await session.refresh(row)
    return _fork_public(row, with_content=True)


@router.post(
    "/prompts/forks/{override_id}/activate",
    response_model=PromptForkPublic,
    dependencies=[Depends(require_role(_FORK_ROLES))],
)
@require_tier(TierFlag.CLOUD | TierFlag.LOCAL)
async def activate_prompt_fork(
    override_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> PromptForkPublic:
    """Make a specific fork the active override for its prompt."""
    row = await WorkspacePromptOverrideRepo(session).activate(ctx.workspace_id, override_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="fork not found")
    await write_audit(
        session,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        action="prompt.fork.activate",
        resource_type="workspace_prompt_override",
        resource_id=row.id,
        metadata={"prompt_name": row.prompt_name, "fork_version": row.fork_version},
    )
    await session.commit()
    await session.refresh(row)
    return _fork_public(row, with_content=True)


@router.delete(
    "/prompts/forks/{override_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(_FORK_ROLES))],
)
@require_tier(TierFlag.CLOUD | TierFlag.LOCAL)
async def delete_prompt_fork(
    override_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Delete a fork. Reverts the prompt to the file default if it was active."""
    repo = WorkspacePromptOverrideRepo(session)
    row = await repo.get_by_id(override_id)
    if row is None or row.workspace_id != ctx.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="fork not found")
    await session.delete(row)
    await write_audit(
        session,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        action="prompt.fork.delete",
        resource_type="workspace_prompt_override",
        resource_id=override_id,
        metadata={"prompt_name": row.prompt_name},
    )
    await session.commit()


# ---------------------------------------------------------------------------
# Prompt A/B experiments (M5-4).
# ---------------------------------------------------------------------------


def _conversion(successes: int, impressions: int) -> float:
    return round(100.0 * successes / impressions, 1) if impressions else 0.0


def _experiment_public(exp: PromptExperiment) -> PromptExperimentPublic:
    a = ExperimentVariantStats(
        variant="A",
        override_id=exp.variant_a_override_id,
        impressions=exp.a_impressions,
        successes=exp.a_successes,
        conversion_pct=_conversion(exp.a_successes, exp.a_impressions),
    )
    b = ExperimentVariantStats(
        variant="B",
        override_id=exp.variant_b_override_id,
        impressions=exp.b_impressions,
        successes=exp.b_successes,
        conversion_pct=_conversion(exp.b_successes, exp.b_impressions),
    )
    # Declare a winner only once both variants have data, by conversion rate.
    winner: str | None = None
    if a.impressions > 0 and b.impressions > 0 and a.conversion_pct != b.conversion_pct:
        winner = "A" if a.conversion_pct > b.conversion_pct else "B"
    return PromptExperimentPublic(
        id=exp.id,
        prompt_name=exp.prompt_name,
        status=exp.status,
        split_pct=exp.split_pct,
        variant_a=a,
        variant_b=b,
        winner=winner,
        created_at=exp.created_at,
    )


@router.get("/prompt-experiments", response_model=PromptExperimentListEnvelope)
async def list_prompt_experiments(
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> PromptExperimentListEnvelope:
    """List the workspace's prompt A/B experiments with live stats."""
    rows = await PromptExperimentRepo(session).list_for_workspace(ctx.workspace_id)
    return PromptExperimentListEnvelope(items=[_experiment_public(r) for r in rows])


@router.post(
    "/prompt-experiments",
    response_model=PromptExperimentPublic,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(_FORK_ROLES))],
)
@require_tier(TierFlag.CLOUD | TierFlag.LOCAL)
async def create_prompt_experiment(
    body: PromptExperimentCreateBody,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> PromptExperimentPublic:
    """Start an A/B test between two variants of ``prompt_name``.

    A variant override id of ``null`` means the file default. The prompt must
    exist as a file default; referenced forks must belong to this workspace.
    """
    try:
        read_prompt(body.prompt_name, _BASE_VERSION)
    except PromptNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="prompt not found"
        ) from exc
    fork_repo = WorkspacePromptOverrideRepo(session)
    for override_id in (body.variant_a_override_id, body.variant_b_override_id):
        if override_id is None:
            continue
        fork = await fork_repo.get_by_id(override_id)
        if fork is None or fork.workspace_id != ctx.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="variant fork not found"
            )
    repo = PromptExperimentRepo(session)
    row = await repo.create(
        PromptExperimentCreate(
            workspace_id=ctx.workspace_id,
            prompt_name=body.prompt_name,
            variant_a_override_id=body.variant_a_override_id,
            variant_b_override_id=body.variant_b_override_id,
            split_pct=body.split_pct,
            created_by=_as_uuid(ctx.user_id),
        )
    )
    await write_audit(
        session,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        action="prompt.experiment.create",
        resource_type="prompt_experiment",
        resource_id=row.id,
        metadata={"prompt_name": body.prompt_name, "split_pct": body.split_pct},
    )
    await session.commit()
    await session.refresh(row)
    return _experiment_public(row)


@router.post(
    "/prompt-experiments/{experiment_id}/stop",
    response_model=PromptExperimentPublic,
    dependencies=[Depends(require_role(_FORK_ROLES))],
)
@require_tier(TierFlag.CLOUD | TierFlag.LOCAL)
async def stop_prompt_experiment(
    experiment_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> PromptExperimentPublic:
    """Stop an experiment (subsequent resolution falls back to fork/default)."""
    row = await PromptExperimentRepo(session).stop(ctx.workspace_id, experiment_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="experiment not found")
    await session.commit()
    await session.refresh(row)
    return _experiment_public(row)


@router.post(
    "/prompt-experiments/{experiment_id}/outcome",
    response_model=PromptExperimentPublic,
)
async def record_experiment_outcome(
    experiment_id: str,
    body: ExperimentOutcomeBody,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> PromptExperimentPublic:
    """Record a success/failure outcome for a variant (any workspace member)."""
    repo = PromptExperimentRepo(session)
    exp = await repo.get_by_id(experiment_id)
    if exp is None or exp.workspace_id != ctx.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="experiment not found")
    variant: Literal["A", "B"] = "A" if body.variant == "A" else "B"
    row = await repo.record_outcome(experiment_id, variant, success=body.success)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="experiment not found")
    await session.commit()
    await session.refresh(row)
    return _experiment_public(row)
