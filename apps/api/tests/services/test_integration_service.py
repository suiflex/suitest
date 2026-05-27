"""IntegrationService tests — secret redaction + workspace scoping."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from suitest_api.deps.scope import TenantContext
from suitest_api.services.integration_service import IntegrationService
from suitest_db.models.integration import Integration
from suitest_shared.domain.enums import IntegrationKind, Role

_NOW = datetime(2026, 5, 28, tzinfo=UTC)


def _ctx(ws: str = "ws_1") -> TenantContext:
    return TenantContext(
        workspace_id=ws, user_id="00000000-0000-0000-0000-000000000001", role=Role.ADMIN
    )


def _integration(ws: str, secret: str | None) -> Integration:
    i = Integration(
        id="int_1",
        workspace_id=ws,
        kind=IntegrationKind.GITHUB,
        name="gh",
        config={"org": "acme"},
        secrets_encrypted=secret,
        status="active",
    )
    i.created_at = _NOW
    i.updated_at = _NOW
    i.last_synced_at = None
    return i


@pytest.mark.asyncio
async def test_integration_scopes_by_workspace() -> None:
    repo = AsyncMock()
    repo.list_by_workspace.return_value = [_integration("ws_1", "cipher")]
    svc = IntegrationService(_ctx("ws_1"), repo)

    out = await svc.list()

    repo.list_by_workspace.assert_awaited_once_with("ws_1", kind=None)
    assert [i.id for i in out] == ["int_1"]


@pytest.mark.asyncio
async def test_integration_redacts_secrets() -> None:
    repo = AsyncMock()
    repo.list_by_workspace.return_value = [_integration("ws_1", "super-secret-cipher")]
    svc = IntegrationService(_ctx("ws_1"), repo)

    out = await svc.list()
    dto = out[0]

    dumped = dto.model_dump()
    assert "secrets_encrypted" not in dumped
    assert "super-secret-cipher" not in str(dumped)
    assert dto.has_secrets is True

    # No-secret integration reports has_secrets False.
    repo.list_by_workspace.return_value = [_integration("ws_1", None)]
    out2 = await svc.list()
    assert out2[0].has_secrets is False


@pytest.mark.asyncio
async def test_integration_get_404_when_cross_workspace() -> None:
    repo = AsyncMock()
    repo.get_by_id.return_value = _integration("ws_OTHER", "cipher")
    svc = IntegrationService(_ctx("ws_1"), repo)

    assert await svc.get_by_id("int_1") is None
