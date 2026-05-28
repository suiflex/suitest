"""Integration read endpoints (docs/API.md §3.9) — workspace-scoped, secrets redacted.

The list never touches secret material. The detail decrypts the stored secret
ONCE solely to surface its last 4 characters as a ``hint`` — the full plaintext is
never placed on the response. This is the only read path that decrypts, and only
the tail is exposed (docs/API.md §3.9, plan 7g.2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.integration import Integration
from suitest_db.repositories.integrations import IntegrationRepo
from suitest_shared.domain.enums import IntegrationKind

from suitest_api.auth.db import get_async_session
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.schemas.integration import (
    IntegrationDetail,
    IntegrationListItem,
    SecretsHint,
)

router = APIRouter(prefix="/api/v1", tags=["integrations"])


def _to_list_item(row: Integration) -> IntegrationListItem:
    return IntegrationListItem(
        id=row.id,
        workspace_id=row.workspace_id,
        kind=row.kind,
        name=row.name,
        status=row.status,
        has_secrets=row.secrets_encrypted is not None,
        last_synced_at=row.last_synced_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _secrets_hint(row: Integration) -> SecretsHint | None:
    """Build the redacted secrets block: ``None`` if absent, else last-4 hint.

    ``secrets_encrypted`` is an ``EncryptedBytes`` column, so reading it decrypts
    the plaintext; we keep only the last 4 chars and discard the rest immediately.
    """
    plaintext = row.secrets_encrypted
    if plaintext is None:
        return None
    tail = plaintext[-4:] if len(plaintext) >= 4 else plaintext
    return SecretsHint(redacted=True, hint=f"…{tail}")


@router.get("/integrations", response_model=list[IntegrationListItem])
async def list_integrations(
    kind: IntegrationKind | None = Query(default=None),
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> list[IntegrationListItem]:
    """List the workspace's integrations (optionally filtered by kind)."""
    rows = await IntegrationRepo(session).list_by_workspace(ctx.workspace_id, kind=kind)
    return [_to_list_item(r) for r in rows]


@router.get("/integrations/{integration_id}", response_model=IntegrationDetail)
async def get_integration(
    integration_id: str,
    ctx: TenantContext = Depends(require_workspace_membership),
    session: AsyncSession = Depends(get_async_session),
) -> IntegrationDetail:
    """Return an integration with config + REDACTED secrets; 404 if cross-workspace."""
    row = await IntegrationRepo(session).get_by_id(integration_id)
    if row is None or row.workspace_id != ctx.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="integration not found")
    base = _to_list_item(row)
    return IntegrationDetail(
        **base.model_dump(),
        config=row.config,
        secrets=_secrets_hint(row),
    )
