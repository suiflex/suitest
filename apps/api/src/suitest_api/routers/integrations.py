"""Integration read + write endpoints (docs/API.md §3.9) — workspace-scoped, secrets redacted.

The list never touches secret material. The detail decrypts the stored secret
ONCE solely to surface its last 4 characters as a ``hint`` — the full plaintext is
never placed on the response. This is the only read path that decrypts, and only
the tail is exposed (docs/API.md §3.9, plan 7g.2).

M1d-19 adds the write surface: ``POST /integrations``, ``PATCH /integrations/:id``,
``DELETE /integrations/:id``, ``POST /integrations/:id/test`` (existing-row test
connection), ``POST /integrations/:id/sync`` (issue-tracker only), plus the
pre-save ``POST /integrations/jira/test-connection`` and ``POST
/integrations/github/test-connection`` validators. All writes are gated by
``Role.ADMIN`` or ``Role.OWNER`` per ``docs/API.md §3.9``. Secrets are AES-GCM
encrypted at rest via :class:`suitest_core.crypto.EncryptedBytes` and NEVER
echoed in :class:`IntegrationRead` (only ``has_secrets: bool`` surfaces).
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from suitest_db.models.integration import Integration
from suitest_db.repositories.integrations import IntegrationRepo
from suitest_shared.domain.enums import IntegrationKind, Role

from suitest_api.auth.db import get_async_session
from suitest_api.deps.integrations import (
    PreSaveTestFactory,
    get_adapter_registry,
    get_notifier_factories,
    get_pre_save_github_factory,
    get_pre_save_jira_factory,
)
from suitest_api.deps.role import require_role
from suitest_api.deps.scope import TenantContext, require_workspace_membership
from suitest_api.integrations.base import (
    AdapterAuthError,
    AdapterError,
    AdapterRateLimitError,
    AdapterRemoteError,
    AdapterTimeoutError,
    ConnectionTestResult,
)
from suitest_api.integrations.registry import AdapterRegistry, NotifierFactory
from suitest_api.schemas.integration import (
    ConnectionTestResponse,
    GitHubTestConnectionRequest,
    IntegrationCreate,
    IntegrationDetail,
    IntegrationListItem,
    IntegrationRead,
    IntegrationUpdate,
    JiraTestConnectionRequest,
    SecretsHint,
    SyncResult,
)
from suitest_api.services.integration_service import (
    IntegrationKindUnsupportedError,
    IntegrationService,
)
from suitest_api.ws.publisher import publish_event

router = APIRouter(prefix="/api/v1", tags=["integrations"])

# Role gate shared by every mutating endpoint (docs/API.md §3.9).
_ADMIN_ROLES: set[Role] = {Role.ADMIN, Role.OWNER}
_admin_dep = require_role(_ADMIN_ROLES)


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


def _to_read(row: Integration) -> IntegrationRead:
    """Build the :class:`IntegrationRead` write-path DTO (no secret echo)."""
    return IntegrationRead(
        id=row.id,
        workspace_id=row.workspace_id,
        kind=row.kind,
        name=row.name,
        status=row.status,
        has_secrets=row.secrets_encrypted is not None,
        last_synced_at=row.last_synced_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        config=row.config,
    )


def _error_envelope(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    """Canonical ``{"error": {...}}`` payload per docs/API.md §3."""
    return {"error": {"code": code, "message": message, "details": details}}


def _build_service(
    session: AsyncSession,
    ctx: TenantContext,
    *,
    adapter_registry: AdapterRegistry | None = None,
    notifier_factories: dict[IntegrationKind, NotifierFactory] | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> IntegrationService:
    return IntegrationService(
        ctx,
        IntegrationRepo(session),
        adapter_registry=adapter_registry,
        notifier_factories=notifier_factories,
        http_client=http_client,
    )


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


# ---------------------------------------------------------------------------
# Write surface — M1d-19
# ---------------------------------------------------------------------------


@router.post(
    "/integrations",
    response_model=IntegrationRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_integration(
    body: IntegrationCreate,
    request: Request,
    ctx: TenantContext = Depends(_admin_dep),
    session: AsyncSession = Depends(get_async_session),
) -> IntegrationRead:
    """Connect a new integration. ADMIN/OWNER; secrets AES-GCM encrypted; never echoed."""
    svc = _build_service(session, ctx)
    outcome = await svc.create(
        kind=body.kind,
        name=body.name,
        config=body.config,
        secrets=body.secrets,
    )
    await session.commit()
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    # Refetch from DB so the response reflects committed timestamps + the
    # post-flip enabled state. Single round-trip — cheap.
    row = await IntegrationRepo(session).get_by_id(outcome.out.id)
    assert row is not None, "integration row missing after commit"
    return _to_read(row)


@router.patch(
    "/integrations/{integration_id}",
    response_model=IntegrationRead,
)
async def update_integration(
    integration_id: str,
    body: IntegrationUpdate,
    request: Request,
    ctx: TenantContext = Depends(_admin_dep),
    session: AsyncSession = Depends(get_async_session),
) -> IntegrationRead:
    """Patch an integration. Partial; absent ``secrets`` preserves the existing blob."""
    svc = _build_service(session, ctx)
    secrets_present = "secrets" in body.model_fields_set
    outcome = await svc.update(
        integration_id,
        name=body.name,
        config=body.config,
        secrets=body.secrets,
        status=body.status,
        secrets_field_present=secrets_present,
    )
    if outcome is None:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="integration not found")
    await session.commit()
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    row = await IntegrationRepo(session).get_by_id(outcome.out.id)
    assert row is not None, "integration row missing after commit"
    return _to_read(row)


@router.delete(
    "/integrations/{integration_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_integration(
    integration_id: str,
    request: Request,
    ctx: TenantContext = Depends(_admin_dep),
    session: AsyncSession = Depends(get_async_session),
) -> None:
    """Hard-delete an integration. ADMIN/OWNER. No body."""
    svc = _build_service(session, ctx)
    outcome = await svc.delete(integration_id)
    if outcome is None:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="integration not found")
    await session.commit()
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event=outcome.ws_event,
        data=outcome.ws_payload,
    )
    return None


# ---------------------------------------------------------------------------
# Test connection (existing row)
# ---------------------------------------------------------------------------


def _connection_test_to_response(result: ConnectionTestResult) -> ConnectionTestResponse:
    return ConnectionTestResponse(
        ok=result.ok,
        account_id=result.account_id,
        display_name=result.display_name,
        error=result.error,
    )


@router.post(
    "/integrations/{integration_id}/test",
    response_model=ConnectionTestResponse,
)
async def test_integration(
    integration_id: str,
    request: Request,
    ctx: TenantContext = Depends(_admin_dep),
    session: AsyncSession = Depends(get_async_session),
    adapter_registry: AdapterRegistry = Depends(get_adapter_registry),
    notifier_factories: dict[IntegrationKind, NotifierFactory] = Depends(get_notifier_factories),
) -> ConnectionTestResponse:
    """Smoke-test an existing integration's credentials. Never 500s on bad creds."""
    # Per-request httpx client is cheap and isolates Slack-style notifier
    # invocations from cross-request connection reuse.
    async with httpx.AsyncClient() as http_client:
        svc = _build_service(
            session,
            ctx,
            adapter_registry=adapter_registry,
            notifier_factories=notifier_factories,
            http_client=http_client,
        )
        try:
            result = await svc.test_connection(integration_id)
        except IntegrationKindUnsupportedError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_error_envelope(
                    "INTEGRATION_KIND_UNSUPPORTED",
                    f"No adapter registered for integration kind '{exc.kind.value}'.",
                    {"kind": exc.kind.value},
                ),
            ) from exc
    if result is None:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="integration not found")
    await session.commit()
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event="integration.tested",
        data={"integrationId": integration_id, "ok": result.ok},
    )
    return _connection_test_to_response(result)


# ---------------------------------------------------------------------------
# Sync external (issue-tracker only)
# ---------------------------------------------------------------------------


@router.post(
    "/integrations/{integration_id}/sync",
    response_model=SyncResult,
)
async def sync_integration(
    integration_id: str,
    request: Request,
    ctx: TenantContext = Depends(_admin_dep),
    session: AsyncSession = Depends(get_async_session),
    adapter_registry: AdapterRegistry = Depends(get_adapter_registry),
    notifier_factories: dict[IntegrationKind, NotifierFactory] = Depends(get_notifier_factories),
) -> SyncResult:
    """Refetch external statuses for every linked defect; update local status with conflict reporting."""
    async with httpx.AsyncClient() as http_client:
        svc = _build_service(
            session,
            ctx,
            adapter_registry=adapter_registry,
            notifier_factories=notifier_factories,
            http_client=http_client,
        )
        try:
            result = await svc.sync_external(integration_id)
        except IntegrationKindUnsupportedError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=_error_envelope(
                    "INTEGRATION_KIND_UNSUPPORTED",
                    f"Sync not supported for integration kind '{exc.kind.value}'.",
                    {"kind": exc.kind.value},
                ),
            ) from exc
    if result is None:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="integration not found")
    await session.commit()
    await publish_event(
        request,
        topic=f"workspace:{ctx.workspace_id}",
        event="integration.synced",
        data={
            "integrationId": integration_id,
            "synced": result.synced,
            "skipped": result.skipped,
            "conflicts": len(result.conflicts),
        },
    )
    return result


# ---------------------------------------------------------------------------
# Pre-save credential validation
# ---------------------------------------------------------------------------


async def _run_pre_save_test(
    factory: PreSaveTestFactory | None, body: dict[str, str], kind_label: str
) -> ConnectionTestResponse:
    """Shared helper: invoke the pre-save factory, catch adapter errors, return DTO."""
    if factory is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=_error_envelope(
                "INTEGRATION_KIND_UNSUPPORTED",
                f"Pre-save test factory for '{kind_label}' is not wired in this deployment.",
                {"kind": kind_label},
            ),
        )
    adapter = factory(body)
    try:
        result = await adapter.test_connection()
    except AdapterAuthError as exc:
        result = ConnectionTestResult(ok=False, error=f"AUTH: {exc}")
    except AdapterRateLimitError as exc:
        result = ConnectionTestResult(ok=False, error=f"RATE_LIMIT: {exc}")
    except AdapterTimeoutError as exc:
        result = ConnectionTestResult(ok=False, error=f"TIMEOUT: {exc}")
    except AdapterRemoteError as exc:
        result = ConnectionTestResult(ok=False, error=f"REMOTE: {exc}")
    except AdapterError as exc:
        result = ConnectionTestResult(ok=False, error=str(exc))
    return _connection_test_to_response(result)


@router.post(
    "/integrations/jira/test-connection",
    response_model=ConnectionTestResponse,
)
async def test_jira_pre_save(
    body: JiraTestConnectionRequest,
    _ctx: TenantContext = Depends(_admin_dep),
    factory: PreSaveTestFactory | None = Depends(get_pre_save_jira_factory),
) -> ConnectionTestResponse:
    """Validate Jira credentials BEFORE persisting. Never logs ``jira_token``."""
    return await _run_pre_save_test(
        factory,
        {
            "jira_url": body.jira_url,
            "jira_email": body.jira_email,
            "jira_token": body.jira_token,
            "jira_auth_type": body.jira_auth_type,
        },
        "JIRA",
    )


@router.post(
    "/integrations/github/test-connection",
    response_model=ConnectionTestResponse,
)
async def test_github_pre_save(
    body: GitHubTestConnectionRequest,
    _ctx: TenantContext = Depends(_admin_dep),
    factory: PreSaveTestFactory | None = Depends(get_pre_save_github_factory),
) -> ConnectionTestResponse:
    """Validate GitHub App credentials BEFORE persisting. Never logs ``private_key_pem``."""
    return await _run_pre_save_test(
        factory,
        {
            "app_installation_id": body.app_installation_id,
            "private_key_pem": body.private_key_pem,
        },
        "GITHUB",
    )
